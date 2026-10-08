"use client";

import Link from "next/link";
import { NewBotForm } from "@/components/app/new-bot-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";

/** /bots/new: name the business, then the assistant builds it on the Changes page. */
export default function NewBotPage() {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
      <PageHeader
        title="کسب‌وکار جدید"
        description="برای کسب‌وکارتان یک نام انتخاب کنید. بعد، کار آن را برای دستیار توضیح می‌دهید تا ربات تلگرامش را بسازد."
      />
      <Card>
        <CardContent>
          <NewBotForm
            secondaryAction={
              <Button asChild variant="ghost">
                <Link href="/bots?all=1">انصراف</Link>
              </Button>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
