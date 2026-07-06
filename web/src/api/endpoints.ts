// Typed endpoint wrappers. Types come from the generated OpenAPI schema
// (schema.d.ts) so they can never drift from the API; apiFetch stays the
// transport (auth header, error envelope). Every call takes the bearer token
// from the auth seam — null in AUTH_MODE=none, a Clerk JWT otherwise.

import { apiFetch } from "./client";
import type { components } from "./schema";

export type Folder = components["schemas"]["FolderResponse"];
export type Subscription = components["schemas"]["SubscriptionResponse"];
export type Counts = components["schemas"]["CountsResponse"];

export function getFolders(token: string | null): Promise<Folder[]> {
  return apiFetch<Folder[]>("/folders", { token });
}

export function getSubscriptions(token: string | null): Promise<Subscription[]> {
  return apiFetch<Subscription[]>("/subscriptions", { token });
}

export function getCounts(token: string | null): Promise<Counts> {
  return apiFetch<Counts>("/counts", { token });
}
