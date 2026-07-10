/**
 * @fileoverview Safe, semantic Markdown rendering for user-facing research text.
 */

import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

type MarkdownContentProps = {
  className?: string;
  content: string;
};

/** Render trusted application Markdown without enabling raw HTML. */
export function MarkdownContent({ className, content }: MarkdownContentProps) {
  return (
    <div
      className={cn(
        "min-w-0 text-[15px] leading-7 text-foreground md:text-base md:leading-8",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: SafeLink,
          blockquote: ({ children }) => (
            <blockquote className="my-4 border-l-2 border-accent/45 pl-4 text-muted-foreground">
              {children}
            </blockquote>
          ),
          code: ({ className: codeClassName, children, ...props }) => {
            const fenced = Boolean(codeClassName);
            return (
              <code
                className={cn(
                  fenced
                    ? "font-mono text-[13px] leading-6 text-background"
                    : "rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.86em] text-foreground",
                  codeClassName,
                )}
                {...props}
              >
                {children}
              </code>
            );
          },
          h1: ({ children }) => (
            <h1 className="mb-3 mt-7 text-xl font-semibold tracking-tight first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-6 text-lg font-semibold tracking-tight first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-5 text-base font-semibold tracking-tight first:mt-0">
              {children}
            </h3>
          ),
          li: ({ children }) => <li className="pl-1 marker:text-muted-foreground">{children}</li>,
          ol: ({ children }) => (
            <ol className="my-3 grid list-decimal gap-1.5 pl-6">{children}</ol>
          ),
          p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
          pre: ({ children }) => (
            <pre className="my-4 max-w-full overflow-x-auto rounded-xl border border-border bg-foreground p-4 text-background shadow-xs">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="my-4 max-w-full overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
                {children}
              </table>
            </div>
          ),
          td: ({ children }) => (
            <td className="border-t border-border px-3 py-2 align-top">{children}</td>
          ),
          th: ({ children }) => (
            <th className="bg-muted/55 px-3 py-2 text-xs font-semibold text-muted-foreground">
              {children}
            </th>
          ),
          ul: ({ children }) => (
            <ul className="my-3 grid list-disc gap-1.5 pl-6">{children}</ul>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SafeLink({ children, href, ...props }: ComponentPropsWithoutRef<"a">) {
  const external = Boolean(href?.startsWith("http://") || href?.startsWith("https://"));
  return (
    <a
      className="font-medium text-accent underline decoration-accent/30 underline-offset-4 transition-colors hover:decoration-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      href={href}
      rel={external ? "noreferrer" : undefined}
      target={external ? "_blank" : undefined}
      {...props}
    >
      {children}
    </a>
  );
}
