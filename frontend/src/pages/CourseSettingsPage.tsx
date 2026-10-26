import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useOutletContext } from "react-router";
import type { CourseContext } from "@/components/CourseLayout";
import { Button, ErrorNote, Field, Input, Loading, TextArea, errorMessage } from "@/components/ui";
import type { MemberRole } from "@/lib/api/client";
import {
  useAddMember,
  useDeleteCourse,
  useMe,
  useMembers,
  useRemoveMember,
  useUpdateCourse,
} from "@/lib/queries";

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-6 border-b border-rule py-8 md:grid-cols-[15rem_minmax(0,1fr)]">
      <div>
        <h2 className="font-read text-lg font-semibold">{title}</h2>
        {description && <p className="mt-1 text-sm text-graphite">{description}</p>}
      </div>
      <div className="max-w-xl">{children}</div>
    </section>
  );
}

export function CourseSettingsPage() {
  const { course, isInstructor } = useOutletContext<CourseContext>();
  const me = useMe();
  const update = useUpdateCourse(course.id);
  const members = useMembers(course.id);
  const add = useAddMember(course.id);
  const removeMember = useRemoveMember(course.id);
  const deleteCourse = useDeleteCourse(course.id);
  const navigate = useNavigate();

  const [name, setName] = useState(course.name);
  const [description, setDescription] = useState(course.description ?? "");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("student");
  const [saved, setSaved] = useState(false);

  if (!isInstructor) return <Navigate to="../chat" relative="path" replace />;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    await update.mutateAsync({ name, description: description || null });
    setSaved(true);
  };
  const invite = async (e: FormEvent) => {
    e.preventDefault();
    await add.mutateAsync({ email, role });
    setEmail("");
  };
  const destroy = async () => {
    const typed = window.prompt("Type the course name to confirm:");
    if (typed !== course.name) return;
    await deleteCourse.mutateAsync();
    navigate("/", { replace: true });
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-5 sm:px-8">
      <Section title="Details">
        <form onSubmit={save} className="space-y-4">
          <Field label="Course name" htmlFor="s-name">
            <Input id="s-name" required value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} />
          </Field>
          <Field label="Description" htmlFor="s-desc">
            <TextArea id="s-desc" rows={3} value={description} onChange={(e) => { setDescription(e.target.value); setSaved(false); }} />
          </Field>
          {update.isError && <ErrorNote>{errorMessage(update.error)}</ErrorNote>}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={update.isPending}>Save changes</Button>
            {saved && <span className="text-sm text-ok">Saved</span>}
          </div>
        </form>
      </Section>

      <Section title="Members">
        <form onSubmit={invite} className="flex flex-wrap items-end gap-2">
          <div className="min-w-56 flex-1">
            <Field label="Add by email" htmlFor="m-email">
              <Input id="m-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
          </div>
          <label className="sr-only" htmlFor="m-role">Role</label>
          <select
            id="m-role"
            value={role}
            onChange={(e) => setRole(e.target.value as MemberRole)}
            className="h-10 rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-2 text-sm"
          >
            <option value="student">Student</option>
            <option value="instructor">Instructor</option>
          </select>
          <Button type="submit" disabled={add.isPending}>Add</Button>
        </form>
        {add.isError && <ErrorNote>{errorMessage(add.error)}</ErrorNote>}
        {members.isPending && <Loading />}
        <ul className="mt-2 divide-y divide-rule border-y border-rule">
          {members.data?.map((m) => (
            <li key={m.user_id} className="flex items-center gap-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{m.full_name || m.email}</p>
                {m.full_name && <p className="truncate text-xs text-graphite">{m.email}</p>}
              </div>
              <span className="text-xs capitalize text-graphite">{m.role}</span>
              {m.user_id !== me.data?.id && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => window.confirm(`Remove ${m.email} from the course?`) && removeMember.mutate(m.user_id)}
                >
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Delete course" description="Removes all materials and chats. Can’t be undone.">
        {deleteCourse.isError && <ErrorNote>{errorMessage(deleteCourse.error)}</ErrorNote>}
        <Button variant="danger" onClick={destroy} disabled={deleteCourse.isPending}>
          Delete this course
        </Button>
      </Section>
    </div>
  );
}
