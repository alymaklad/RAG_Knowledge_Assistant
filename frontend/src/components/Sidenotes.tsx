import clsx from "clsx";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { Source } from "@/lib/api/client";
import { bestExcerpt, citedNumbers, textCiting } from "@/lib/citations";

export function sourceLocation(s: Source): string {
  const parts: string[] = [];
  if (s.page_num) parts.push(`Page ${s.page_num}`);
  if (s.section_header) parts.push(s.section_header);
  return parts.join(", ");
}

export function fileUrl(courseId: string, s: Source): string {
  return `/api/courses/${courseId}/documents/${s.document_id}/file${s.page_num ? `#page=${s.page_num}` : ""}`;
}

function Excerpt({ source, answer }: { source: Source; answer: string }) {
  const ex = useMemo(
    () => bestExcerpt(source.text, textCiting(answer, source.index) || answer, 110),
    [source.text, source.index, answer],
  );
  if (!answer.trim()) {
    // Nothing to match against until the answer starts streaming.
    return (
      <p className="mt-2 line-clamp-3 font-read text-[0.9rem] leading-relaxed text-graphite">
        {source.text}
      </p>
    );
  }
  return (
    <p className="mt-2 font-read text-[0.9rem] leading-relaxed text-graphite">
      {ex.before}
      {ex.before && " "}
      <mark className="marker">{ex.marked}</mark>
      {ex.after && " "}
      {ex.after}
    </p>
  );
}

/**
 * Sources in the margin, aligned with the answer that cites them. Cited sources come first;
 * passages that were retrieved but not cited are folded away.
 */
export function Sidenotes({
  sources,
  answer,
  active,
  onActive,
  onOpen,
}: {
  sources: Source[];
  answer: string;
  active: number | null;
  onActive: (n: number | null) => void;
  onOpen: (s: Source) => void;
}) {
  const cited = citedNumbers(answer);
  const primary = sources.filter((s) => cited.has(s.index));
  const rest = sources.filter((s) => !cited.has(s.index));
  const refs = useRef<Record<number, HTMLLIElement | null>>({});

  useEffect(() => {
    if (active != null) refs.current[active]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  if (sources.length === 0) return null;

  const note = (s: Source) => (
    <li
      key={s.index}
      ref={(el) => {
        refs.current[s.index] = el;
      }}
      onMouseEnter={() => onActive(s.index)}
      onMouseLeave={() => onActive(null)}
      className={clsx(
        "border-l-2 pl-3.5 transition-colors",
        active === s.index ? "border-ink" : "border-highlight",
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(s)}
        className="block w-full text-left"
        aria-label={`Open source ${s.index}: ${s.document_name}`}
      >
        <p className="flex items-baseline gap-1.5 text-sm font-medium text-ink">
          <span
            className={clsx(
              "rounded-sm px-1 text-xs",
              active === s.index ? "bg-ink text-paper" : "bg-highlight text-[#1f2544]",
            )}
          >
            {s.index}
          </span>
          <span className="min-w-0 break-words">{s.document_name}</span>
        </p>
        {sourceLocation(s) && <p className="mt-0.5 text-xs text-graphite">{sourceLocation(s)}</p>}
        <Excerpt source={s} answer={answer} />
      </button>
    </li>
  );

  return (
    <div className="text-sm">
      <ol className="space-y-6">{(primary.length ? primary : sources).map(note)}</ol>
      {primary.length > 0 && rest.length > 0 && (
        <details className="mt-6 text-xs text-graphite">
          <summary className="cursor-pointer select-none hover:text-ink">
            {rest.length} more {rest.length === 1 ? "match" : "matches"}
          </summary>
          <ol className="mt-4 space-y-6">{rest.map(note)}</ol>
        </details>
      )}
    </div>
  );
}

/** Full text of one source, with the answer's matching sentence highlighted. */
export function SourceDrawer({
  courseId,
  source,
  answer,
  onClose,
}: {
  courseId: string;
  source: Source;
  answer: string;
  onClose: () => void;
}) {
  const ex = useMemo(
    () => bestExcerpt(source.text, textCiting(answer, source.index) || answer, 100_000),
    [source, answer],
  );
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Source passage">
      <div className="absolute inset-0 bg-ink/25" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-sheet shadow-2xl">
        <header className="flex items-start gap-3 border-b border-rule px-6 py-5">
          <span className="mt-0.5 rounded-sm bg-highlight px-1.5 text-sm font-medium text-[#1f2544]">
            {source.index}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="break-words font-read text-lg font-semibold">{source.document_name}</h2>
            {sourceLocation(source) && (
              <p className="text-sm text-graphite">{sourceLocation(source)}</p>
            )}
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="rounded p-1.5 text-graphite hover:bg-rule/60 hover:text-ink"
            aria-label="Close"
          >
            <X className="size-5" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="prose-read whitespace-pre-line text-ink">
            {ex.before} <mark className="marker">{ex.marked}</mark> {ex.after}
          </p>
        </div>
        <footer className="flex items-center justify-between gap-4 border-t border-rule px-6 py-4 text-sm">
          <span className="text-graphite">Match score {source.score.toFixed(2)}</span>
          <a
            href={fileUrl(courseId, source)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 font-medium text-ink underline decoration-highlight decoration-2 underline-offset-4"
          >
            Open {source.page_num ? `page ${source.page_num}` : "the document"}
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        </footer>
      </aside>
    </div>
  );
}
