// Per-feed settings (opened from the sidebar row's gear). Edit the feed's title and
// category, see its URL, or delete it — all via PATCH /subscriptions/{id} (backend
// from WP-06). Same visual language as the add-feed dialog.

import { useEffect, useState } from "react";

import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, Trash2 } from "lucide-react";

import { ApiError } from "../../api/client";
import {
  createFolder,
  type Folder,
  type Subscription,
  type UpdateSubscriptionInput,
} from "../../api/endpoints";
import { useUpdateSubscription } from "../../api/feedMutations";
import { useTokenGetter } from "../../app/auth";
import { FolderSelect, NEW_FOLDER } from "./FolderSelect";
import styles from "./FeedSettingsDialog.module.css";

export function FeedSettingsDialog({
  sub,
  open,
  onOpenChange,
  folders,
  onDelete,
}: {
  sub: Subscription | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: Folder[];
  onDelete: (sub: Subscription) => void;
}) {
  const getToken = useTokenGetter();
  const update = useUpdateSubscription();

  const [title, setTitle] = useState("");
  const [folderId, setFolderId] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Re-seed the form each time a feed's settings open.
  useEffect(() => {
    if (sub) {
      setTitle(sub.title);
      setFolderId(sub.folder_id != null ? String(sub.folder_id) : "");
      setNewFolderName("");
      setError(null);
    }
  }, [sub]);

  if (!sub) return null;
  const current = sub;

  async function save() {
    setError(null);
    try {
      const patch: { id: number } & UpdateSubscriptionInput = { id: current.id };

      // Title: only touch it if changed. Empty clears the override (feed's own title).
      if (title.trim() !== current.title.trim()) {
        patch.title_override = title.trim() || null;
      }

      // Category: resolve the target folder, creating a new one if asked.
      let targetFolder: number | null = current.folder_id ?? null;
      if (folderId === NEW_FOLDER) {
        const name = newFolderName.trim();
        if (!name) {
          setError("Enter a name for the new category.");
          return;
        }
        targetFolder = (await createFolder(await getToken(), name)).id;
      } else {
        targetFolder = folderId ? Number(folderId) : null;
      }
      if (targetFolder !== (current.folder_id ?? null)) patch.folder_id = targetFolder;

      if ("title_override" in patch || "folder_id" in patch) {
        await update.mutateAsync(patch);
      }
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the feed's settings.");
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>Feed settings</Dialog.Title>

          <label className={styles.field}>
            <span className={styles.label}>Title</span>
            <input
              className={styles.input}
              type="text"
              value={title}
              placeholder="The feed's own title"
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
          </label>

          <div className={styles.field}>
            <span className={styles.label}>Feed URL</span>
            <div className={styles.url} title={current.feed_url}>
              {current.feed_url}
            </div>
          </div>

          <div className={styles.field}>
            <FolderSelect
              folders={folders}
              value={folderId}
              onChange={setFolderId}
              newName={newFolderName}
              onNewNameChange={setNewFolderName}
            />
          </div>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.delete}
              onClick={() => {
                onOpenChange(false);
                onDelete(current);
              }}
            >
              <Trash2 size={14} />
              <span>Delete feed</span>
            </button>
            <div className={styles.right}>
              <Dialog.Close asChild>
                <button type="button" className={styles.cancel}>
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="button"
                className={styles.save}
                disabled={update.isPending}
                onClick={() => void save()}
              >
                {update.isPending ? <Loader2 size={14} className={styles.spin} /> : null}
                <span>Save</span>
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
