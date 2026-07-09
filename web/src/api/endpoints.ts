// Typed endpoint wrappers. Types come from the generated OpenAPI schema
// (schema.d.ts) so they can never drift from the API; apiFetch stays the
// transport (auth header, error envelope). Every call takes the bearer token
// from the auth seam — null in AUTH_MODE=none, a Clerk JWT otherwise.

import { apiFetch } from "./client";
import type { components } from "./schema";

export type Folder = components["schemas"]["FolderResponse"];
export type Subscription = components["schemas"]["SubscriptionResponse"];
export type Counts = components["schemas"]["CountsResponse"];
export type EntryListItem = components["schemas"]["EntryListItem"];
export type StreamPage = components["schemas"]["StreamPage"];
export type EntryDetail = components["schemas"]["EntryDetail"];

export function getFolders(token: string | null): Promise<Folder[]> {
  return apiFetch<Folder[]>("/folders", { token });
}

export function getSubscriptions(token: string | null): Promise<Subscription[]> {
  return apiFetch<Subscription[]>("/subscriptions", { token });
}

export function getCounts(token: string | null): Promise<Counts> {
  return apiFetch<Counts>("/counts", { token });
}

export interface StreamQuery {
  status?: "unread" | "all";
  cursor?: string | null;
  limit?: number;
  q?: string;
}

export function getStreamEntries(
  token: string | null,
  streamPath: string,
  opts: StreamQuery = {},
): Promise<StreamPage> {
  const params = new URLSearchParams({
    status: opts.status ?? "all",
    limit: String(opts.limit ?? 50),
  });
  if (opts.cursor) params.set("cursor", opts.cursor);
  if (opts.q) params.set("q", opts.q);
  return apiFetch<StreamPage>(`/streams/${streamPath}/entries?${params}`, { token });
}

export function getEntry(token: string | null, id: number): Promise<EntryDetail> {
  return apiFetch<EntryDetail>(`/entries/${id}`, { token });
}

export type UpdatedResponse = components["schemas"]["UpdatedResponse"];

export interface EntryStateInput {
  ids: number[];
  read?: boolean;
  starred?: boolean;
  changed_at?: string;
}

export function postEntryState(
  token: string | null,
  input: EntryStateInput,
): Promise<UpdatedResponse> {
  return apiFetch<UpdatedResponse>("/entries/state", { token, method: "POST", body: input });
}

export function postMarkRead(
  token: string | null,
  streamPath: string,
  maxEntryId: number,
): Promise<UpdatedResponse> {
  return apiFetch<UpdatedResponse>(`/streams/${streamPath}/mark-read`, {
    token,
    method: "POST",
    body: { max_entry_id: maxEntryId },
  });
}
