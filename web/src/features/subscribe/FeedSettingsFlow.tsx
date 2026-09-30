// The feed settings dialog and its delete confirmation, as one flow the app shell
// owns (AppLayout, opened through FeedSettingsContext). Moved out of the sidebar so
// the list's "failing feed" banner can open it too, on a phone as well.

import { useState } from "react";

import { useNavigate, useRouterState } from "@tanstack/react-router";

import type { Subscription } from "../../api/endpoints";
import { useDeleteSubscription } from "../../api/feedMutations";
import { useFolders } from "../../api/queries";
import { lazyDialog } from "../../components/lazyDialog";

const ConfirmDialog = lazyDialog(() =>
  import("../../components/ConfirmDialog").then((m) => m.ConfirmDialog),
);
const FeedSettingsDialog = lazyDialog(() =>
  import("./FeedSettingsDialog").then((m) => m.FeedSettingsDialog),
);

export function FeedSettingsFlow({
  sub,
  onClose,
}: {
  sub: Subscription | null;
  onClose: () => void;
}) {
  const folders = useFolders();
  const deleteSub = useDeleteSubscription();
  const [pendingDelete, setPendingDelete] = useState<Subscription | null>(null);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <>
      <FeedSettingsDialog
        sub={sub}
        open={sub !== null}
        onOpenChange={(open) => !open && onClose()}
        folders={folders.data ?? []}
        onDelete={setPendingDelete}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Delete this feed?"
        body={`"${pendingDelete?.title || "Untitled feed"}" will be removed along with its articles and your read/star history. Re-subscribing later starts fresh.`}
        confirmLabel="Delete"
        onConfirm={() => {
          if (!pendingDelete) return;
          const { id, title, feed_id } = pendingDelete;
          deleteSub.mutate(
            { id, title },
            {
              // If we're viewing the feed we just left, go back to All items so the
              // list + reader don't keep showing the removed feed's content.
              onSuccess: () => {
                if (pathname === `/feed/${feed_id}`) void navigate({ to: "/" });
              },
            },
          );
        }}
      />
    </>
  );
}
