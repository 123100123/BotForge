import { CircleCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fa } from "@/lib/format";

interface DeployedStateProps {
  number: number;
  onOpenSection: (section: "data" | "settings") => void;
}

/** Shown once a revision is active: what to do next. */
export function DeployedState({ number, onOpenSection }: DeployedStateProps) {
  return (
    <Card className="border-success/40 bg-success-soft">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-base font-semibold text-success-text">
          <CircleCheck className="size-5" />
          نسخهٔ {fa(number)} فعال شد
        </div>
        <p className="text-sm leading-7">
          برای اینکه ربات کارگاه‌های واقعی را نشان دهد، آن‌ها را در بخش «عملیات» اضافه کنید. برای وصل کردن ربات به تلگرام،
          توکن آن را در «تنظیمات» وارد کنید.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => onOpenSection("data")}>
            رفتن به عملیات
          </Button>
          <Button size="sm" variant="outline" onClick={() => onOpenSection("settings")}>
            رفتن به تنظیمات
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
