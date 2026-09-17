# Copy brief — WP-17 landing page

## The job

Write the words for a one-page site at `/` that turns a curious stranger into a
signed-up reader, plus the microcopy on the signed-out screen at `/app`.

Read [`PROOF.md`](PROOF.md) first. It is not background — it is the set of things you
are permitted to say, with the numbers attached. **No claim and no number appears in
your copy unless it appears there.** If a sentence you want to write needs a fact that
is not in it, say so and stop; the fact gets verified and added, or the sentence goes.

## Who is reading

Two people, and the copy has to work for both without a word wasted on either:

1. **Someone leaving another reader.** Feedly, Inoreader, Reeder, an abandoned
   Google Reader habit. They have an OPML file and a grievance — usually an algorithm
   that started deciding what they see, or a price rise, or an app that got busier
   every release. They are not asking "what is RSS".
2. **The link-from-Mastodon skeptic.** Will read the page in 20 seconds, then look for
   the part where you are lying. Checks whether "private" survives contact with the
   architecture section. This person is why PROOF.md exists, and winning them is worth
   more than any phrase, because they are the one who posts the link.

Neither needs RSS explained. Both need to know, fast: what does this refuse to do that
the others do.

## Voice

The product's pitch is the absence of hype. The copy has to sound like the thing it is
selling: **calm, specific, finished**. Short sentences. Concrete nouns. The reader
should finish the page feeling that nobody tried to excite them.

DESIGN.md's own line is the best sentence written about this product so far, and the
page should be built around it rather than around something new:

> An inbox for the web: no algorithms, no recommendations, no engagement mechanics.

**Banned outright** — these are not stylistic preferences, they are the wrong product:

- "Supercharge", "unleash", "revolutionary", "seamless", "effortless", "delightful",
  "game-changing", "reimagined", "10x", "blazing fast"
- Anything with AI in it. There is no AI in this product and that is a selling point.
- Exclamation marks. Rhetorical questions as headings. "Ever wondered…"
- Second-person flattery ("you're the kind of reader who…")
- Fake scarcity, countdowns, "join thousands of…" (there are no thousands)
- Em-dash-heavy rhythm and triplet constructions used for drama. One clean statement
  beats three escalating ones.
- Emoji. The project bans them in the UI (Lucide or SVG only); the same applies here.

**Reach for instead:** the number, the refusal, the mechanism. "Feeds are checked every
15 minutes to 24 hours, adapting to how often they publish" beats "lightning-fast
updates" — it is more impressive *and* it is true.

## What the page has to do, in order

The structure is fixed by WP-17; you are writing into it, not redesigning it.

1. **Hero.** What this is and what it refuses to do, in one headline and at most two
   supporting lines. The refusal is the differentiator — lead with it.
2. **Proof.** Four to six points, each one sentence, each traceable to PROOF.md:
   chronological order · keyboard-driven · offline · search across your own archive
   (with the benchmark number and its caveat) · OPML import in one step · self-hostable.
   Pick the order that reads best; put OPML high, because it removes the reason not to
   switch.
3. **Trust.** The section nobody else writes. What happens to your data, in plain words:
   starred kept forever, unread never purged, read-and-unstarred purged after the
   horizon and only once everyone who subscribes has read it. Who else touches it
   (Clerk holds identity — name it). Free while in beta, with limits, and why that is
   the honest phrasing. This section converts the skeptic, so it gets real sentences,
   not bullet fragments.
4. **CTA.** One primary action: create an account. One secondary, quieter: self-host it.

## Deliverables

- **Three headline options**, different angles — one leading on refusal, one on
  chronology, one on calm. Say which you would ship and why, in one line each.
- **One full body set** for the sections above, with a tightened variant of the proof
  section (~40% shorter) so the design pass can choose based on how the page breathes.
- **Meta**: `<title>` (≤60 chars), meta description (≤155), OG title and description.
  These are what people actually see when the link is shared — treat them as primary
  copy, not an afterthought.
- **Microcopy**: primary CTA button, secondary link, the one line above the Clerk
  widget on `/app`'s signed-out screen, and the empty-state sentence a brand-new
  account sees before it has feeds.
- **A claims table**: every factual sentence you wrote, mapped to its PROOF.md row.
  This is the WP-17 acceptance check; producing it as you go is cheaper than
  reconstructing it later.

## Traps specific to this product

- **Do not oversell offline.** Articles opened while online stay readable, and
  read/star changes queue and replay. Unopened articles are not there. Say what it is.
- **Do not say "open source".** There is no LICENSE file yet. "Self-hostable" is the
  claim that is currently true.
- **Do not say "private" as an absolute.** Clerk holds identity. The strong, honest
  version is specific: no third-party analytics, no tracking pixels, self-hosted
  telemetry, and here is exactly who sees what.
- **Do not promise uptime.** One box, beta.
- **Do not compare to named competitors.** Describe what this does; let the reader do
  the subtraction.
