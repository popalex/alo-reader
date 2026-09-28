import { clerkSetup } from "@clerk/testing/playwright";

// Exchanges CLERK_SECRET_KEY for a Clerk testing token (CLERK_TESTING_TOKEN), which
// setupClerkTestingToken() then attaches to the browser's Frontend API requests.
// That is what lets an automated browser past the instance's bot protection; without
// it the sign-up form stops at Cloudflare's "verify you are human".
export default async function globalSetup(): Promise<void> {
  await clerkSetup();
}
