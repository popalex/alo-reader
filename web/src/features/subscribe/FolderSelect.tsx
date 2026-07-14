// The category picker shared by the add-feed and feed-settings dialogs: a
// <select> of folders plus "No category" and "+ New category…", and — when the
// latter is chosen — an inline name input. The create-or-pick resolution differs
// per dialog (the add dialog guards against duplicate creates), so that stays in
// each caller; only the control and the NEW_FOLDER sentinel are shared here.

import type { Folder } from "../../api/endpoints";
import styles from "./FolderSelect.module.css";

export const NEW_FOLDER = "__new__";

export function FolderSelect({
  folders,
  value,
  onChange,
  newName,
  onNewNameChange,
  label = "Category",
}: {
  folders: Folder[];
  value: string;
  onChange: (value: string) => void;
  newName: string;
  onNewNameChange: (value: string) => void;
  label?: string;
}) {
  return (
    <>
      <label className={styles.field}>
        <span className={styles.label}>{label}</span>
        <select className={styles.select} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">No category</option>
          {folders.map((f) => (
            <option key={f.id} value={String(f.id)}>
              {f.name}
            </option>
          ))}
          <option value={NEW_FOLDER}>+ New category…</option>
        </select>
      </label>
      {value === NEW_FOLDER && (
        <input
          className={styles.input}
          type="text"
          placeholder="New category name"
          value={newName}
          onChange={(e) => onNewNameChange(e.target.value)}
          aria-label="New category name"
        />
      )}
    </>
  );
}
