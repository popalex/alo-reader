// Minimal authenticated placeholder: proves the secure path end to end by
// loading /me through the token seam. The real reading UI lands in WP-09/10.

import { useEffect, useState } from "react";

import { ApiError, getMe, type Me } from "../api/client";
import { useTokenGetter } from "../app/auth";

export function Home() {
  const getToken = useTokenGetter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const data = await getMe(token);
        if (!cancelled) setMe(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return (
    <main>
      <h1>alo-reader</h1>
      {error ? (
        <p role="alert">Could not load your account — {error}</p>
      ) : me ? (
        <p>
          Signed in as <strong>{me.email || `user #${me.id}`}</strong> ·{" "}
          {me.counts_summary.total_unread} unread
        </p>
      ) : (
        <p>Loading…</p>
      )}
      <p>A calm, chronological RSS reader. The reading UI arrives with WP-09/10.</p>
    </main>
  );
}
