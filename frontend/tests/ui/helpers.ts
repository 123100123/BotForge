import { expect, test as base, type Page } from "@playwright/test";

/** Fail on uncaught UI errors and React hydration warnings as well as failed assertions. */
export const test = base.extend({
  page: async ({ page }, run) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error" && /hydration|server rendered HTML|did not match/i.test(message.text())) {
        errors.push(message.text());
      }
    });
    await run(page);
    expect(errors, "uncaught page or hydration errors").toEqual([]);
  },
});

/** The UI tests must never create bots or revisions against a configured live service. */
export async function requireMock(page: Page) {
  await page.goto("/login");
  await expect(page.getByText("حالت نمایشی:", { exact: true })).toBeVisible();
}

export async function loginMock(page: Page, next = "/bots") {
  await requireMock(page);
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("ایمیل").fill("ui-check@example.com");
  await page.getByLabel("گذرواژه", { exact: true }).fill("demo-password-123");
  await page.getByRole("button", { name: "ورود به پنل" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(next);
}

export async function openSection(page: Page, label: string, width: number) {
  if (width < 1024) await page.getByRole("button", { name: "باز کردن فهرست بخش‌ها" }).click();
  await page.getByRole("navigation", { name: "بخش‌های ربات" }).last().getByRole("button", { name: label, exact: true }).click();
  const region = page.getByRole("region", { name: label });
  await expect(region).toBeVisible();
  await expect(region.getByRole("status", { name: "در حال بارگذاری" })).toHaveCount(0);
}
