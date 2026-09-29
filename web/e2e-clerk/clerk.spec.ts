import { createHmac, randomUUID } from "node:crypto";

import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// AUTH_MODE=clerk, end to end, against a dedicated Clerk development instance.
// scripts/e2e-clerk.sh creates this run's test user (E2E_CLERK_EMAIL), seeds its data,
// and deletes every Clerk user the run created afterwards. The addresses are
// +clerk_test ones, so Clerk accepts 424242 as their code and sends no email.

const email = process.env.E2E_CLERK_EMAIL ?? "";
const signupEmail = process.env.E2E_CLERK_SIGNUP_EMAIL ?? "";
const deleteEmail = process.env.E2E_CLERK_DELETE_EMAIL ?? "";
const TEST_CODE = "424242";

test.beforeAll(() => {
  expect(email, "run through scripts/e2e-clerk.sh").toContain("+clerk_test@");
});

/** A code-verification step: wait for Clerk to have prepared (sent) the code before
 *  typing it. Clerk's code input submits by itself at six digits, and a submission
 *  that beats the prepare request fails. That race once made a manual run flaky. */
async function enterTestCode(page: Page, prepared: Promise<unknown>): Promise<void> {
  await prepared;
  const code = page.locator('input[autocomplete="one-time-code"]').first();
  await code.waitFor();
  await code.click();
  await page.keyboard.type(TEST_CODE);
}

const isPrepare = (url: string) => /\/(prepare_first_factor|prepare_verification)\b/.test(url);

/** Sign in through the real <SignIn> form with the email-code method. */
async function signInThroughForm(page: Page, address: string): Promise<void> {
  await setupClerkTestingToken({ page });
  await page.goto("/app/");
  await page.locator('input[name="identifier"]').fill(address);
  // Depending on the instance's settings, Continue either prepares an email code at
  // once or asks for a password first; the second offers the code under "another method".
  let prepared = page.waitForResponse((r) => isPrepare(r.url()) && r.ok());
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const password = page.locator('input[name="password"]');
  const code = page.locator('input[autocomplete="one-time-code"]').first();
  await expect(password.or(code)).toBeVisible();
  if (await password.isVisible()) {
    await page.getByRole("link", { name: /another method/i }).click();
    prepared = page.waitForResponse((r) => isPrepare(r.url()) && r.ok());
    await page.getByRole("button", { name: /Email code to/ }).click();
  }
  await enterTestCode(page, prepared);
}

/** Programmatic sign-in (Clerk sign-in token), for tests that are not about the form. */
async function signIn(page: Page, address = email): Promise<void> {
  await setupClerkTestingToken({ page });
  await page.goto("/app/");
  await clerk.signIn({ page, emailAddress: address });
  await page.goto("/app/");
  await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeVisible();
}

/** The current session token, as the app's token bridge would get it. */
function sessionToken(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const w = window as unknown as { Clerk: { session: { getToken(): Promise<string> } } };
    return w.Clerk.session.getToken();
  });
}

/** POST a webhook signed the way Clerk (Svix) signs them, with this run's secret. */
async function postWebhook(request: APIRequestContext, payload: object) {
  const secret = process.env.CLERK_WEBHOOK_SECRET ?? "";
  const body = JSON.stringify(payload);
  const id = `msg_${randomUUID()}`;
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const key = Buffer.from(secret.replace(/^whsec_/, ""), "base64");
  const signature = createHmac("sha256", key).update(`${id}.${timestamp}.${body}`).digest("base64");
  return request.post("/api/v1/webhooks/clerk", {
    data: body,
    headers: {
      "content-type": "application/json",
      "svix-id": id,
      "svix-timestamp": timestamp,
      "svix-signature": `v1,${signature}`,
    },
  });
}

async function clerkBackend(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(`https://api.clerk.com/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${process.env.CLERK_SECRET_KEY}`,
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) throw new Error(`Clerk ${path}: ${response.status}`);
  return response.json();
}

