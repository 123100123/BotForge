import { expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { loginMock, openSection, requireMock, test } from "./helpers";

const widths = [375, 768, 1024, 1440] as const;
const themes = ["light", "dark"] as const;
const sections = [
  "نمای کلی",
  "دستیار هوشمند",
  "قابلیت‌ها",
  "داده‌ها",
  "گزارش‌ها",
  "شبیه‌ساز",
  "نسخه‌ها",
  "تنظیمات",
] as const;

async function expectNoPageOverflow(page: Page, where: string) {
  const width = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(width.document, `${where}: document width ${width.document}, viewport ${width.viewport}`).toBeLessThanOrEqual(width.viewport + 1);
}

for (const width of widths) {
  for (const theme of themes) {
    test(`${theme} theme at ${width}px keeps landing, directory, and all workspace sections reachable`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await requireMock(page);
      await page.goto("/");
      await page.getByRole("button", { name: theme === "dark" ? "حالت تیره" : "حالت روشن" }).click();
      await expect(page.locator("html")).toHaveClass(new RegExp(theme));
      await expectNoPageOverflow(page, "landing");
      if (width === 375 || width === 1440) {
        await mkdir("ui-review", { recursive: true });
        await page.screenshot({ path: `ui-review/landing-${theme}-${width}.png`, fullPage: true });
        if (width === 1440 && theme === "dark") await page.screenshot({ path: "ui-review/landing-dark-1440-preview.png" });
      }

      await loginMock(page, "/bots/bot_sepehr");
      await page.goto("/bots");
      await expect(page.getByRole("heading", { name: "کسب‌وکارتان، تحت کنترل" })).toBeVisible();
      await expect(page.getByRole("link", { name: /کارگاه‌های سپهر/ })).toBeVisible();
      await expectNoPageOverflow(page, "bot directory");
      await page.goto("/bots/bot_sepehr");
      await expect(page.getByRole("heading", { name: "کارگاه‌های سپهر" })).toBeVisible();
      await openSection(page, "نمای کلی", width);
      if (width === 375 || width === 1440) await page.screenshot({ path: `ui-review/dashboard-${theme}-${width}.png` });

      for (const section of sections) {
        await openSection(page, section, width);
        await expectNoPageOverflow(page, section);
      }
    });
  }
}
