// A feed's favicon: the fetched icon when we have one, else a stable coloured
// initial derived from the title. Shared by the sidebar and the entry list.

import styles from "./Favicon.module.css";

function hueFor(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h % 360;
}

export function Favicon({
  title,
  iconUrl,
  size = 16,
}: {
  title: string;
  iconUrl?: string | null;
  size?: number;
}) {
  const dim = { width: size, height: size };
  if (iconUrl) {
    return <img className={styles.img} src={iconUrl} alt="" loading="lazy" style={dim} />;
  }
  const label = (title.trim() || "?").charAt(0).toUpperCase();
  return (
    <span
      className={styles.letter}
      aria-hidden="true"
      style={{ ...dim, background: `hsl(${hueFor(title || "?")} 42% 42%)`, fontSize: Math.round(size * 0.56) }}
    >
      {label}
    </span>
  );
}
