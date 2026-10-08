"use client";

import { LogOut } from "lucide-react";
import { useSignOut } from "@/components/app/account-menu";
import { ThemeChoice } from "@/components/app/theme-choice";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { FieldRow, PanelSection, SettingsPanel } from "./settings-panel";

/** Settings › Account: who is signed in, the theme, and (last, apart from the rest) signing out. */
export function AccountSettings() {
  const { user } = useAuth();
  const signOut = useSignOut();
  return (
    <SettingsPanel title="حساب کاربری" description="ورود شما، ظاهر برنامه و خروج از حساب.">
      <PanelSection>
        <dl>
          <FieldRow label="ایمیل">
            <span dir="ltr" className="inline-block">
              {user?.email ?? "—"}
            </span>
          </FieldRow>
        </dl>
      </PanelSection>
      <PanelSection title="ظاهر">
        <ThemeChoice className="max-w-md" label="پوستهٔ برنامه" />
      </PanelSection>
      <PanelSection title="خروج" description="در این دستگاه از حساب خود خارج می‌شوید.">
        <div>
          <Button variant="secondary" onClick={() => void signOut()}>
            <LogOut className="rtl:-scale-x-100" strokeWidth={1.75} />
            خروج از حساب
          </Button>
        </div>
      </PanelSection>
    </SettingsPanel>
  );
}
