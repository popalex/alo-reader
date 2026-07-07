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
