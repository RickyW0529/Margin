import { Skeleton } from "@/components/ui/skeleton";

/** Route-level loading placeholder rendered while server data resolves. */
export default function Loading() {
  return (
    <main className="page-shell space-y-8">
      <div className="space-y-3">
        <Skeleton className="h-3 w-20 rounded-full" />
        <Skeleton className="h-9 w-56 rounded-xl" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-2xl" />
    </main>
  );
}
