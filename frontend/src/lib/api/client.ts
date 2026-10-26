import type { components } from "./schema";

type Schemas = components["schemas"];
export type User = Schemas["UserOut"];
export type Course = Schemas["CourseOut"];
export type Member = Schemas["MemberOut"];
export type MemberRole = Schemas["MemberRole"];
export type DocumentRow = Schemas["DocumentOut"];
export type DocStatus = Schemas["DocStatus"];
export type ChatSession = Schemas["SessionOut"];
export type ChatMessage = Schemas["MessageOut"];

/** A cited chunk, as sent in the `sources` SSE event and stored on assistant messages. */
export interface Source {
  index: number;
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_num: number | null;
  section_header: string | null;
  score: number;
  text: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Endpoints where a 401 means bad credentials, not an expired session.
const NO_REFRESH = ["/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/auth/logout"];

export function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

export function authHeaders(method: string): Record<string, string> {
  const csrf = readCookie("csrf_token");
  return UNSAFE.has(method) && csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {};
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      const first = body.detail[0];
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "";
      message = field ? `${field}: ${first.msg}` : first.msg;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message);
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the refresh cookie for a new access cookie. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
    headers: authHeaders("POST"),
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** fetch() with cookies, CSRF header, and one silent refresh-and-retry on 401. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const send = () =>
    fetch(path, {
      ...init,
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...authHeaders(method), ...init.headers },
    });
  let res = await send();
  if (res.status === 401 && !NO_REFRESH.includes(path) && (await refreshSession())) {
    res = await send();
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const body = (data: unknown): RequestInit => ({
  body: JSON.stringify(data),
  headers: { "Content-Type": "application/json" },
});

export const api = {
  get: <T>(path: string) => json<T>(path),
  post: <T>(path: string, data?: unknown) =>
    json<T>(path, { method: "POST", ...(data === undefined ? {} : body(data)) }),
  patch: <T>(path: string, data: unknown) => json<T>(path, { method: "PATCH", ...body(data) }),
  del: (path: string) => json<void>(path, { method: "DELETE" }),

  /** Multipart upload with progress (fetch has no upload progress events). */
  upload<T>(path: string, file: File, onProgress?: (fraction: number) => void): Promise<T> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", path);
      xhr.withCredentials = true;
      for (const [k, v] of Object.entries(authHeaders("POST"))) xhr.setRequestHeader(k, v);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(parsed as T);
        else {
          const detail = (parsed as { detail?: unknown })?.detail;
          reject(new ApiError(xhr.status, typeof detail === "string" ? detail : "Upload failed"));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
};
