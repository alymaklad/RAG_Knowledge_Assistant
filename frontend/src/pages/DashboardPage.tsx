import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button, ErrorNote, Field, Input, Loading, PageHeading, TextArea, errorMessage } from "@/components/ui";
import { useCourses, useCreateCourse } from "@/lib/queries";

function NewCourseForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useCreateCourse();
  const navigate = useNavigate();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const course = await create.mutateAsync({ name, description: description || undefined });
    onDone();
    navigate(`/courses/${course.id}/documents`);
  };

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-rule bg-sheet p-6">
      <h2 className="font-read text-lg font-semibold">New course</h2>
      <Field label="Course name" htmlFor="course-name">
        <Input
          id="course-name"
          required
          autoFocus
          placeholder="e.g. CS 228"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Description (optional)" htmlFor="course-desc">
        <TextArea
          id="course-desc"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      {create.isError && <ErrorNote>{errorMessage(create.error)}</ErrorNote>}
      <div className="flex gap-2">
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create course"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function DashboardPage() {
  const courses = useCourses();
  const [params, setParams] = useSearchParams();
  const creating = params.get("new") === "1";
  const setCreating = (on: boolean) => setParams(on ? { new: "1" } : {}, { replace: true });

  return (
    <div className="mx-auto max-w-4xl px-5 py-8 sm:px-8 lg:py-12">
      <PageHeading title="Courses">
        {!creating && <Button onClick={() => setCreating(true)}>New course</Button>}
      </PageHeading>

      {creating && (
        <div className="mt-6">
          <NewCourseForm onDone={() => setCreating(false)} />
        </div>
      )}

      <div className="mt-8">
        {courses.isPending && <Loading />}
        {courses.isError && <ErrorNote>{errorMessage(courses.error)}</ErrorNote>}
        {courses.data?.length === 0 && !creating && (
          <div className="rounded-lg border border-dashed border-rule-strong px-6 py-12">
            <h2 className="font-read text-lg font-semibold">No courses yet</h2>
            <Button className="mt-5" onClick={() => setCreating(true)}>
              Create a course
            </Button>
          </div>
        )}
        {courses.data && courses.data.length > 0 && (
          <ul className="divide-y divide-rule border-y border-rule">
            {courses.data.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-x-6 gap-y-3 py-5">
                <div className="min-w-0 flex-1 basis-72">
                  <Link
                    to={`/courses/${c.id}`}
                    className="font-read text-lg font-semibold text-ink hover:underline hover:decoration-highlight hover:decoration-2 hover:underline-offset-4"
                  >
                    {c.name}
                  </Link>
                  {c.description && (
                    <p className="mt-0.5 line-clamp-1 text-sm text-graphite">{c.description}</p>
                  )}
                </div>
                <dl className="flex gap-6 text-sm">
                  <div>
                    <dt className="text-xs text-graphite">Materials</dt>
                    <dd className="font-medium tabular-nums">
                      {c.indexed_count}
                      {c.indexed_count !== c.document_count && (
                        <span className="text-graphite"> of {c.document_count}</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-graphite">Your chats</dt>
                    <dd className="font-medium tabular-nums">{c.session_count}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-graphite">Role</dt>
                    <dd className="font-medium capitalize">{c.role}</dd>
                  </div>
                </dl>
                <div className="flex gap-2">
                  <Link
                    to={`/courses/${c.id}/chat`}
                    className="inline-flex h-8 items-center rounded-[var(--radius-control)] bg-ink px-3 text-xs font-medium text-paper hover:bg-ink/90"
                  >
                    Ask
                  </Link>
                  <Link
                    to={`/courses/${c.id}/documents`}
                    className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-xs font-medium hover:border-ink"
                  >
                    Materials
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
