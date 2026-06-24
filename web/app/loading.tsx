import { Skeleton } from "@/components/ui/skeleton";

/** Route-level loading placeholder rendered while server data resolves. */
export default function Loading() {
  return (
    <main className="mx-auto max-w-5xl space-y-8 px-8 py-10">
      <div className="space-y-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-9 w-64" />
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </main>
  );
}
