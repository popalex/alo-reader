// Add-subscription / OPML-import dialog (Radix). Two ways to add feeds:
//   1. Paste a site or feed URL → POST /discover surfaces the feed candidates →
//      pick one → POST /subscriptions (optionally into a folder).
//   2. Upload an OPML file → POST /opml → show the per-feed import report.
// Backend endpoints exist since WP-06/WP-08; this is the missing UI for them.

import { useRef, useState } from "react";

import * as Dialog from "@radix-ui/react-dialog";
import { FileUp, Loader2, Plus, Search } from "lucide-react";

import { useTokenGetter } from "../../app/auth";
import { ApiError } from "../../api/client";
import { useCreateSubscription, useImportOpml } from "../../api/feedMutations";
import {
  createFolder,
  discoverFeeds,
  type DiscoverCandidate,
  type Folder,
  type ImportReport,
} from "../../api/endpoints";
import { FolderSelect, NEW_FOLDER } from "./FolderSelect";
import styles from "./AddSubscriptionDialog.module.css";

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function AddSubscriptionDialog({
  open,
  onOpenChange,
  folders,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: Folder[];
}) {
  const getToken = useTokenGetter();
  const create = useCreateSubscription();
  const importer = useImportOpml();

  const [url, setUrl] = useState("");
  const [folderId, setFolderId] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [candidates, setCandidates] = useState<DiscoverCandidate[] | null>(null);
  const [directUrl, setDirectUrl] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Caches the in-flight (or resolved) folder creation for "+ New category…" by
  // name, so adding a second candidate — even in a rapid double-click before the
  // first resolves — reuses the same folder instead of POSTing a duplicate.
  const createdFolder = useRef<{ name: string; id: Promise<number> } | null>(null);

  function reset() {
    setUrl("");
    setFolderId("");
    setNewFolderName("");
    setCandidates(null);
    setDirectUrl(null);
    setDiscovering(false);
    setReport(null);
    setError(null);
    createdFolder.current = null;
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  async function onFind(e: React.FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return;
    setError(null);
    setCandidates(null);
    setDirectUrl(null);
    setReport(null);
    setDiscovering(true);
    try {
      const found = await discoverFeeds(await getToken(), u);
      // Nothing auto-detected: still let the user add the exact URL they typed —
      // it may be a feed discovery couldn't scan (unreachable during discovery,
      // odd content type, etc.). If it turns out not to be a feed, the worker
      // marks it failed and it shows an error in the sidebar.
      if (found.length === 0) setDirectUrl(u);
      else setCandidates(found);
    } catch (err) {
      setDirectUrl(u);
      setError(messageOf(err, "Couldn't scan that address for feeds."));
    } finally {
      setDiscovering(false);
    }
  }

  async function subscribe(feedUrl: string, title?: string) {
    setError(null);
    try {
      let folder_id: number | null = null;
      if (folderId === NEW_FOLDER) {
        const name = newFolderName.trim();
        if (!name) {
          setError("Enter a name for the new category.");
          return;
        }
        // Reuse the folder if one is already being (or has been) created for this
        // name; otherwise start creating it. The ref is set synchronously (no await
        // before it) so racing clicks serialize onto a single POST /folders.
        if (createdFolder.current?.name !== name) {
          const id = (async () => (await createFolder(await getToken(), name)).id)();
          createdFolder.current = { name, id };
        }
        try {
          folder_id = await createdFolder.current.id;
        } catch (err) {
          createdFolder.current = null; // let a retry re-attempt the create
          throw err;
        }
        setFolderId(String(folder_id));
      } else if (folderId) {
        folder_id = Number(folderId);
      }
      await create.mutateAsync({ feed_url: feedUrl, folder_id, title });
      handleOpenChange(false);
    } catch (err) {
      setError(messageOf(err, "Couldn't subscribe to that feed."));
    }
  }

  async function onOpmlFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file after a failure
    if (!file) return;
    setError(null);
    setReport(null);
    setCandidates(null);
    try {
      setReport(await importer.mutateAsync(file));
    } catch (err) {
      setError(messageOf(err, "Couldn't import that file."));
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>Add a feed</Dialog.Title>

          <form className={styles.section} onSubmit={onFind}>
            <label className={styles.label} htmlFor="add-feed-url">
              Feed or site URL
            </label>
            <div className={styles.row}>
              <input
                id="add-feed-url"
                className={styles.input}
                type="text"
                inputMode="url"
                placeholder="example.com or https://example.com/feed.xml"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                autoFocus
              />
              <button type="submit" className={styles.find} disabled={discovering || !url.trim()}>
                {discovering ? <Loader2 size={14} className={styles.spin} /> : <Search size={14} />}
                <span>Find</span>
              </button>
            </div>

            <FolderSelect
              folders={folders}
              value={folderId}
              onChange={setFolderId}
              newName={newFolderName}
              onNewNameChange={setNewFolderName}
            />

            {candidates && candidates.length > 0 && (
              <ul className={styles.candidates}>
                {candidates.map((c) => (
                  <li key={c.feed_url} className={styles.candidate}>
                    <div className={styles.candidateText}>
                      <span className={styles.candidateTitle}>{c.title || c.feed_url}</span>
                      <span className={styles.candidateUrl}>{c.feed_url}</span>
                    </div>
                    <button
                      type="button"
                      className={styles.add}
                      disabled={create.isPending}
                      onClick={() => void subscribe(c.feed_url, c.title)}
                    >
                      <Plus size={14} />
                      <span>Add</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {directUrl && (
              <div className={styles.fallback}>
                <span className={styles.fallbackNote}>
                  No feeds were auto-detected. Add the URL as a feed directly?
                </span>
                <button
                  type="button"
                  className={styles.add}
                  disabled={create.isPending}
                  onClick={() => void subscribe(directUrl)}
                >
                  <Plus size={14} />
                  <span>Add directly</span>
                </button>
              </div>
            )}
          </form>

          <div className={styles.divider}>
            <span>or</span>
          </div>

          <div className={styles.section}>
            <span className={styles.label}>Import an OPML file</span>
            <label className={styles.opml} data-busy={importer.isPending || undefined}>
              {importer.isPending ? <Loader2 size={14} className={styles.spin} /> : <FileUp size={14} />}
              <span>{importer.isPending ? "Importing…" : "Choose OPML file"}</span>
              <input
                type="file"
                accept=".opml,.xml,application/xml,text/xml"
                className={styles.fileInput}
                onChange={(e) => void onOpmlFile(e)}
                disabled={importer.isPending}
              />
            </label>

            {report && (
              <div className={styles.report}>
                <p className={styles.reportSummary}>
                  Imported {report.imported} · skipped {report.skipped} · failed {report.failed.length}
                </p>
                {report.failed.length > 0 && (
                  <ul className={styles.failList}>
                    {report.failed.map((f) => (
                      <li key={f.url}>
                        <span className={styles.failUrl}>{f.url}</span> — {f.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <div className={styles.actions}>
            <Dialog.Close asChild>
              <button type="button" className={styles.close}>
                Done
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
