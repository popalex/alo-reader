// A polite screen-reader announcement when the total unread count changes
// (WP-12 accessibility). Counts update after mark-read / mark-all / refresh;
// this reflects the new total into an off-screen aria-live region. The first
// resolved value is not announced (it's the initial state, not a change).

import { useEffect, useRef, useState } from "react";

import { useCounts } from "../api/queries";

export function UnreadAnnouncer() {
  const counts = useCounts();
  const total = counts.data?.total_unread;
  const prev = useRef<number | undefined>(undefined);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (total == null) return;
    if (prev.current != null && total !== prev.current) {
      setMessage(`${total} unread ${total === 1 ? "article" : "articles"}`);
    }
    prev.current = total;
  }, [total]);

  return (
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {message}
    </div>
  );
}
