import { expect } from "@playwright/test";
import { loginMock, openSection, requireMock, test } from "./helpers";

test("mock login honors a safe next path and rejects an external redirect", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await expect(page.getByRole("heading", { name: "کارگاه‌های سپهر" })).toBeVisible();

  // A second isolated context is used so the existing session cannot hide redirect behavior.
  const fresh = await page.context().browser()!.newContext();
  try {
    const other = await fresh.newPage();
    await requireMock(other);
    await other.goto("/login?next=%2F%2Fevil.example");
    await other.getByLabel("ایمیل").fill("redirect-check@example.com");
    await other.getByLabel("گذرواژه", { exact: true }).fill("demo-password-123");
    await other.getByRole("button", { name: "ورود به پنل" }).click();
    await expect.poll(() => new URL(other.url()).pathname).toBe("/bots");
  } finally {
    await fresh.close();
  }
});

test("signup validates email and password before submitting", async ({ page }) => {
  await requireMock(page);
  await page.goto("/signup");
  await page.getByLabel("ایمیل").fill("bad-address");
  await page.getByLabel("گذرواژه", { exact: true }).fill("short");
  await page.getByRole("button", { name: "ساخت حساب کاربری" }).click();
  await expect(page.getByText("ایمیل واردشده معتبر نیست.")).toBeVisible();
  await expect(page.getByText("گذرواژه باید دست‌کم ۱۰ نویسه باشد.")).toBeVisible();
});

test("theme selection survives reload", async ({ page }) => {
  await loginMock(page);
  await page.getByRole("button", { name: "حالت تیره" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.getByRole("button", { name: "حالت تیره" })).toHaveAttribute("aria-pressed", "true");
});

test("new bot modal validates its name and restores focus on Escape", async ({ page }) => {
  await loginMock(page);
  const trigger = page.getByRole("button", { name: "ربات جدید" });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "ساخت ربات" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("نام ربات را وارد کنید.");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.click();
  await page.getByLabel("نام ربات").fill("ربات تست رابط کاربری");
  await dialog.getByRole("button", { name: "ساخت ربات" }).click();
  await expect(page).toHaveURL(/\/bots\/bot_/);
  await expect(page.getByRole("heading", { name: "ربات تست رابط کاربری" })).toBeVisible();
});

test("HeroUI revision Select changes the simulator revision", async ({ page }) => {
  await loginMock(page, "/bots/bot_tamir");
  await openSection(page, "شبیه‌ساز", 1440);
  const select = page.getByRole("region", { name: "شبیه‌ساز" }).getByRole("button", { name: /نسخهٔ ۲/ });
  await select.click();
  await page.getByRole("option", { name: /نسخهٔ ۱/ }).click();
  await expect(page.getByRole("region", { name: "شبیه‌ساز" }).getByRole("button", { name: /نسخهٔ ۱/ })).toBeVisible();
  await page.getByRole("button", { name: "شروع", exact: true }).click();
  await expect(page.getByRole("region", { name: "شبیه‌ساز" }).locator('[aria-live="polite"] [dir="auto"]')).toHaveCount(2);
});

test("builder stream survives mode and section changes through approval", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "دستیار هوشمند", 1440);
  await page.getByRole("textbox", { name: "پیام شما" }).fill("ظرفیت هر کارگاه را ۱۲ نفر کن.");
  await page.getByRole("button", { name: "ارسال" }).click();
  await expect(page.getByRole("region", { name: "گفتگو و ساخت ربات" })).toContainText("ظرفیت هر کارگاه را ۱۲ نفر کن.");

  await page.getByRole("radiogroup", { name: "حالت دستیار" }).getByText("پرسش از داده‌ها", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "از کسب‌وکارتان بپرسید" })).toBeVisible();
  await page.getByRole("radiogroup", { name: "حالت دستیار" }).getByText("ساخت و تغییر", { exact: true }).click();
  await openSection(page, "نمای کلی", 1440);
  await openSection(page, "دستیار هوشمند", 1440);
  await expect(page.getByRole("region", { name: "گفتگو و ساخت ربات" })).toContainText("ظرفیت هر کارگاه را ۱۲ نفر کن.");

  const approve = page.getByRole("button", { name: "تأیید و فعال‌سازی" });
  await expect(approve).toBeVisible({ timeout: 90_000 });
  await approve.click();
  await expect(page.getByText(/نسخهٔ ۴ فعال شد/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("نسخهٔ فعال ۴")).toBeVisible();
});

test("revision rollback requires confirmation and tests show scenario detail", async ({ page }) => {
  await loginMock(page, "/bots/bot_sepehr");
  await openSection(page, "نسخه‌ها", 1440);
  await page.getByRole("list", { name: "نسخه‌ها" }).getByRole("button", { name: /نسخهٔ ۲/ }).click();
  await page.getByRole("region", { name: "نسخه‌ها" }).getByRole("button", { name: "بازگشت به این نسخه" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "انصراف" }).click();
  await expect(page.getByText("نسخهٔ فعال ۳")).toBeVisible();
  await page.getByRole("region", { name: "نسخه‌ها" }).getByRole("button", { name: "بازگشت به این نسخه" }).click();
  await dialog.getByRole("button", { name: "بازگشت به این نسخه" }).click();
  await expect(page.getByText("نسخهٔ فعال ۲")).toBeVisible();

  await page.getByRole("radiogroup", { name: "بخش نسخه‌ها" }).getByText("آزمون‌ها", { exact: true }).click();
  await expect(page.getByText(/سناریو موفق/)).toBeVisible();
  await expect(page.getByRole("region", { name: "مرحله‌ها" })).toBeVisible();
});
