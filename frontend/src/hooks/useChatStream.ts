import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, type ChatMessage, type ChatSession, type Source } from "@/lib/api/client";
import { keys, useMessages } from "@/lib/queries";
import { readSse } from "@/lib/sse";

export interface ViewMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  status: "streaming" | "done" | "error";
  error?: string;
}

function fromServer(m: ChatMessage): ViewMessage {
  return {
    id: m.id,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    sources: (m.source_chunks as unknown as Source[]) ?? [],
    status: "done",
  };
}

/**
 * Chat state for one course: loads a session's history, sends questions to POST /api/chat and
 * applies the SSE stream (session -> sources -> token* -> done | error) to the transcript.
 */
export function useChatStream(
  courseId: string,
  sessionId: string | undefined,
  onSession: (s: ChatSession) => void,
) {
  const qc = useQueryClient();
  const history = useMessages(sessionId);
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const onSessionRef = useRef(onSession);
  onSessionRef.current = onSession;

  // Server history replaces the view, except while an answer is streaming in.
  useEffect(() => {
    if (streamingRef.current) return;
    if (!sessionId) setMessages([]);
    else if (history.data) setMessages(history.data.map(fromServer));
  }, [sessionId, history.data]);

  const patchLast = (patch: (m: ViewMessage) => ViewMessage) =>
    setMessages((list) => {
      const copy = list.slice();
      copy[copy.length - 1] = patch(copy[copy.length - 1]);
      return copy;
    });

  const send = useCallback(
    async (text: string, documentIds?: string[]) => {
      if (streamingRef.current) return;
      streamingRef.current = true;
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      let session = sessionId;
      setMessages((list) => [
        ...list,
        { id: `u-${Date.now()}`, role: "user", content: text, sources: [], status: "done" },
        { id: `a-${Date.now()}`, role: "assistant", content: "", sources: [], status: "streaming" },
      ]);

      try {
        const res = await apiFetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          body: JSON.stringify({
            course_id: courseId,
            session_id: sessionId ?? null,
            message: text,
            document_ids: documentIds?.length ? documentIds : null,
          }),
          signal: controller.signal,
        });
        if (!res.body) throw new Error("The server sent no response body.");
        for await (const ev of readSse(res.body)) {
          if (ev.event === "session") {
            const s = ev.data as ChatSession;
            session = s.id;
            onSessionRef.current(s);
          } else if (ev.event === "sources") {
            patchLast((m) => ({ ...m, sources: ev.data as Source[] }));
          } else if (ev.event === "token") {
            const t = (ev.data as { t: string }).t;
            patchLast((m) => ({ ...m, content: m.content + t }));
          } else if (ev.event === "done") {
            patchLast((m) => ({ ...m, status: "done" }));
          } else if (ev.event === "error") {
            const message = (ev.data as { message?: string }).message ?? "The answer failed.";
            patchLast((m) => ({ ...m, status: "error", error: message }));
          }
        }
        patchLast((m) => (m.status === "streaming" ? { ...m, status: "done" } : m));
      } catch (e) {
        const aborted = e instanceof DOMException && e.name === "AbortError";
        patchLast((m) => ({
          ...m,
          status: aborted ? "done" : "error",
          content: aborted && m.content ? `${m.content}\n\n*(stopped)*` : m.content,
          error: aborted ? undefined : e instanceof Error ? e.message : "The answer failed.",
        }));
      } finally {
        streamingRef.current = false;
        setStreaming(false);
        abortRef.current = null;
        qc.invalidateQueries({ queryKey: keys.sessions(courseId) });
        qc.invalidateQueries({ queryKey: keys.course(courseId) });
        if (session) qc.invalidateQueries({ queryKey: keys.messages(session) });
      }
    },
    [courseId, sessionId, qc],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { messages, send, stop, streaming, loading: Boolean(sessionId) && history.isPending };
}
