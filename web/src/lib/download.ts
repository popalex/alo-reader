// Hand the browser a file the app fetched itself. A plain <a href download> can't
// send the bearer token the API needs in clerk mode, so the caller fetches the bytes
// and this saves them through a short-lived object URL.

export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  // Revoked on the next task: some browsers start the download after click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Today's local date as YYYY-MM-DD, for file names that sort by date. */
export function localDateStamp(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
