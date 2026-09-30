// The two right-hand panes: the entry list and the reading pane, sharing a
// per-stream selection store. On mobile the panes become a single view that
// swaps to the reader (with a Back button) once an entry is selected.

import { useMemo, useState } from "react";

import { useFolders, useSubscriptions } from "../../api/queries";
import { lazyDialog } from "../../components/lazyDialog";
import { streamToPath, type StreamDescriptor } from "../../lib/streams";
import { EntryList } from "./EntryList";
import { ReaderPane } from "./ReaderPane";
import { SelectionProvider } from "./SelectionProvider";
import { useSelection } from "./selection";
import { Welcome } from "../welcome/Welcome";
import styles from "./StreamView.module.css";

const AddSubscriptionDialog = lazyDialog(() =>
  import("../subscribe/AddSubscriptionDialog").then((m) => m.AddSubscriptionDialog),
);

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
  const subs = useSubscriptions();
  const folders = useFolders();
  const [addOpen, setAddOpen] = useState(false);
  // An account with no feeds gets the welcome screen instead of two empty panes.
  // Only a loaded, empty list counts: while loading, or offline with nothing cached,
  // the panes show their own loading and error states.
  const noFeeds = subs.data?.length === 0;
  return (
    <>
      {noFeeds ? (
        <Welcome onAddFeed={() => setAddOpen(true)} />
      ) : (
        // Key by stream so selection resets when the stream changes.
        <SelectionProvider key={streamToPath(stream)}>
          <Panes stream={stream} title={title} />
        </SelectionProvider>
      )}
      {/* Here rather than inside Welcome: adding the first feed swaps Welcome for the
          panes, and the dialog has to stay open through that. */}
      <AddSubscriptionDialog open={addOpen} onOpenChange={setAddOpen} folders={folders.data ?? []} />
    </>
  );
}
