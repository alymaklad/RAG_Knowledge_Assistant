import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Download, Shuffle, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useOutletContext, useSearchParams } from "react-router";
import type { CourseContext } from "@/components/CourseLayout";
import { Markdown } from "@/components/Markdown";
import { fileUrl, sourceLocation } from "@/components/Sidenotes";
import { Button, ErrorNote, Input, Loading, errorMessage } from "@/components/ui";
import { api, type Source } from "@/lib/api/client";
import { useDocuments } from "@/lib/queries";

type Kind = "quiz" | "flashcards" | "summary";

interface QuizQuestion {
  question: string;
  options: Record<"A" | "B" | "C" | "D", string>;
  correct_answer: "A" | "B" | "C" | "D";
  explanation: string;
  difficulty: "Easy" | "Medium" | "Hard";
  source: number | null;
}
interface Flashcard {
  front: string;
  back: string;
  type: string;
  source: number | null;
}
interface StudySet {
  id: string;
  kind: "quiz" | "flashcards";
  title: string;
  items: QuizQuestion[] | Flashcard[];
  sources: Source[];
  created_at: string;
}
interface Summary {
  document_id: string;
  content: string;
  sources: Source[];
  created_at: string;
}

const setsKey = (courseId: string) => ["courses", courseId, "study-sets"];

function SourceLink({ courseId, sources, n }: { courseId: string; sources: Source[]; n: number | null }) {
  const s = n ? sources.find((x) => x.index === n) : undefined;
  if (!s) return null;
  return (
    <a
      href={fileUrl(courseId, s)}
      target="_blank"
      rel="noreferrer"
      className="text-xs text-graphite underline decoration-highlight decoration-2 underline-offset-4 hover:text-ink"
    >
      {s.document_name}
      {sourceLocation(s) && `, ${sourceLocation(s)}`}
    </a>
  );
}

