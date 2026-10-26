import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { LogOut, Menu, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api } from "@/lib/api/client";
import { useCourses, useMe } from "@/lib/queries";

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link to="/" className={clsx("flex items-center gap-2.5 text-ink", className)}>
      <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="6" fill="currentColor" />
        <rect x="7" y="17" width="18" height="6" fill="var(--highlight)" />
        <path
          d="M9 9h14M9 14h14M9 20h9"
          stroke="var(--paper)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <span className="font-read text-lg font-semibold tracking-tight">Margin</span>
    </Link>
  );
}

function CourseNav({ onNavigate }: { onNavigate?: () => void }) {
  const courses = useCourses();
  return (
    <nav aria-label="Courses" className="flex-1 overflow-y-auto">
      <div className="flex items-center justify-between px-3 pb-2">
        <h2 className="text-xs font-medium text-graphite">Courses</h2>
        <Link
          to="/?new=1"
          onClick={onNavigate}
          className="rounded p-1 text-graphite hover:bg-rule/60 hover:text-ink"
          aria-label="Create a course"
        >
          <Plus className="size-4" />
        </Link>
      </div>
      <ul className="space-y-0.5">
        {courses.data?.map((c) => (
          <li key={c.id}>
            <NavLink
              to={`/courses/${c.id}`}
              onClick={onNavigate}
              className={({ isActive }) =>
                clsx(
                  "block truncate rounded-[var(--radius-control)] px-3 py-2 text-sm",
                  isActive
                    ? "bg-sheet font-medium text-ink shadow-[inset_3px_0_0_var(--highlight)]"
                    : "text-graphite hover:bg-rule/50 hover:text-ink",
                )
              }
            >
              {c.name}
            </NavLink>
          </li>
        ))}
        {courses.data?.length === 0 && (
          <li className="px-3 py-2 text-sm text-pencil">No courses yet</li>
        )}
      </ul>
    </nav>
  );
}

function Account() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const signOut = async () => {
    await api.post("/api/auth/logout").catch(() => undefined);
    qc.clear();
    navigate("/login");
  };
  return (
    <div className="flex items-center gap-2 border-t border-rule px-3 pt-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{me.data?.full_name || "Signed in"}</p>
        <p className="truncate text-xs text-graphite">{me.data?.email}</p>
      </div>
      <button
        onClick={signOut}
        className="rounded p-2 text-graphite hover:bg-rule/60 hover:text-ink"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r border-rule py-5 lg:flex">
        <Wordmark className="px-5" />
        <CourseNav />
        <Account />
      </aside>

      {/* Mobile header + drawer */}
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center justify-between border-b border-rule bg-paper/95 px-4 backdrop-blur lg:hidden">
        <Wordmark />
        <button
          onClick={() => setOpen(true)}
          className="rounded p-2 text-ink hover:bg-rule/60"
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-ink/30" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 bg-paper py-5 shadow-xl">
            <div className="flex items-center justify-between px-5">
              <Wordmark />
              <button
                onClick={() => setOpen(false)}
                className="rounded p-2 text-ink hover:bg-rule/60"
                aria-label="Close navigation"
              >
                <X className="size-5" />
              </button>
            </div>
            <CourseNav onNavigate={() => setOpen(false)} />
            <Account />
          </aside>
        </div>
      )}

      <main className="min-w-0 flex-1 pt-14 lg:pt-0">
        <Outlet />
      </main>
    </div>
  );
}
