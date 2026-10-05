// Download every subscription as one OPML file, the format any other reader
// imports. /legal promises users can take their feeds out at any time; this is
// where they do it without curl.

import { Download, Loader2 } from "lucide-react";

import { useExportOpml } from "../../api/feedMutations";
import styles from "./Sidebar.module.css";

export function ExportFeedsButton() {
  const exporter = useExportOpml();
  const busy = exporter.isPending;
  return (
    <button
      type="button"
      className={styles.footButton}
      aria-label="Export feeds (OPML)"
      title="Export feeds (OPML)"
      disabled={busy}
      aria-busy={busy || undefined}
      onClick={() => exporter.mutate()}
    >
      {busy ? <Loader2 size={16} className={styles.footSpin} /> : <Download size={16} />}
    </button>
  );
}
