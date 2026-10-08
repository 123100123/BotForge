import { CircleCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fa } from "@/lib/format";

interface DeployedStateProps {
  number: number;
  onOpenSection: (section: "data" | "settings") => void;
}

/** Shown once a version is active: what to do next. */
export function DeployedState({ number, onOpenSection }: DeployedStateProps) {
  return (
    <div className="flex flex-col gap-3 rounded-md bg-success-soft p-4">
      <div className="flex items-center gap-2 text-h3 text-success-text">
        <CircleCheck strokeWidth={1.75} aria-hidden className="size-5" />
        نسخهٔ {fa(number)} فعال شد
      </div>
      <p className="text-body text-fg-secondary">
        برای اینکه ربات داده‌های واقعی شما را نشان دهد، آن‌ها را در بخش «عملیات» اضافه کنید. برای وصل کردن ربات به تلگرام،
        به «تنظیمات» بروید.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => onOpenSection("data")}>
          رفتن به عملیات
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onOpenSection("settings")}>
          رفتن به تنظیمات
        </Button>
      </div>
    </div>
  );
}
