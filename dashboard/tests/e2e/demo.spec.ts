import { test, expect } from "@playwright/test";

test("the unconfigured app is Wes’s original local prototype with all seven views", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator("#homehq-status")).toHaveText(
    "Original prototype · local only",
  );
  await expect(page.locator("#rail .rail-item")).toHaveText([
    "Today",
    "Calendar",
    "Chores",
    "Shopping",
    "Photos",
    "Home",
    "Agents",
  ]);
  await expect(page.locator("#view-home .h-lanes")).toContainText("Wes");
  await page.locator('#rail [data-go="calendar"]').click();
  await page.getByRole("button", { name: "Add event", exact: true }).click();
  await page.getByPlaceholder("What’s happening?").fill("Local prototype plan");
  await page
    .getByRole("button", { name: "Add to calendar", exact: true })
    .click();
  await expect(page.locator("#view-calendar")).toContainText(
    "Local prototype plan",
  );
  await page.reload();
  await expect(page.locator("#view-calendar")).not.toContainText(
    "Local prototype plan",
  );
});

test("unconfigured settings explain environment setup without a second dashboard or key form", async ({
  page,
}) => {
  await page.goto("/settings.html");
  await expect(
    page.getByRole("heading", { name: "Household settings" }),
  ).toBeVisible();
  await expect(page.getByText(/Set VITE_SUPABASE_URL/)).toBeVisible();
  await expect(page.locator("input")).toHaveCount(0);
  await expect(page.locator(".rail")).toHaveCount(0);
  await page.getByRole("link", { name: "← Dashboard" }).click();
  await expect(page.locator("#stage")).toBeVisible();
});
