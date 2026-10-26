import clsx from "clsx";
import type { DocStatus } from "@/lib/api/client";

const STEPS: { status: DocStatus; label: string }[] = [
  { status: "extracting", label: "Reading" },
  { status: "chunking", label: "Splitting" },
  { status: "embedding", label: "Indexing" },
  { status: "indexed", label: "Ready" },
];

const ORDER: Record<DocStatus, number> = {
  uploaded: -1,
  extracting: 0,
  chunking: 1,
  embedding: 2,
  indexed: 3,
  failed: -2,
};

/** Indexing is a sequence, so it is shown as one: four steps, current one labelled. */
export function StatusSteps({ status }: { status: DocStatus }) {
  if (status === "failed") {
    return <span className="text-sm font-medium text-correction">Couldn’t index</span>;
  }
  if (status === "indexed") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-ok">
        <span className="size-1.5 rounded-full bg-ok" aria-hidden />
        Ready
      </span>
    );
  }
  const current = ORDER[status];
  const label = current < 0 ? "Queued" : STEPS[current].label;
  return (
    <div className="min-w-40" aria-live="polite">
      <div className="flex gap-1" aria-hidden>
        {STEPS.map((s, i) => (
          <span
            key={s.status}
            className={clsx(
              "h-1 flex-1 rounded-full",
              i < current && "bg-ink",
              i === current && "animate-pulse bg-highlight",
              i > current && "bg-rule",
            )}
          />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-graphite">
        {label}
      </p>
    </div>
  );
}
