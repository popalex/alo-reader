// A stream is the one query abstraction (DESIGN.md §5): all | starred |
// feed/{id} | folder/{id}. The descriptor is the app-side representation; the
// path is what the API expects under /streams/{stream}/entries.

export type StreamDescriptor =
  | { kind: "all" }
  | { kind: "starred" }
  | { kind: "feed"; id: number }
  | { kind: "folder"; id: number };

export function streamToPath(stream: StreamDescriptor): string {
  switch (stream.kind) {
    case "all":
      return "all";
    case "starred":
      return "starred";
    case "feed":
      return `feed/${stream.id}`;
    case "folder":
      return `folder/${stream.id}`;
  }
}

/** The fields of a subscription that say whether its feed has been fetched yet. */
interface FetchState {
  feed_id: number;
  folder_id: number | null;
  last_fetched_at: string | null;
  last_error: string | null;
}

/** Whether a stream is still waiting for the first fetch of any of its feeds: the
 *  reason an empty list is empty right after subscribing or importing. A feed counts
 *  as waiting until it has been fetched once or has failed (the same test
 *  usePendingFeedPolling uses). Starred never waits: it holds only what you star. */
export function awaitingFirstFetch(stream: StreamDescriptor, subs: FetchState[]): boolean {
  const waiting = (s: FetchState) => !s.last_fetched_at && !s.last_error;
  switch (stream.kind) {
    case "all":
      return subs.some(waiting);
    case "starred":
      return false;
    case "feed":
      return subs.some((s) => s.feed_id === stream.id && waiting(s));
    case "folder":
      return subs.some((s) => s.folder_id === stream.id && waiting(s));
  }
}
