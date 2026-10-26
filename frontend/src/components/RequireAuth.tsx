import { Navigate, Outlet, useLocation } from "react-router";
import { useMe } from "@/lib/queries";
import { Button, ErrorNote, Loading, errorMessage } from "./ui";

/** Client-side guard for app routes. The API is still the real enforcement point. */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Loading />
      </div>
    );
  }
  if (me.isError) {
    return (
      <div className="mx-auto max-w-md space-y-4 px-6 py-16">
        <ErrorNote>Can’t reach the server ({errorMessage(me.error)}).</ErrorNote>
        <Button variant="secondary" onClick={() => me.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (!me.data) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} replace />;
  }
  return <Outlet />;
}
