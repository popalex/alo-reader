// Typed endpoint wrappers. Types come from the generated OpenAPI schema
// (schema.d.ts) so they can never drift from the API; apiFetch stays the
// transport (auth header, error envelope). Every call takes the bearer token
// from the auth seam — null in AUTH_MODE=none, a Clerk JWT otherwise.

import { apiFetch, apiFetchVoid } from "./client";
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

export type DiscoverCandidate = components["schemas"]["DiscoverCandidate"];
export type ImportReport = components["schemas"]["ImportReport"];

/** Create a folder (category). */
export function createFolder(token: string | null, name: string): Promise<Folder> {
  return apiFetch<Folder>("/folders", { token, method: "POST", body: { name } });
}

/** Rename a folder (category). */
export function updateFolder(token: string | null, id: number, name: string): Promise<Folder> {
  return apiFetch<Folder>(`/folders/${id}`, { token, method: "PATCH", body: { name } });
}

/** Delete a folder (category). 409 if it still has feeds. */
export function deleteFolder(token: string | null, id: number): Promise<void> {
  return apiFetchVoid(`/folders/${id}`, { token, method: "DELETE" });
}

/** Probe a site or feed URL and return the feed candidates found there. */
export function discoverFeeds(token: string | null, url: string): Promise<DiscoverCandidate[]> {
  return apiFetch<DiscoverCandidate[]>("/discover", { token, method: "POST", body: { url } });
}

export interface CreateSubscriptionInput {
  feed_url: string;
  folder_id?: number | null;
  title?: string;
}

export function createSubscription(
  token: string | null,
  input: CreateSubscriptionInput,
): Promise<Subscription> {
  return apiFetch<Subscription>("/subscriptions", { token, method: "POST", body: input });
}

/** Import an OPML file (multipart) and return the per-file import report. */
export function importOpml(token: string | null, file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<ImportReport>("/opml", { token, method: "POST", body: form });
}

export interface UpdateSubscriptionInput {
  title_override?: string | null;
  folder_id?: number | null;
}

/** Patch a subscription (rename via title_override, move category via folder_id).
 *  Only the keys present are changed (PATCH semantics). */
export function updateSubscription(
  token: string | null,
  id: number,
  input: UpdateSubscriptionInput,
): Promise<Subscription> {
  return apiFetch<Subscription>(`/subscriptions/${id}`, { token, method: "PATCH", body: input });
}

/** Unsubscribe (delete a subscription). Returns 204. */
export function deleteSubscription(token: string | null, id: number): Promise<void> {
  return apiFetchVoid(`/subscriptions/${id}`, { token, method: "DELETE" });
}

export function getCounts(token: string | null): Promise<Counts> {
  return apiFetch<Counts>("/counts", { token });
}

export interface StreamQuery {
  cursor?: string | null;
  limit?: number;
  q?: string;
}

export function getStreamEntries(
  token: string | null,
  streamPath: string,
  opts: StreamQuery = {},
): Promise<StreamPage> {
  // status is always "all" — the app has no unread-only view (the API defaults to
  // all, but send it explicitly to keep the contract obvious).
  const params = new URLSearchParams({
    status: "all",
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
  maxEntryId?: number,
): Promise<UpdatedResponse> {
  // No bound → mark the whole stream ("mark all read").
  return apiFetch<UpdatedResponse>(`/streams/${streamPath}/mark-read`, {
    token,
    method: "POST",
    body: maxEntryId != null ? { max_entry_id: maxEntryId } : {},
  });
}
