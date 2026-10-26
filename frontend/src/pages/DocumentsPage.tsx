import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ExternalLink, FileText, RotateCw, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useOutletContext } from "react-router";
import type { CourseContext } from "@/components/CourseLayout";
import { StatusSteps } from "@/components/StatusSteps";
import { Button, ErrorNote, Loading, errorMessage } from "@/components/ui";
import { api, type DocumentRow } from "@/lib/api/client";
import { keys, useDeleteDocument, useDocuments, useReprocessDocument } from "@/lib/queries";

const ACCEPT = ".pdf,.docx,.txt,.md";
const MAX_MB = 50;

interface PendingUpload {
  id: string;
  name: string;
  progress: number;
  error?: string;
}

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function DropZone({ courseId }: { courseId: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState<PendingUpload[]>([]);

  const update = (id: string, patch: Partial<PendingUpload>) =>
    setPending((list) => list.map((p) => (p.id === id ? { ...p, ...patch } : p)));

  const send = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const id = crypto.randomUUID();
      if (file.size > MAX_MB * 1024 * 1024) {
        setPending((l) => [...l, { id, name: file.name, progress: 0, error: `Larger than ${MAX_MB} MB` }]);
        continue;
      }
      setPending((l) => [...l, { id, name: file.name, progress: 0 }]);
      try {
        await api.upload<DocumentRow>(`/api/courses/${courseId}/documents`, file, (f) =>
          update(id, { progress: f }),
        );
        setPending((l) => l.filter((p) => p.id !== id));
        qc.invalidateQueries({ queryKey: keys.documents(courseId) });
        qc.invalidateQueries({ queryKey: keys.course(courseId) });
      } catch (e) {
        update(id, { error: errorMessage(e) });
      }
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) void send(e.dataTransfer.files);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "flex flex-col items-start gap-4 rounded-lg border-2 border-dashed px-6 py-7 sm:flex-row sm:items-center",
          dragging ? "border-ink bg-highlight-soft" : "border-rule-strong bg-sheet",
        )}
      >
        <Upload className="size-6 shrink-0 text-graphite" aria-hidden />
        <div className="flex-1">
          <p className="font-medium text-ink">Drop files here</p>
          <p className="text-sm text-graphite">PDF, DOCX, TXT or MD, up to {MAX_MB} MB</p>
        </div>
        <Button variant="secondary" onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          className="sr-only"
          onChange={(e) => {
            if (e.target.files) void send(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {pending.length > 0 && (
        <ul className="mt-3 space-y-2">
          {pending.map((p) => (
            <li key={p.id} className="flex items-center gap-3 text-sm">
              <span className="w-56 truncate">{p.name}</span>
              {p.error ? (
                <>
                  <span className="text-correction">{p.error}</span>
                  <button
                    className="text-xs text-graphite underline"
                    onClick={() => setPending((l) => l.filter((x) => x.id !== p.id))}
                  >
                    Dismiss
                  </button>
                </>
              ) : (
                <span className="h-1 w-40 overflow-hidden rounded-full bg-rule">
                  <span
                    className="block h-full bg-ink transition-[width]"
                    style={{ width: `${Math.round(p.progress * 100)}%` }}
                  />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DocumentsPage() {
  const { course, isInstructor } = useOutletContext<CourseContext>();
  const docs = useDocuments(course.id);
  const remove = useDeleteDocument(course.id);
  const reprocess = useReprocessDocument(course.id);

  const confirmDelete = (d: DocumentRow) => {
    if (window.confirm(`Delete “${d.filename}”?`)) {
      remove.mutate(d.id);
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-5 py-8 sm:px-8">
      {isInstructor ? (
        <DropZone courseId={course.id} />
      ) : (
        <p className="text-sm text-graphite">Only instructors can add materials.</p>
      )}

      {docs.isPending && <Loading />}
      {docs.isError && <ErrorNote>{errorMessage(docs.error)}</ErrorNote>}
      {remove.isError && <ErrorNote>{errorMessage(remove.error)}</ErrorNote>}

      {docs.data?.length === 0 && (
        <p className="text-graphite">
          No materials yet.
        </p>
      )}

      {docs.data && docs.data.length > 0 && (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Course materials</caption>
          <thead className="border-b border-rule text-xs text-graphite">
            <tr>
              <th className="py-2 pr-4 font-medium">Name</th>
              <th className="hidden py-2 pr-4 font-medium sm:table-cell">Size</th>
              <th className="hidden py-2 pr-4 font-medium md:table-cell">Added</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {docs.data.map((d) => (
              <tr key={d.id} className="align-top">
                <td className="py-4 pr-4">
                  <div className="flex items-start gap-2.5">
                    <FileText className="mt-0.5 size-4 shrink-0 text-pencil" aria-hidden />
                    <div className="min-w-0">
                      <p className="break-words font-medium text-ink">{d.filename}</p>
                      {d.status === "indexed" && (
                        <p className="text-xs text-graphite">
                          {d.page_count && d.mime_type === "application/pdf"
                            ? `${d.page_count} pages, `
                            : ""}
                          {d.chunk_count} passages
                        </p>
                      )}
                      {d.status === "failed" && d.error_message && (
                        <p className="mt-1 max-w-md text-xs text-correction">{d.error_message}</p>
                      )}
                    </div>
                  </div>
                </td>
                <td className="hidden py-4 pr-4 tabular-nums text-graphite sm:table-cell">
                  {formatSize(d.file_size)}
                </td>
                <td className="hidden py-4 pr-4 text-graphite md:table-cell">
                  {formatDate(d.created_at)}
                </td>
                <td className="py-4 pr-4">
                  <StatusSteps status={d.status} />
                </td>
                <td className="py-3">
                  <div className="flex justify-end gap-1">
                    <a
                      href={`/api/courses/${course.id}/documents/${d.id}/file`}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded p-2 text-graphite hover:bg-rule/60 hover:text-ink"
                      title="Open original file"
                      aria-label={`Open ${d.filename}`}
                    >
                      <ExternalLink className="size-4" />
                    </a>
                    {isInstructor && (d.status === "failed" || d.status === "indexed") && (
                      <button
                        onClick={() => reprocess.mutate(d.id)}
                        className="rounded p-2 text-graphite hover:bg-rule/60 hover:text-ink"
                        title="Index again"
                        aria-label={`Index ${d.filename} again`}
                      >
                        <RotateCw className="size-4" />
                      </button>
                    )}
                    {isInstructor && (
                      <button
                        onClick={() => confirmDelete(d)}
                        className="rounded p-2 text-graphite hover:bg-correction-soft hover:text-correction"
                        title="Delete"
                        aria-label={`Delete ${d.filename}`}
                      >
                        <Trash2 className="size-4" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
