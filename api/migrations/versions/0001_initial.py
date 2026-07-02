"""initial schema (DESIGN.md §4)

Revision ID: 0001
Revises:
Create Date: 2026-07-02

The DDL below reproduces DESIGN.md §4 as-is, with one unavoidable correction:
§4 writes ``CREATE INDEX idx_feeds_due ON feeds (next_check_at) WHERE claimed_until
< now()``. A partial-index predicate must be IMMUTABLE, and ``now()`` is STABLE, so
Postgres rejects that. We keep the intent (fast lookup of due, unclaimed feeds for
the WP-05 claim query) with a plain composite index ``(next_check_at, claimed_until)``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS: list[str] = [
    # ── strip_html: IMMUTABLE tag-stripper used by the generated search_tsv column
    """
    CREATE FUNCTION strip_html(text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT regexp_replace($1, '<[^>]*>', ' ', 'g') $$
    """,
    # ── users
    """
    CREATE TABLE users (
        id             BIGSERIAL PRIMARY KEY,
        clerk_user_id  TEXT UNIQUE,
        email          TEXT NOT NULL DEFAULT '',
        quota_subs     INT  NOT NULL DEFAULT 300,
        created_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ── api_tokens
    """
    CREATE TABLE api_tokens (
        id           BIGSERIAL PRIMARY KEY,
        user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash   BYTEA NOT NULL UNIQUE,
        label        TEXT NOT NULL,
        last_used_at timestamptz,
        created_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ── icons (referenced by feeds.icon_id)
    """
    CREATE TABLE icons (
        id   BIGSERIAL PRIMARY KEY,
        url  TEXT UNIQUE,
        mime TEXT,
        data BYTEA
    )
    """,
    # ── feeds (global, deduped across all users)
    """
    CREATE TABLE feeds (
        id               BIGSERIAL PRIMARY KEY,
        feed_url         TEXT NOT NULL UNIQUE,
        site_url         TEXT,
        title            TEXT NOT NULL DEFAULT '',
        etag             TEXT,
        last_modified    TEXT,
        next_check_at    timestamptz NOT NULL DEFAULT 'epoch',
        claimed_until    timestamptz NOT NULL DEFAULT 'epoch',
        check_interval_s INT NOT NULL DEFAULT 3600,
        error_count      INT NOT NULL DEFAULT 0,
        last_error       TEXT,
        last_fetched_at  timestamptz,
        icon_id          BIGINT REFERENCES icons(id),
        created_at       timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX idx_feeds_due ON feeds (next_check_at, claimed_until)",
    # ── folders
    """
    CREATE TABLE folders (
        id       BIGSERIAL PRIMARY KEY,
        user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name     TEXT NOT NULL,
        position INT NOT NULL DEFAULT 0,
        UNIQUE (user_id, name)
    )
    """,
    # ── subscriptions
    """
    CREATE TABLE subscriptions (
        id             BIGSERIAL PRIMARY KEY,
        user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        feed_id        BIGINT NOT NULL REFERENCES feeds(id),
        folder_id      BIGINT REFERENCES folders(id) ON DELETE SET NULL,
        title_override TEXT,
        since_entry_id BIGINT NOT NULL DEFAULT 0,
        created_at     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, feed_id)
    )
    """,
    "CREATE INDEX idx_subs_feed ON subscriptions (feed_id)",
    # ── entries (search_tsv generated STORED; strip_html + english regconfig)
    """
    CREATE TABLE entries (
        id            BIGSERIAL PRIMARY KEY,
        feed_id       BIGINT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
        guid_hash     BYTEA NOT NULL,
        url           TEXT,
        title         TEXT NOT NULL DEFAULT '',
        author        TEXT,
        content_html  TEXT NOT NULL DEFAULT '',
        content_raw   BYTEA,
        published_at  timestamptz,
        created_at    timestamptz NOT NULL DEFAULT now(),
        search_tsv    tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
                        || setweight(
                             to_tsvector('english'::regconfig,
                                         left(strip_html(content_html), 20000)), 'B')
                      ) STORED,
        UNIQUE (feed_id, guid_hash)
    )
    """,
    "CREATE INDEX idx_entries_feed ON entries (feed_id, id DESC)",
    "CREATE INDEX idx_entries_fts ON entries USING GIN (search_tsv)",
    # ── entry_states (per-user; row exists only once touched)
    """
    CREATE TABLE entry_states (
        user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        entry_id   BIGINT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        is_read    BOOLEAN NOT NULL DEFAULT false,
        is_starred BOOLEAN NOT NULL DEFAULT false,
        changed_at timestamptz NOT NULL,
        PRIMARY KEY (user_id, entry_id)
    )
    """,
    "CREATE INDEX idx_states_read    ON entry_states (user_id, entry_id) WHERE is_read",
    "CREATE INDEX idx_states_starred ON entry_states (user_id, entry_id) WHERE is_starred",
    # ── Supplementary indexes (beyond §4) — speed up FK cascades and hot queries.
    #    Postgres does NOT auto-index foreign keys; unindexed FKs make parent
    #    deletes do full scans of the child, and these columns are queried directly.
    # api_tokens.user_id: cascade on user delete + list-tokens-by-user (WP-02).
    "CREATE INDEX idx_api_tokens_user ON api_tokens (user_id)",
    # subscriptions.folder_id: ON DELETE SET NULL cascade + folder-stream listing.
    "CREATE INDEX idx_subs_folder ON subscriptions (folder_id)",
    # entry_states.entry_id: cascade on entry delete (PK is user_id-first, so
    # entry_id alone is not a usable prefix).
    "CREATE INDEX idx_states_entry ON entry_states (entry_id)",
    # folders: ordered per-user listing (the UNIQUE(user_id,name) index doesn't
    # help ORDER BY position).
    "CREATE INDEX idx_folders_user_pos ON folders (user_id, position)",
]

DOWNGRADE_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS entry_states",
    "DROP TABLE IF EXISTS entries",
    "DROP TABLE IF EXISTS subscriptions",
    "DROP TABLE IF EXISTS folders",
    "DROP TABLE IF EXISTS feeds",
    "DROP TABLE IF EXISTS icons",
    "DROP TABLE IF EXISTS api_tokens",
    "DROP TABLE IF EXISTS users",
    "DROP FUNCTION IF EXISTS strip_html(text)",
]


def upgrade() -> None:
    for stmt in UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_STATEMENTS:
        op.execute(stmt)
