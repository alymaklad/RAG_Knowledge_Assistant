import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { Wordmark } from "@/components/AppShell";

/** Shown when a page throws while rendering, instead of a blank screen. */
export function ErrorPage() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : null;
  return (
    <div className="mx-auto max-w-xl px-6 py-16">
      <Wordmark />
      <h1 className="mt-12 font-read text-xl font-semibold">This page hit an error</h1>
      {detail && <p className="mt-2 text-sm text-graphite">{detail}</p>}
      <div className="mt-6 flex gap-4 text-sm">
        <button
          onClick={() => window.location.reload()}
          className="font-medium text-ink underline decoration-highlight decoration-2 underline-offset-4"
        >
          Reload
        </button>
        <Link to="/" className="text-graphite underline underline-offset-4 hover:text-ink">
          Go to your courses
        </Link>
      </div>
    </div>
  );
}
