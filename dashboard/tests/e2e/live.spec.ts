import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";

const url = process.env.HOMEHQ_TEST_URL;
const key = process.env.HOMEHQ_TEST_KEY;
const webURL = process.env.HOMEHQ_LIVE_WEB_URL;
test.use({ baseURL: webURL || "http://127.0.0.1:5186" });
test.skip(
  !url || !key || !webURL,
  "Requires a disposable local Supabase project and a Vite server configured for it.",
);
async function connect(page: Page): Promise<void> {
  await page.goto("/settings.html");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("dialog").locator("input")).toHaveCount(2);
}

test("independent browser sessions share native dashboard actions, metadata and private photos", async ({
  browser,
  page,
}) => {
  const email = `homehq-ui-${randomUUID()}@example.com`,
    password = `Local-Test-${randomUUID()}`;
  await connect(page);
  await page
    .getByRole("dialog")
    .getByLabel("Email", { exact: true })
    .fill(email);
  await page
    .getByRole("dialog")
    .getByLabel("Password", { exact: true })
    .fill(password);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.locator("#settings-status")).toHaveText("Live sync", {
    timeout: 25000,
  });
  const secondContext = await browser.newContext({ baseURL: webURL });
  const second = await secondContext.newPage();
  await connect(second);
  await second
    .getByRole("dialog")
    .getByLabel("Email", { exact: true })
    .fill(email);
  await second
    .getByRole("dialog")
    .getByLabel("Password", { exact: true })
    .fill(password);
  await second
    .getByRole("dialog")
    .getByRole("button", { name: "Sign in", exact: true })
    .click();
  await expect(second.locator("#settings-status")).toHaveText("Live sync");
  for (const tab of [page, second]) {
    await tab.goto("/#tasks");
    await expect(tab.locator("#homehq-status")).toContainText("Live sync");
    await tab.locator('#view-tasks [data-r="after"]').click();
  }
  await page.locator('#view-tasks [data-ch="c11"]').click();
  await expect(second.locator('#view-tasks [data-ch="c11"]')).toHaveClass(
    /is-done/,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(second.locator('#view-tasks [data-ch="c11"]')).not.toHaveClass(
    /is-done/,
  );
  await page.goto("/settings.html");
  await page.getByRole("button", { name: "Edit Wes", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Name", { exact: true })
    .fill("Wes on the badge");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Save person", exact: true })
    .click();
  await second.locator('#rail [data-go="home"]').click();
  await expect(second.locator("#view-home .h-lanes")).toContainText(
    "Wes on the badge",
  );
  const source = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#315342";
    context.fillRect(0, 0, 640, 480);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  await page.getByRole("button", { name: "Add photo", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Photo", { exact: true })
    .setInputFiles({
      name: "family.png",
      mimeType: "image/png",
      buffer: Buffer.from(source, "base64"),
    });
  await page
    .getByRole("dialog")
    .getByLabel("Place")
    .fill("A private little memory");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Add photo", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await second.goto("/settings.html");
  const image = second.getByRole("img", {
    name: "A private little memory",
    exact: true,
  });
  await expect(image).toHaveAttribute(
    "src",
    /storage\/v1\/object\/sign\/homehq-photos\//,
  );
  await expect
    .poll(() =>
      image.evaluate((img: HTMLImageElement) => [
        img.naturalWidth,
        img.naturalHeight,
      ]),
    )
    .toEqual([640, 480]);
  const owner = createClient(url!, key!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const ownerSignIn = await owner.auth.signInWithPassword({ email, password });
  expect(ownerSignIn.error).toBeNull();
  const ownerId = ownerSignIn.data.user!.id;
  const other = createClient(url!, key!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const otherSignup = await other.auth.signUp({
    email: `homehq-other-${randomUUID()}@example.com`,
    password: `Local-Test-${randomUUID()}`,
  });
  expect(otherSignup.error).toBeNull();
  const read = await other
    .from("homehq_people")
    .select("id")
    .eq("owner_id", ownerId);
  expect(read.error).toBeNull();
  expect(read.data).toEqual([]);
  const write = await other
    .from("homehq_people")
    .update({ name: "Unexpected cross-owner edit" })
    .eq("owner_id", ownerId)
    .eq("id", "alex")
    .select("id");
  expect(write.data).toEqual([]);
  const check = await owner
    .from("homehq_people")
    .select("name")
    .eq("id", "alex")
    .single();
  expect(check.data?.name).toBe("Wes on the badge");
  const photos = await owner
    .from("homehq_photos")
    .select("path")
    .not("path", "is", null)
    .limit(1)
    .single();
  const privateObject = await other.storage
    .from("homehq-photos")
    .download(photos.data!.path);
  expect(privateObject.error).not.toBeNull();
  const privateChannel = other.channel(`homehq:${ownerId}`, {
    config: { private: true },
  });
  const joinStatus = await new Promise<string>((resolve) => {
    const timeout = setTimeout(() => resolve("TIMED_OUT"), 12_000);
    privateChannel.subscribe((status) => {
      if (
        status === "SUBSCRIBED" ||
        status === "CHANNEL_ERROR" ||
        status === "TIMED_OUT"
      ) {
        clearTimeout(timeout);
        resolve(status);
      }
    });
  });
  expect(joinStatus).not.toBe("SUBSCRIBED");
  await other.removeChannel(privateChannel);
  await secondContext.close();
});
