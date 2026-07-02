"""SQLAlchemy ORM models mirroring the DESIGN.md §4 schema.

The Alembic baseline migration (``migrations/versions/0001_initial.py``) is the
source of truth for the DDL — including the ``strip_html`` function and the
generated ``entries.search_tsv`` column, which cannot be fully expressed here.
These models mirror that schema for use by the store layer and query building;
``search_tsv`` is mapped read-only.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    clerk_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    quota_subs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Icon(Base):
    __tablename__ = "icons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    url: Mapped[str | None] = mapped_column(Text, unique=True)
    mime: Mapped[str | None] = mapped_column(Text)
    data: Mapped[bytes | None] = mapped_column(LargeBinary)


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    site_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("'epoch'")
    )
    claimed_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("'epoch'")
    )
    check_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3600")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    icon_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("icons.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feed_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("feeds.id"), nullable=False)
    folder_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("folders.id", ondelete="SET NULL")
    )
    title_override: Mapped[str | None] = mapped_column(Text)
    since_entry_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feed_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False
    )
    guid_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    author: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_raw: Mapped[bytes | None] = mapped_column(LargeBinary)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Generated column (STORED); DDL lives in the migration. Read-only here.
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, FetchedValue(), nullable=True)


class EntryState(Base):
    __tablename__ = "entry_states"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
