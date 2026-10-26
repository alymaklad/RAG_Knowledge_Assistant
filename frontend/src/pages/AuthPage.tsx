import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { Wordmark } from "@/components/AppShell";
import { Button, ErrorNote, Field, Input, errorMessage } from "@/components/ui";
import { api, type User } from "@/lib/api/client";
import { keys, useMe } from "@/lib/queries";

/** The product, shown rather than described: an answer with its source in the margin. */
function SampleAnswer() {
  return (
    <figure className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_15rem]" aria-label="Example answer">
      <div>
        <p className="text-sm text-graphite">What is a Markov blanket?</p>
        <p className="prose-read mt-3 text-ink">
          A node’s Markov blanket is its parents, its children, and its children’s other parents.
          Once you know the values of those nodes, the node is conditionally independent of
          everything else in the network
          <sup className="ml-0.5 font-ui text-xs font-medium">
            <span className="rounded-sm bg-highlight px-1 text-[#1f2544]">1</span>
          </sup>
          , which is why inference only needs to look at that neighbourhood.
        </p>
      </div>
      <aside className="border-l-2 border-highlight pl-4 text-sm">
        <p className="font-medium text-ink">
          <span className="mr-1.5 rounded-sm bg-highlight px-1 text-xs text-[#1f2544]">1</span>
          Week 6, Bayesian Networks
        </p>
        <p className="mt-0.5 text-xs text-graphite">Page 15, Probabilistic graphical models</p>
        <p className="mt-2 font-read leading-relaxed text-graphite">
          …the blanket shields the node from the rest of the graph.{" "}
          <mark className="marker">
            Given its Markov blanket, a node is conditionally independent of all other nodes.
          </mark>
        </p>
      </aside>
    </figure>
  );
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me.data) return <Navigate to={next} replace />;

  const isLogin = mode === "login";
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ user: User }>(
        isLogin ? "/api/auth/login" : "/api/auth/register",
        isLogin ? { email, password } : { email, password, full_name: fullName || null },
      );
      qc.setQueryData(keys.me, res.user);
      navigate(next.startsWith("/") ? next : "/", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.15fr)_minmax(24rem,1fr)]">
      <section className="hidden flex-col gap-16 border-r border-rule px-12 py-10 lg:flex xl:px-16">
        <Wordmark />
        <div className="max-w-3xl">
          <h1 className="font-read text-2xl font-semibold tracking-tight text-ink">
            Ask your course materials.
          </h1>
          <div className="mt-10 rounded-lg border border-rule bg-sheet p-7">
            <SampleAnswer />
          </div>
        </div>
      </section>

      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <Wordmark className="mb-10 lg:hidden" />
          <h2 className="font-read text-xl font-semibold tracking-tight">
            {isLogin ? "Sign in" : "Create account"}
          </h2>
          <p className="mt-1.5 text-sm text-graphite">
            {isLogin ? "No account? " : "Have an account? "}
            <Link
              to={`${isLogin ? "/register" : "/login"}${params.toString() ? `?${params}` : ""}`}
              className="font-medium text-ink underline decoration-highlight decoration-2 underline-offset-4"
            >
              {isLogin ? "Create one" : "Sign in"}
            </Link>
          </p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            {!isLogin && (
              <Field label="Name" htmlFor="name">
                <Input
                  id="name"
                  autoComplete="name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </Field>
            )}
            <Field label="Email" htmlFor="email">
              <Input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            <Field
              label="Password"
              htmlFor="password"
              hint={isLogin ? undefined : "8+ characters"}
            >
              <Input
                id="password"
                type="password"
                required
                minLength={isLogin ? undefined : 8}
                autoComplete={isLogin ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <ErrorNote>{error}</ErrorNote>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "One moment…" : isLogin ? "Sign in" : "Create account"}
            </Button>
          </form>
        </div>
      </section>
    </div>
  );
}
