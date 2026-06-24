/**
 * @fileoverview Skeleton loading placeholder for workspace pages.
 */

import { Skeleton } from "@/components/ui/skeleton";

type PageLoadingProps = {
  title: string;
  eyebrow: string;
};

/** Renders a skeleton workspace layout while page data is loading. */
export function PageLoading({ title, eyebrow }: PageLoadingProps) {
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-8 py-10">
      <div className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-wider text-accent">
          {eyebrow}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
      </div>
      <div className="flex gap-2">
        <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
          正在连接后端
        </span>
        <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
          实时数据
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-56" />
    </main>
  );
}
