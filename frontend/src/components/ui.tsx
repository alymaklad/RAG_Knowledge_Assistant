import clsx from "clsx";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-ink text-paper hover:bg-ink/90 disabled:bg-ink/40",
  secondary:
    "bg-sheet text-ink border border-rule-strong hover:border-ink disabled:text-pencil disabled:border-rule",
  ghost: "text-graphite hover:text-ink hover:bg-rule/50 disabled:text-pencil",
  danger: "bg-sheet text-correction border border-correction/50 hover:bg-correction-soft",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }
>(function Button({ variant = "primary", size = "md", className, ...props }, ref) {
  return (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] font-medium",
        "transition-colors disabled:cursor-not-allowed",
        size === "md" ? "h-10 px-4 text-sm" : "h-8 px-3 text-xs",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
});

const fieldBase =
  "w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-sm text-ink " +
  "placeholder:text-pencil focus:border-ink focus:outline-none focus-visible:outline-2 " +
  "focus-visible:outline-focus disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={clsx(fieldBase, "h-10", className)} {...props} />;
  },
);

export const TextArea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function TextArea({ className, ...props }, ref) {
  return <textarea ref={ref} className={clsx(fieldBase, "py-2.5", className)} {...props} />;
});

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-graphite">{hint}</p>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p
      role="alert"
      className="rounded-[var(--radius-control)] border-l-[3px] border-correction bg-correction-soft px-3 py-2 text-sm text-ink"
    >
      {children}
    </p>
  );
}

export function PageHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <h1 className="font-read text-xl font-semibold tracking-tight text-ink">{title}</h1>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="text-sm text-graphite" aria-live="polite">
      {label}…
    </p>
  );
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong.";
}
