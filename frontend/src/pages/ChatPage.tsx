import clsx from "clsx";
import { MessageSquarePlus, PanelLeft, Pencil, Search, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router";
import type { CourseContext } from "@/components/CourseLayout";
import { Markdown } from "@/components/Markdown";
import { Sidenotes, SourceDrawer } from "@/components/Sidenotes";
import { Button, Loading } from "@/components/ui";
import { useChatStream, type ViewMessage } from "@/hooks/useChatStream";
import type { ChatSession, Source } from "@/lib/api/client";
import { useDeleteSession, useDocuments, useRenameSession, useSessions } from "@/lib/queries";

function relativeDay(iso: string): string {
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function SessionList({ courseId, activeId }: { courseId: string; activeId?: string }) {
  const [q, setQ] = useState("");
  const sessions = useSessions(courseId, q.trim() || undefined);
  const rename = useRenameSession(courseId);
  const remove = useDeleteSession(courseId);
  const navigate = useNavigate();

  const onRename = (s: ChatSession) => {
    const title = window.prompt("Rename conversation", s.title ?? "");
    if (title?.trim()) rename.mutate({ id: s.id, title: title.trim() });
  };
  const onDelete = (s: ChatSession) => {
    if (!window.confirm("Delete this conversation?")) return;
    remove.mutate(s.id, {
      onSuccess: () => s.id === activeId && navigate(`/courses/${courseId}/chat`),
    });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 p-4">
        <Link
          to={`/courses/${courseId}/chat`}
          className="flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm font-medium hover:border-ink"
        >
          <MessageSquarePlus className="size-4" aria-hidden /> New chat
        </Link>
        <label className="relative block">
          <span className="sr-only">Search conversations</span>
          <Search className="absolute top-2.5 left-2.5 size-4 text-pencil" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search"
            className="h-9 w-full rounded-[var(--radius-control)] border border-rule bg-paper pr-3 pl-8 text-sm placeholder:text-pencil focus:border-ink focus:outline-none"
          />
        </label>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
        {sessions.data?.map((s) => (
          <li key={s.id} className="group relative">
            <Link
              to={`/courses/${courseId}/chat/${s.id}`}
              className={clsx(
                "block rounded-[var(--radius-control)] px-3 py-2 pr-16",
                s.id === activeId ? "bg-sheet shadow-[inset_3px_0_0_var(--highlight)]" : "hover:bg-rule/50",
              )}
            >
              <span className="block truncate text-sm text-ink">{s.title || "Untitled"}</span>
              <span className="text-xs text-pencil">{relativeDay(s.updated_at)}</span>
            </Link>
            <div className="absolute top-2 right-2 hidden gap-0.5 group-focus-within:flex group-hover:flex">
              <button
                onClick={() => onRename(s)}
                className="rounded p-1 text-graphite hover:bg-rule hover:text-ink"
                aria-label="Rename conversation"
              >
                <Pencil className="size-3.5" />
              </button>
              <button
                onClick={() => onDelete(s)}
                className="rounded p-1 text-graphite hover:bg-correction-soft hover:text-correction"
                aria-label="Delete conversation"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          </li>
        ))}
        {sessions.data?.length === 0 && (
          <li className="px-3 py-2 text-sm text-pencil">
            {q ? "No matches" : "No chats yet"}
          </li>
        )}
      </ul>
    </div>
  );
}

function Exchange({
  question,
  answer,
  courseId,
}: {
  question?: ViewMessage;
  answer?: ViewMessage;
  courseId: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [open, setOpen] = useState<Source | null>(null);
  const sources = answer?.sources ?? [];
  const onCite = (n: number | null, openIt?: boolean) => {
    setActive(n);
    if (openIt && n != null) {
      const s = sources.find((x) => x.index === n);
      if (s) setOpen(s);
    }
  };

  return (
    <article className="grid gap-x-12 gap-y-5 xl:grid-cols-[minmax(0,44rem)_17rem]">
      <div className="min-w-0">
        {question && (
          <h2 className="font-read text-lg leading-snug font-semibold whitespace-pre-wrap text-ink">
            {question.content}
          </h2>
        )}
        {answer && (
          <div className="mt-3">
            {answer.status === "streaming" && !answer.content ? (
              <p className="text-sm text-graphite" aria-live="polite">
                {sources.length ? "Writing…" : "Searching…"}
              </p>
            ) : (
              <Markdown
                content={answer.content}
                activeCite={active}
                onCite={onCite}
                className={clsx(answer.status === "streaming" && "caret")}
              />
            )}
            {answer.status === "error" && (
              <p role="alert" className="mt-3 text-sm text-correction">
                {answer.error ?? "The answer failed."}
              </p>
            )}
          </div>
        )}
      </div>
      {answer && sources.length > 0 && (
        <div className="border-t border-rule pt-4 xl:border-t-0 xl:pt-1">
          <Sidenotes
            sources={sources}
            answer={answer.content}
            active={active}
            onActive={setActive}
            onOpen={setOpen}
          />
        </div>
      )}
      {open && answer && (
        <SourceDrawer
          courseId={courseId}
          source={open}
          answer={answer.content}
          onClose={() => setOpen(null)}
        />
      )}
    </article>
  );
}

function pairUp(messages: ViewMessage[]): { question?: ViewMessage; answer?: ViewMessage }[] {
  const out: { question?: ViewMessage; answer?: ViewMessage }[] = [];
  for (const m of messages) {
    if (m.role === "user") out.push({ question: m });
    else if (out.length && !out[out.length - 1].answer) out[out.length - 1].answer = m;
    else out.push({ answer: m });
  }
  return out;
}

export function ChatPage() {
  const { course } = useOutletContext<CourseContext>();
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const docs = useDocuments(course.id);
  const ready = docs.data?.filter((d) => d.status === "indexed") ?? [];
  const [scope, setScope] = useState("");
  const [draft, setDraft] = useState("");
  const [showSessions, setShowSessions] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const chat = useChatStream(course.id, sessionId, (s) => {
    if (s.id !== sessionId) navigate(`/courses/${course.id}/chat/${s.id}`, { replace: true });
  });

  // Follow the answer as it streams, unless the reader has scrolled up.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (el.scrollHeight > el.clientHeight + 1) {
      if (el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTop = el.scrollHeight;
    } else if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 240) {
      window.scrollTo({ top: document.body.scrollHeight });
    }
  }, [chat.messages]);

  useEffect(() => setShowSessions(false), [sessionId]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || chat.streaming) return;
    setDraft("");
    void chat.send(text, scope ? [scope] : undefined);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };
  const ask = (q: string) => {
    setDraft(q);
    textarea.current?.focus();
  };

  const exchanges = pairUp(chat.messages);
  const suggestions = ready.slice(0, 3).map((d) => {
    const name = d.filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    return `What are the key ideas in ${name}?`;
  });

  return (
    <div className="flex flex-1 lg:min-h-0">
      <aside className="hidden w-60 shrink-0 border-r border-rule xl:block">
        <SessionList courseId={course.id} activeId={sessionId} />
      </aside>
      {showSessions && (
        <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-ink/30" onClick={() => setShowSessions(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-paper shadow-xl">
            <SessionList courseId={course.id} activeId={sessionId} />
          </aside>
        </div>
      )}

      <section className="flex min-w-0 flex-1 flex-col lg:min-h-0">
        <div ref={scroller} className="flex-1 px-5 pt-6 pb-10 sm:px-8 lg:min-h-0 lg:overflow-y-auto lg:px-12">
          <button
            onClick={() => setShowSessions(true)}
            className="mb-4 inline-flex items-center gap-2 text-sm text-graphite hover:text-ink xl:hidden"
          >
            <PanelLeft className="size-4" aria-hidden /> Chats
          </button>

          {chat.loading && <Loading label="Loading conversation" />}

          {!chat.loading && exchanges.length === 0 && (
            <div className="max-w-2xl pt-6">
              <h2 className="font-read text-xl font-semibold tracking-tight">
                Ask a question
              </h2>
              {ready.length === 0 ? (
                <p className="mt-3 text-graphite">
                  <Link
                    to="../documents"
                    relative="path"
                    className="font-medium text-ink underline decoration-highlight decoration-2 underline-offset-4"
                  >
                    Add materials
                  </Link>{" "}
                  to get started.
                </p>
              ) : (
                <>
                  <ul className="mt-5 space-y-2">
                    {suggestions.map((s) => (
                      <li key={s}>
                        <button
                          onClick={() => ask(s)}
                          className="text-left font-read text-ink underline decoration-rule-strong decoration-1 underline-offset-4 hover:decoration-highlight hover:decoration-2"
                        >
                          {s}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          <div className="space-y-14">
            {exchanges.map((x, i) => (
              <Exchange
                key={x.answer?.id ?? x.question?.id ?? i}
                question={x.question}
                answer={x.answer}
                courseId={course.id}
              />
            ))}
          </div>
        </div>

        <form
          onSubmit={submit}
          className="sticky bottom-0 shrink-0 border-t border-rule bg-paper px-5 py-3 sm:px-8 lg:static lg:py-4 lg:px-12"
        >
          <div className="max-w-[44rem] rounded-lg border border-rule-strong bg-sheet focus-within:border-ink">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              ref={textarea}
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              placeholder={
                ready.length ? "Ask about your materials" : "Add materials first"
              }
              disabled={ready.length === 0}
              className="block w-full resize-none bg-transparent px-4 pt-3 font-read text-base text-ink placeholder:font-ui placeholder:text-pencil focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-3">
              <label className="flex items-center gap-2 text-xs text-graphite">
                <span className="hidden sm:inline">Search in</span>
                <select
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  className="max-w-[14rem] truncate rounded border border-rule bg-paper px-2 py-1 text-xs text-ink"
                >
                  <option value="">All materials</option>
                  {ready.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
                </select>
              </label>
              {chat.streaming ? (
                <Button type="button" size="sm" variant="secondary" onClick={chat.stop}>
                  <Square className="size-3" aria-hidden /> Stop
                </Button>
              ) : (
                <Button type="submit" size="sm" disabled={!draft.trim() || ready.length === 0}>
                  Ask
                </Button>
              )}
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}
