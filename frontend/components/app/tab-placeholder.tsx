import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";

/** Shared body of the not-yet-built workspace tabs. */
export function TabPlaceholder({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="max-w-md text-sm leading-7 text-muted-foreground">
          {children ?? "این بخش در نسخهٔ بعدی اضافه می‌شود."}
        </p>
      </CardContent>
    </Card>
  );
}
