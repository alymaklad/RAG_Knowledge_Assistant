import clsx from "clsx";
import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { linkCitations } from "@/lib/citations";

/** Models often write \( \) and \[ \] for math; remark-math expects $ and $$. */
function normalizeMath(md: string): string {
  return md
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => `$$${m}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => `$${m}$`);
}

interface Props {
  content: string;
  className?: string;
  activeCite?: number | null;
  onCite?: (n: number | null, open?: boolean) => void;
}

export const Markdown = memo(function Markdown({ content, className, activeCite, onCite }: Props) {
  const components: Components = {
    a({ href, children, ...rest }) {
      const m = href?.match(/^#cite-(\d+)$/);
      if (m) {
        const n = Number(m[1]);
        return (
          <sup className="mx-px font-ui">
            <button
              type="button"
              onMouseEnter={() => onCite?.(n)}
              onMouseLeave={() => onCite?.(null)}
              onFocus={() => onCite?.(n)}
              onBlur={() => onCite?.(null)}
              onClick={() => onCite?.(n, true)}
              aria-label={`Source ${n}`}
              className={clsx(
                "rounded-sm px-1 text-[0.7rem] font-medium leading-none text-[#1f2544] transition-colors",
                activeCite === n ? "bg-ink text-paper" : "bg-highlight hover:bg-ink hover:text-paper",
              )}
            >
              {n}
            </button>
          </sup>
        );
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="underline decoration-rule-strong underline-offset-2 hover:decoration-ink"
          {...rest}
        >
          {children}
        </a>
      );
    },
  };

  return (
    <div className={clsx("prose-read", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {linkCitations(normalizeMath(content))}
      </ReactMarkdown>
    </div>
  );
});
