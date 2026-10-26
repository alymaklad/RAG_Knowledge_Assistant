import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useOutletContext } from "react-router";
import type { CourseContext } from "@/components/CourseLayout";
import { ErrorNote, Loading, errorMessage } from "@/components/ui";
import { api } from "@/lib/api/client";

interface Analytics {
  days: number;
  totals: { questions: number; students: number; unanswered: number; avg_latency_ms: number | null };
  per_day: { day: string; questions: number }[];
  top_questions: { question: string; count: number }[];
  unanswered: { question: string; count: number; last_asked: string }[];
  top_documents: { document_name: string; citations: number }[];
  top_sections: { document_name: string; section: string | null; page_num: number | null; citations: number }[];
}

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-graphite">{label}</dt>
      <dd className="mt-1 font-read text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,1fr)_3rem] items-center gap-3 text-sm">
          <div className="min-w-0">
            <p className="truncate" title={r.label}>
              {r.label}
            </p>
            <div className="mt-1 h-1.5 rounded-full bg-rule">
              <div className="h-full rounded-full bg-ink" style={{ width: `${(r.value / max) * 100}%` }} />
            </div>
          </div>
          <span className="text-right tabular-nums text-graphite">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-rule pt-5">
      <h2 className="font-read text-lg font-semibold">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function InsightsPage() {
  const { course, isInstructor } = useOutletContext<CourseContext>();
  const [days, setDays] = useState(30);
  const data = useQuery({
    queryKey: ["courses", course.id, "analytics", days],
    queryFn: () => api.get<Analytics>(`/api/courses/${course.id}/analytics?days=${days}`),
    enabled: isInstructor,
  });
  if (!isInstructor) return <Navigate to="../chat" relative="path" replace />;

  const a = data.data;
  // Every day in the range, including quiet ones, so the chart reads as a timeline.
  const counts = new Map(a?.per_day.map((d) => [d.day, d.questions]) ?? []);
  const timeline = Array.from({ length: days }, (_, k) => {
    const day = new Date(Date.now() - (days - 1 - k) * 86_400_000).toISOString().slice(0, 10);
    return { day, questions: counts.get(day) ?? 0 };
  });
  const maxDay = Math.max(1, ...timeline.map((d) => d.questions));

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-5 py-8 sm:px-8">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-graphite">
          Last
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-ink"
          >
            {[7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </label>
      </div>
      {data.isPending && <Loading />}
      {data.isError && <ErrorNote>{errorMessage(data.error)}</ErrorNote>}
      {a && (
        <>
          <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <Stat label="Questions" value={a.totals.questions} />
            <Stat label="People asking" value={a.totals.students} />
            <Stat label="Not answered" value={a.totals.unanswered} />
            <Stat
              label="Avg. response"
              value={a.totals.avg_latency_ms ? `${(a.totals.avg_latency_ms / 1000).toFixed(1)} s` : "–"}
            />
          </dl>

          {a.totals.questions > 0 && (
            <figure>
              <div
                role="img"
                aria-label={`Questions per day over the last ${days} days`}
                className="flex h-20 items-end gap-px border-b border-rule"
              >
                {timeline.map((d) => (
                  <div key={d.day} className="flex h-full flex-1 items-end" title={`${d.day}: ${d.questions}`}>
                    <div
                      className={d.questions ? "w-full rounded-t-[2px] bg-ink" : "w-full"}
                      style={{ height: d.questions ? `${Math.max(6, (d.questions / maxDay) * 100)}%` : 0 }}
                    />
                  </div>
                ))}
              </div>
              <figcaption className="mt-1.5 flex justify-between text-xs text-pencil">
                <span>{shortDate(timeline[0].day)}</span>
                <span>Questions per day</span>
                <span>Today</span>
              </figcaption>
            </figure>
          )}

          <div className="grid gap-10 md:grid-cols-2">
            <Panel title="Not answered from materials">
              {a.unanswered.length === 0 ? (
                <p className="text-sm text-graphite">None. Every question found matching material.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {a.unanswered.map((q) => (
                    <li key={q.question} className="flex gap-3">
                      <span className="min-w-0 flex-1">{q.question}</span>
                      <span className="tabular-nums text-graphite">{q.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Most asked">
              {a.top_questions.length === 0 ? (
                <p className="text-sm text-graphite">No questions yet.</p>
              ) : (
                <Bars rows={a.top_questions.map((q) => ({ label: q.question, value: q.count }))} />
              )}
            </Panel>
            <Panel title="Most cited materials">
              <Bars rows={a.top_documents.map((d) => ({ label: d.document_name, value: d.citations }))} />
            </Panel>
            <Panel title="Most cited sections">
              <Bars
                rows={a.top_sections.map((s) => ({
                  label: [s.section ?? s.document_name, s.page_num ? `p. ${s.page_num}` : ""].filter(Boolean).join(", "),
                  value: s.citations,
                }))}
              />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
