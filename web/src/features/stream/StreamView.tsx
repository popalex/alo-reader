// The two right-hand panes: the entry list and the reading pane, sharing a
// per-stream selection store. On mobile the panes become a single view that
// swaps to the reader (with a Back button) once an entry is selected.

import { useMemo } from "react";

import { useFolders, useSubscriptions } from "../../api/queries";
import { streamToPath, type StreamDescriptor } from "../../lib/streams";
import { EntryList } from "./EntryList";
import { ReaderPane } from "./ReaderPane";
import { SelectionProvider } from "./SelectionProvider";
import { useSelection } from "./selection";
import styles from "./StreamView.module.css";

export type { StreamDescriptor };

function useStreamTitle(stream: StreamDescriptor): string {
  const subs = useSubscriptions();
  const folders = useFolders();
  return useMemo(() => {
    switch (stream.kind) {
      case "all":
        return "All items";
      case "starred":
        return "Starred";
      case "feed":
        // A feed stream is keyed by feed_id (what the API filters on), not the
        // subscription id — they differ once a feed is shared/re-subscribed.
        return subs.data?.find((s) => s.feed_id === stream.id)?.title || "Feed";
      case "folder":
        return folders.data?.find((f) => f.id === stream.id)?.name || "Folder";
    }
  }, [stream, subs.data, folders.data]);
}

function Panes({ stream, title }: { stream: StreamDescriptor; title: string }) {
  const { openId } = useSelection();
  return (
    <div className={styles.panes} data-reading={openId != null || undefined}>
      <EntryList stream={stream} title={title} />
      <ReaderPane />
    </div>
  );
}

export function StreamView({ stream }: { stream: StreamDescriptor }) {
  const title = useStreamTitle(stream);
  // Key by stream so selection resets when the stream changes.
  return (
    <SelectionProvider key={streamToPath(stream)}>
      <Panes stream={stream} title={title} />
    </SelectionProvider>
  );
}
