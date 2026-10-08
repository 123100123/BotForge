import { Skeleton } from "@/components/ui/skeleton";

/** The shell's shape while the business loads: sidebar (or rail), top bar and a page outline. */
export function ShellSkeleton() {
  return (
    <div className="flex min-h-dvh items-start bg-page" role="status" aria-label="در حال بارگذاری کسب‌وکار">
      <div className="sticky top-0 hidden h-dvh w-[248px] shrink-0 flex-col gap-5 border-e bg-surface p-4 lg:flex">
        <div className="flex flex-col gap-2 border-b pb-4">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-4 w-24" />
        </div>
        {[0, 1, 2].map((g) => (
          <div key={g} className="flex flex-col gap-2">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-4/5" />
          </div>
        ))}
      </div>
      <div className="sticky top-0 hidden h-dvh w-16 shrink-0 flex-col items-center gap-3 border-e bg-surface py-4 sm:flex lg:hidden">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="size-9" />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 items-center gap-3 border-b px-4 sm:px-6">
          <Skeleton className="h-9 w-full max-w-md" />
        </div>
        <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-4 p-4 sm:p-6">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-80 max-w-full" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-64" />
        </div>
      </div>
    </div>
  );
}
