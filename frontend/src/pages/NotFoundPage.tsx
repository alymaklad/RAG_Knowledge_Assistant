import { Link } from "react-router";
import { Wordmark } from "@/components/AppShell";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-xl px-6 py-16">
      <Wordmark />
      <h1 className="mt-12 font-read text-xl font-semibold">There’s no page at this address</h1>
      <p className="mt-2 text-graphite">The link may be out of date, or the course was deleted.</p>
      <Link
        to="/"
        className="mt-6 inline-block font-medium text-ink underline decoration-highlight decoration-2 underline-offset-4"
      >
        Go to your courses
      </Link>
    </div>
  );
}