test.describe.serial("clerk mode", () => {
  test("signs in through the form and lands in the app, with its data", async ({ page }) => {
    await signInThroughForm(page, email);
    // Clerk's default post-sign-in URL is "/", which is the landing page here.
    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /The Verge/ })).toBeVisible(); // seeded
  });

  test("every API call carries the session token, and the API refuses one without", async ({
    page,
  }) => {
    const calls: { path: string; bearer: boolean }[] = [];
    page.on("request", (r) => {
      const url = new URL(r.url());
      if (url.pathname.startsWith("/api/v1/")) {
        calls.push({ path: url.pathname, bearer: /^Bearer ey/.test(r.headers().authorization ?? "") });
      }
    });
    await signIn(page);
    await page.locator("[data-index]").first().waitFor();

    // /config is the pre-auth boot call and icons are <img> loads: both public.
    const needsToken = calls.filter((c) => !/\/(config|icons\/\d+)$/.test(c.path));
    expect(needsToken.length).toBeGreaterThan(3);
    expect(needsToken.filter((c) => !c.bearer)).toEqual([]);

    expect((await page.request.get("/api/v1/me")).status()).toBe(401);
  });

  test("opens and stars an article, and keeps the session across a reload", async ({ page }) => {
    await signIn(page);
    await page.locator("[data-index]").nth(1).click();
    const star = page.getByRole("button", { name: /^Star/ }).first();
    const wasPressed = (await star.getAttribute("aria-pressed")) === "true";
    await star.click();
    await expect(star).toHaveAttribute("aria-pressed", String(!wasPressed));

    await page.reload();
    await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeVisible();
    await expect(page.locator('input[name="identifier"]')).toHaveCount(0);
  });

  test("refreshes the session token once it expires, without interrupting the app", async ({
    page,
  }) => {
    // Clerk session tokens live about 60 s. Wait past that and use the app: the token
    // bridge must hand the API a fresh one, not the expired one.
    test.setTimeout(120_000);
    await signIn(page);
    const before = await sessionToken(page);
    await page.waitForTimeout(65_000);

    // A star click always sends a write (POST /entries/state); read queries may be
    // served from cache and never go out.
    const statuses: number[] = [];
    page.on("response", (r) => {
      if (r.url().includes("/api/v1/")) statuses.push(r.status());
    });
    const write = page.waitForRequest(
      (r) => r.url().includes("/api/v1/entries/state") && r.method() === "POST",
      { timeout: 20_000 },
    );
    await page.locator("[data-index]").first().click();
    await page.getByRole("button", { name: /^Star/ }).first().click();
    const fresh = (await write).headers().authorization?.replace(/^Bearer /, "");
    expect(fresh).toBeTruthy();
    expect(fresh).not.toBe(before);
    await page.waitForLoadState("networkidle");
    expect(statuses.filter((s) => s === 401)).toEqual([]);
  });

  test("sign-out goes to the landing page, and the app asks to sign in again", async ({
    page,
  }) => {
    await signIn(page);
    // Clerk's own signOut(), as its account menu calls it. What is ours to test is
    // where it goes afterwards (ClerkProvider afterSignOutUrl), not Clerk's menu markup.
    await page.evaluate(async () => {
      const w = window as unknown as { Clerk: { signOut(): Promise<void> } };
      await w.Clerk.signOut();
    });
    await expect(page).toHaveURL(/localhost\/$/);
    await expect(page.getByRole("link", { name: "Sign in" }).first()).toBeVisible();

    await page.goto("/app/");
    await expect(page.locator('input[name="identifier"]')).toBeVisible();
  });

  test("the landing page's call to action follows the session", async ({ page }) => {
    // A returning reader must not be pitched a sign-up, and a signed-out one must not
    // be told they are signed in (deploy/landing/landing.js).
    const cta = () => page.locator("a.cta").first();

    await page.goto("/");
    await expect(cta()).toHaveText("Create an account"); // a stranger

    await signIn(page);
    await page.goto("/");
    await expect(cta()).toHaveText("Open alo reader");
    await expect(page.locator(".reassure")).toHaveText("You are already signed in.");

    await page.goto("/app/");
    await page.waitForFunction(() => (window as unknown as { Clerk?: { loaded?: boolean } }).Clerk?.loaded);
    await page.evaluate(async () => {
      const w = window as unknown as { Clerk: { signOut(): Promise<void> } };
      await w.Clerk.signOut();
    });
    await expect(page).toHaveURL(/localhost\/$/);
    await expect(cta()).toHaveText("Create an account"); // signed out again
    await expect(page.locator(".reassure")).not.toHaveText("You are already signed in.");
  });

  test("the landing page and /legal are served in clerk mode", async ({ page }) => {
    const landing = await page.goto("/");
    expect(landing?.status()).toBe(200);
    await expect(page.getByRole("link", { name: /Create an account/ }).first()).toBeVisible();

    const legal = await page.goto("/legal");
    expect(legal?.status()).toBe(200);
    await expect(page).toHaveTitle(/.+/);
  });

  test("sign-up through Clerk's hosted page comes back into the app", async ({ page }) => {
    // The bot check on sign-up is why this needs the testing token; a person would
    // tick it. The hosted page lives on Clerk's domain, so the token is set for the
    // whole context, not just our origin.
    await setupClerkTestingToken({ context: page.context() });
    await page.goto("/app/");
    await page.getByRole("link", { name: "Sign up" }).click();
    await page.locator('input[name="emailAddress"]').fill(signupEmail);
    const password = page.locator('input[name="password"]');
    if (await password.isVisible()) await password.fill(`E2e-${randomUUID()}`);
    const prepared = page.waitForResponse((r) => isPrepare(r.url()) && r.ok());
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await enterTestCode(page, prepared);

    await expect(page).toHaveURL(/localhost\/app\/?/, { timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeVisible();
  });

  test("webhooks: user.updated fills the email, user.deleted removes the account for good", async ({
    page,
    request,
  }) => {
    // Clerk cannot deliver to CI, so the payloads are signed here with the same secret
    // and scheme (Svix HMAC) and posted to the real endpoint. Delivery itself was
    // proven by hand through a tunnel.
    const created = (await clerkBackend("/users", {
      method: "POST",
      body: JSON.stringify({ email_address: [deleteEmail], skip_password_requirement: true }),
    })) as { id: string };
    await signIn(page, deleteEmail);
    const token = await sessionToken(page);
    const me = () =>
      request.get("/api/v1/me", { headers: { authorization: `Bearer ${token}` } });

    // First request auto-provisioned the row, without an email yet.
    expect((await (await me()).json()).email).toBe("");

    const updated = await postWebhook(request, {
      type: "user.updated",
      data: {
        id: created.id,
        primary_email_address_id: "idn_primary",
        email_addresses: [{ id: "idn_primary", email_address: deleteEmail }],
      },
    });
    expect(updated.status()).toBe(204);
    expect((await (await me()).json()).email).toBe(deleteEmail);

    const deleted = await postWebhook(request, {
      type: "user.deleted",
      data: { id: created.id, deleted: true },
    });
    expect(deleted.status()).toBe(204);
    // The session token is still valid for a while. The row is gone and the tombstone
    // stops that token from quietly recreating it.
    expect((await me()).status()).toBe(401);
    expect((await me()).status()).toBe(401);

    // A retried, out-of-order user.created must not bring it back either.
    const late = await postWebhook(request, {
      type: "user.created",
      data: {
        id: created.id,
        primary_email_address_id: "idn_primary",
        email_addresses: [{ id: "idn_primary", email_address: deleteEmail }],
      },
    });
    expect(late.status()).toBe(204);
    expect((await me()).status()).toBe(401);

    // A badly signed delivery is refused outright.
    const forged = await request.post("/api/v1/webhooks/clerk", {
      data: JSON.stringify({ type: "user.deleted", data: { id: "user_someone" } }),
      headers: {
        "content-type": "application/json",
        "svix-id": "msg_forged",
        "svix-timestamp": Math.floor(Date.now() / 1000).toString(),
        "svix-signature": "v1,AAAA",
      },
    });
    expect(forged.status()).toBe(401);
  });
});
