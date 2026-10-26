import { Navigate, Outlet, useLocation } from "react-router";
import { useMe } from "@/lib/queries";
import { Loading } from "./ui";

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
  if (!me.data) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} replace />;
  }
  return <Outlet />;
}