function QuizView({ set, courseId }: { set: StudySet; courseId: string }) {
  const questions = set.items as QuizQuestion[];
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  useEffect(() => {
    setI(0);
    setAnswers({});
  }, [set.id]);

  const done = i >= questions.length;
  const score = questions.filter((q, k) => answers[k] === q.correct_answer).length;

  if (done) {
    return (
      <div className="max-w-2xl">
        <p className="font-read text-2xl font-semibold">
          {score} of {questions.length} correct
        </p>
        <ol className="mt-6 space-y-4">
          {questions.map((q, k) => (
            <li key={k} className="border-l-2 pl-4 text-sm" style={{ borderColor: answers[k] === q.correct_answer ? "var(--ok)" : "var(--correction)" }}>
              <p className="font-medium">{q.question}</p>
              <p className="mt-1 text-graphite">
                {q.correct_answer}. {q.options[q.correct_answer]}
              </p>
            </li>
          ))}
        </ol>
        <div className="mt-8 flex gap-2">
          <Button
            onClick={() => {
              setI(0);
              setAnswers({});
            }}
          >
            Retake
          </Button>
          <a
            href={`/api/study-sets/${set.id}/pdf`}
            className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-4 text-sm font-medium hover:border-ink"
          >
            <Download className="size-4" aria-hidden /> PDF
          </a>
        </div>
      </div>
    );
  }

  const q = questions[i];
  const chosen = answers[i];
  return (
    <div className="max-w-2xl">
      <p className="text-sm text-graphite">
        {i + 1} of {questions.length}
        <span className="ml-3 text-pencil">{q.difficulty}</span>
      </p>
      <h3 className="mt-3 font-read text-lg leading-snug font-semibold">{q.question}</h3>
      <ul className="mt-5 space-y-2">
        {(["A", "B", "C", "D"] as const).map((letter) => {
          const isCorrect = letter === q.correct_answer;
          const isChosen = letter === chosen;
          return (
            <li key={letter}>
              <button
                disabled={Boolean(chosen)}
                onClick={() => setAnswers((a) => ({ ...a, [i]: letter }))}
                className={clsx(
                  "flex w-full items-start gap-3 rounded-[var(--radius-control)] border px-4 py-3 text-left text-sm transition-colors",
                  !chosen && "border-rule-strong bg-sheet hover:border-ink",
                  chosen && isCorrect && "border-ok bg-ok/10",
                  chosen && isChosen && !isCorrect && "border-correction bg-correction-soft",
                  chosen && !isChosen && !isCorrect && "border-rule bg-sheet text-pencil",
                )}
              >
                <span className="font-medium">{letter}</span>
                <span>{q.options[letter]}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {chosen && (
        <div className="mt-5 space-y-2" aria-live="polite">
          <p className="text-sm">
            <span className={clsx("font-medium", chosen === q.correct_answer ? "text-ok" : "text-correction")}>
              {chosen === q.correct_answer ? "Correct." : `The answer is ${q.correct_answer}.`}
            </span>{" "}
            {q.explanation}
          </p>
          <SourceLink courseId={courseId} sources={set.sources} n={q.source} />
          <div>
            <Button className="mt-3" onClick={() => setI(i + 1)}>
              {i + 1 === questions.length ? "See score" : "Next"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FlashcardView({ set, courseId }: { set: StudySet; courseId: string }) {
  const [order, setOrder] = useState<number[]>([]);
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const cards = set.items as Flashcard[];
  useEffect(() => {
    setOrder(cards.map((_, k) => k));
    setI(0);
    setFlipped(false);
  }, [set.id, cards]);

  const go = (d: number) => {
    setFlipped(false);
    setI((x) => Math.min(Math.max(0, x + d), cards.length - 1));
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === " ") {
        e.preventDefault();
        setFlipped((f) => !f);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!order.length) return null;
  const card = cards[order[i]];
  return (
    <div className="max-w-xl">
      <button
        className="flip block w-full text-left"
        data-flipped={flipped}
        onClick={() => setFlipped((f) => !f)}
        aria-label={flipped ? "Show question" : "Show answer"}
      >
        <div className="flip-inner relative min-h-64">
          <div className="flip-face absolute inset-0 flex flex-col justify-center rounded-lg border border-rule-strong bg-sheet p-8">
            <p className="font-read text-xl leading-snug font-semibold">{card.front}</p>
          </div>
          <div className="flip-face flip-back absolute inset-0 flex flex-col justify-center rounded-lg border border-ink bg-sheet p-8">
            <p className="font-read text-base leading-relaxed">{card.back}</p>
            <div className="mt-4" onClick={(e) => e.stopPropagation()}>
              <SourceLink courseId={courseId} sources={set.sources} n={card.source} />
            </div>
          </div>
        </div>
      </button>
      <div className="mt-4 flex items-center justify-between text-sm text-graphite">
        <div className="flex items-center gap-1">
          <button onClick={() => go(-1)} disabled={i === 0} className="rounded p-2 hover:bg-rule/60 disabled:opacity-40" aria-label="Previous card">
            <ChevronLeft className="size-4" />
          </button>
          <span className="tabular-nums">
            {i + 1} / {cards.length}
          </span>
          <button onClick={() => go(1)} disabled={i === cards.length - 1} className="rounded p-2 hover:bg-rule/60 disabled:opacity-40" aria-label="Next card">
            <ChevronRight className="size-4" />
          </button>
        </div>
        <button
          onClick={() => {
            setOrder((o) => [...o].sort(() => Math.random() - 0.5));
            setI(0);
            setFlipped(false);
          }}
          className="inline-flex items-center gap-1.5 rounded px-2 py-1 hover:bg-rule/60 hover:text-ink"
        >
          <Shuffle className="size-3.5" aria-hidden /> Shuffle
        </button>
      </div>
      <p className="mt-2 text-xs text-pencil">Space flips, arrow keys move.</p>
    </div>
  );
}

function SummaryView({ courseId, documentId }: { courseId: string; documentId: string }) {
  const qc = useQueryClient();
  const key = ["summary", documentId];
  const summary = useQuery({
    queryKey: key,
    queryFn: () => api.get<Summary | null>(`/api/courses/${courseId}/documents/${documentId}/summary`),
  });
  const generate = useMutation({
    mutationFn: () => api.post<Summary>(`/api/courses/${courseId}/documents/${documentId}/summary`),
    onSuccess: (s) => qc.setQueryData(key, s),
  });
  if (summary.isPending) return <Loading />;
  if (!summary.data)
    return (
      <div>
        <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
          {generate.isPending ? "Summarizing…" : "Summarize"}
        </Button>
        {generate.isError && <div className="mt-4"><ErrorNote>{errorMessage(generate.error)}</ErrorNote></div>}
      </div>
    );
  return (
    <div className="max-w-2xl">
      <Markdown content={summary.data.content.replace(/\[Sources?[^\]]*\]/g, "")} />
      <button
        onClick={() => generate.mutate()}
        disabled={generate.isPending}
        className="mt-6 text-xs text-graphite underline underline-offset-4 hover:text-ink"
      >
        {generate.isPending ? "Summarizing…" : "Regenerate"}
      </button>
    </div>
  );
}

export function StudyPage() {
  const { course } = useOutletContext<CourseContext>();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const docs = useDocuments(course.id);
  const ready = docs.data?.filter((d) => d.status === "indexed") ?? [];
  const [kind, setKind] = useState<Kind>("quiz");
  const [source, setSource] = useState("");
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(8);
  const selectedId = params.get("set");
  const summaryDoc = params.get("summary");

  const sets = useQuery({
    queryKey: setsKey(course.id),
    queryFn: () => api.get<StudySet[]>(`/api/courses/${course.id}/study-sets`),
  });
  const selected = useMemo(() => sets.data?.find((s) => s.id === selectedId), [sets.data, selectedId]);

  const create = useMutation({
    mutationFn: () =>
      api.post<StudySet>(`/api/courses/${course.id}/study-sets`, {
        kind,
        count,
        document_id: source && source !== "topic" ? source : null,
        topic: source === "topic" ? topic : null,
      }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: setsKey(course.id) });
      setParams({ set: s.id });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/study-sets/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: setsKey(course.id) });
      setParams({});
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (kind === "summary") setParams({ summary: source });
    else create.mutate();
  };
  const canSubmit =
    kind === "summary" ? Boolean(source && source !== "topic") : source === "topic" ? topic.trim().length > 2 : Boolean(source);

  return (
    <div className="grid flex-1 gap-8 px-5 py-6 sm:px-8 lg:grid-cols-[17rem_minmax(0,1fr)] lg:py-8">
      <aside className="space-y-8">
        <form onSubmit={submit} className="space-y-4">
          <div role="radiogroup" aria-label="Type" className="flex rounded-[var(--radius-control)] border border-rule-strong bg-sheet p-0.5 text-sm">
            {(["quiz", "flashcards", "summary"] as const).map((k) => (
              <button
                type="button"
                role="radio"
                aria-checked={kind === k}
                key={k}
                onClick={() => setKind(k)}
                className={clsx("flex-1 rounded px-2 py-1.5 capitalize", kind === k ? "bg-ink text-paper" : "text-graphite hover:text-ink")}
              >
                {k}
              </button>
            ))}
          </div>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">From</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="h-10 w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm"
            >
              <option value="">Choose…</option>
              {ready.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
              {kind !== "summary" && <option value="topic">A topic…</option>}
            </select>
          </label>
          {source === "topic" && kind !== "summary" && (
            <Input aria-label="Topic" placeholder="e.g. congestion control" value={topic} onChange={(e) => setTopic(e.target.value)} />
          )}
          {kind !== "summary" && (
            <label className="flex items-center justify-between text-sm">
              <span className="font-medium">{kind === "quiz" ? "Questions" : "Cards"}</span>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                className="h-9 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2"
              >
                {[5, 8, 10, 15].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
          )}
          <Button type="submit" className="w-full" disabled={!canSubmit || create.isPending}>
            {create.isPending ? "Generating…" : kind === "summary" ? "Open summary" : "Generate"}
          </Button>
          {create.isError && <ErrorNote>{errorMessage(create.error)}</ErrorNote>}
        </form>

        <div>
          <h2 className="text-xs font-medium text-graphite">Saved</h2>
          {sets.isPending && <Loading />}
          <ul className="mt-2 space-y-0.5">
            {sets.data?.map((s) => (
              <li key={s.id} className="group flex items-center">
                <button
                  onClick={() => setParams({ set: s.id })}
                  className={clsx(
                    "min-w-0 flex-1 rounded-[var(--radius-control)] px-3 py-2 text-left",
                    s.id === selectedId ? "bg-sheet shadow-[inset_3px_0_0_var(--highlight)]" : "hover:bg-rule/50",
                  )}
                >
                  <span className="block truncate text-sm">{s.title}</span>
                  <span className="text-xs text-pencil capitalize">
                    {s.kind}, {s.items.length}
                  </span>
                </button>
                <button
                  onClick={() => window.confirm("Delete this set?") && remove.mutate(s.id)}
                  className="invisible rounded p-1.5 text-graphite group-hover:visible group-focus-within:visible hover:text-correction"
                  aria-label={`Delete ${s.title}`}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
            {sets.data?.length === 0 && <li className="px-3 py-2 text-sm text-pencil">Nothing yet</li>}
          </ul>
        </div>
      </aside>

      <section className="min-w-0">
        {create.isPending && <Loading label="Writing questions from your materials" />}
        {!create.isPending && summaryDoc && <SummaryView courseId={course.id} documentId={summaryDoc} />}
        {!create.isPending && !summaryDoc && selected?.kind === "quiz" && <QuizView set={selected} courseId={course.id} />}
        {!create.isPending && !summaryDoc && selected?.kind === "flashcards" && (
          <FlashcardView set={selected} courseId={course.id} />
        )}
        {!create.isPending && !summaryDoc && !selected && (
          <p className="text-graphite">{ready.length ? "Pick a type and a source." : "Add materials first."}</p>
        )}
      </section>
    </div>
  );
}
