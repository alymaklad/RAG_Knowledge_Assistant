import clsx from "clsx";
import { NavLink, Outlet, useParams } from "react-router";
import type { Course } from "@/lib/api/client";
import { useCourse } from "@/lib/queries";
import { ErrorNote, Loading } from "./ui";

export interface CourseContext {
  course: Course;
  isInstructor: boolean;
}

export function CourseLayout() {
  const { courseId = "" } = useParams();
  const course = useCourse(courseId);

  if (course.isPending) {
    return (
      <div className="p-8">
        <Loading />
      </div>
    );
  }
  if (course.isError || !course.data) {
    return (
      <div className="max-w-xl p-8">
        <ErrorNote>
          Course not found.
        </ErrorNote>
      </div>
    );
  }

  const c = course.data;
  const isInstructor = c.role === "instructor" || c.role === "admin";
  const tabs = [
    { to: "chat", label: "Ask" },
    { to: "study", label: "Study" },
    { to: "documents", label: "Materials" },
    ...(isInstructor
      ? [
          { to: "insights", label: "Insights" },
          { to: "settings", label: "Settings" },
        ]
      : []),
  ];

  return (
    <div className="flex min-h-[calc(100dvh-3.5rem)] flex-col lg:h-dvh lg:min-h-0">
      <header className="shrink-0 border-b border-rule px-5 pt-5 sm:px-8 lg:pt-7">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="font-read text-lg font-semibold tracking-tight sm:text-xl">{c.name}</h1>
          <p className="text-sm text-graphite">
            {c.indexed_count}/{c.document_count} ready
          </p>
        </div>
        <nav aria-label="Course sections" className="-mb-px mt-4 flex gap-6">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                clsx(
                  "border-b-2 pb-2.5 text-sm",
                  isActive
                    ? "border-ink font-medium text-ink"
                    : "border-transparent text-graphite hover:text-ink",
                )
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>
      {/* On large screens each section scrolls inside this pane, so the header stays put. */}
      <div className="flex flex-1 flex-col lg:min-h-0 lg:overflow-y-auto">
        <Outlet context={{ course: c, isInstructor } satisfies CourseContext} />
      </div>
    </div>
  );
}
