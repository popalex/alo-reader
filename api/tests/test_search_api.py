"""Full-text search on the streams endpoint (WP-13, DESIGN.md §4.1).

Covers stemming, websearch operator semantics, robustness to garbage input,
stream scope (incl. searching within starred) + tenant isolation, strict id-desc
chronology, limit capping, the highlighted snippet, and the widened coverage
(author + feed name — including that the global feed-name arm can't leak an
unsubscribed or other-tenant feed's entries).
"""

import os

import httpx

from app import db as app_db
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import subscriptions as subs_store
from app.store.entries import NewEntry

from .conftest import PatUser, make_pat_user

BASE = "/api/v1/streams"


async def seed(
    user_id: int | None,
    docs: list[dict[str, str]],
    *,
    feed_title: str = "Feed",
) -> tuple[int, list[int]]:
    """Create a feed titled ``feed_title`` with ``docs`` (title/author/content_html)
    and, when ``user_id`` is given, subscribe them. Returns ``(feed_id, entry_ids)``
    ascending. Passing ``user_id=None`` seeds a feed nobody in the test is subscribed
    to — for scope/tenant-isolation checks."""
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        feed = await feeds_store.create(
            s, feed_url=f"https://{os.urandom(6).hex()}.example/rss", title=feed_title
        )
        rows: list[NewEntry] = [
            {
                "guid_hash": os.urandom(16),
                "title": d.get("title", ""),
                "author": d.get("author"),
                "content_html": d.get("content_html", ""),
            }
            for d in docs
        ]
        inserted = await entries_store.insert_batch(s, feed.id, rows)
        if user_id is not None:
            await subs_store.create(s, user_id, feed_id=feed.id, since_entry_id=0)
        return feed.id, sorted(e.id for e in inserted)


async def search(
    client: httpx.AsyncClient, pu: PatUser, stream: str, q: str, **params: str | int
) -> httpx.Response:
    return await client.get(
        f"{BASE}/{stream}/entries",
        params={"status": "all", "q": q, **params},
        headers=pu.headers,
    )


async def test_matches_content_with_highlighted_snippet(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    await seed(
        pat_user.user_id,
        [
            {
                "title": "About databases",
                "content_html": "<p>Postgres is a relational database.</p>",
            },
            {"title": "About cooking", "content_html": "<p>How to bake sourdough bread.</p>"},
        ],
    )
    resp = await search(api_client, pat_user, "all", "postgres")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["title"] == "About databases"
    # ts_headline highlights the term with <b> markers.
    assert "<b>Postgres</b>" in entries[0]["snippet"]


async def test_stemming_both_directions(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed(
        pat_user.user_id,
        [
            {"title": "one", "content_html": "<p>She was running late.</p>"},
            {"title": "two", "content_html": "<p>A quick run in the park.</p>"},
        ],
    )
    # 'run' finds "running"; 'running' finds "run" — english stemming, both ways.
    for term in ("run", "running", "runs"):
        found = {
            e["id"] for e in (await search(api_client, pat_user, "all", term)).json()["entries"]
        }
        assert found == set(ids), term


async def test_websearch_operators(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed(
        pat_user.user_id,
        [
            {"title": "a", "content_html": "<p>the quick brown fox</p>"},  # ids[0]
            {"title": "b", "content_html": "<p>brown and quick, no canine</p>"},  # ids[1]
            {"title": "c", "content_html": "<p>alpha centauri</p>"},  # ids[2]
            {"title": "d", "content_html": "<p>omega nebula</p>"},  # ids[3]
        ],
    )

    async def hits(q: str) -> set[int]:
        return {e["id"] for e in (await search(api_client, pat_user, "all", q)).json()["entries"]}

    # Quoted phrase requires adjacency: only the "quick brown" doc.
    assert await hits('"quick brown"') == {ids[0]}
    # OR.
    assert await hits("alpha OR omega") == {ids[2], ids[3]}
    # Exclusion: fox present, brown excluded → neither doc (both have brown or no fox).
    assert await hits("quick -brown") == set()
    assert await hits("fox") == {ids[0]}


async def test_garbage_queries_never_500(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    await seed(pat_user.user_id, [{"title": "x", "content_html": "<p>hello world</p>"}])
    for q in ['"', ":*", "!!!", "& | ! <>", "()))", "\\", "  ", "🚀🚀", "a" * 500, "AND OR NOT"]:
        resp = await search(api_client, pat_user, "all", q)
        assert resp.status_code == 200, (q, resp.status_code)
        assert isinstance(resp.json()["entries"], list)


async def test_scope_and_tenant_isolation(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    fa, ida = await seed(
        pat_user.user_id, [{"title": "a", "content_html": "<p>quantum entanglement</p>"}]
    )
    fb, idb = await seed(
        pat_user.user_id, [{"title": "b", "content_html": "<p>quantum computing</p>"}]
    )
    # A feed this user is NOT subscribed to, containing the same term.
    await seed(None, [{"title": "c", "content_html": "<p>quantum foam</p>"}])

    # 'all' spans only the user's subscriptions — never the unsubscribed feed.
    all_hits = {
        e["id"] for e in (await search(api_client, pat_user, "all", "quantum")).json()["entries"]
    }
    assert all_hits == set(ida) | set(idb)
    # Feed-scoped search stays within that feed.
    feed_hits = {
        e["id"]
        for e in (await search(api_client, pat_user, f"feed/{fa}", "quantum")).json()["entries"]
    }
    assert feed_hits == set(ida)


async def test_results_are_id_desc(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed(
        pat_user.user_id,
        [{"title": f"n{i}", "content_html": "<p>widget</p>"} for i in range(6)],
    )
    got = [e["id"] for e in (await search(api_client, pat_user, "all", "widget")).json()["entries"]]
    assert got == sorted(ids, reverse=True)


async def test_limit_capped_at_50_and_paginates(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed(
        pat_user.user_id,
        [{"title": f"n{i}", "content_html": "<p>widget</p>"} for i in range(60)],
    )
    # Even asking for 200, search caps the page at 50.
    page1 = (await search(api_client, pat_user, "all", "widget", limit=200)).json()
    assert len(page1["entries"]) == 50
    assert page1["next_cursor"] is not None
    assert [e["id"] for e in page1["entries"]] == sorted(ids, reverse=True)[:50]
    # The cursor pages into the remainder.
    page2 = (
        await search(api_client, pat_user, "all", "widget", limit=200, cursor=page1["next_cursor"])
    ).json()
    assert [e["id"] for e in page2["entries"]] == sorted(ids, reverse=True)[50:]
    assert page2["next_cursor"] is None


async def test_matches_author_and_feed_name(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # Author in an otherwise-unrelated doc.
    _, a_ids = await seed(
        pat_user.user_id,
        [{"title": "essay", "author": "Ada Lovelace", "content_html": "<p>on engines</p>"}],
    )
    # Feed name in an otherwise-unrelated doc.
    _, v_ids = await seed(
        pat_user.user_id,
        [{"title": "gadget review", "content_html": "<p>a new phone</p>"}],
        feed_title="The Verge",
    )
    author_hits = {
        e["id"] for e in (await search(api_client, pat_user, "all", "lovelace")).json()["entries"]
    }
    assert author_hits == set(a_ids)
    feed_hits = {
        e["id"] for e in (await search(api_client, pat_user, "all", "verge")).json()["entries"]
    }
    assert feed_hits == set(v_ids)


async def test_blank_q_is_normal_listing(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    # >50 entries so we can prove blank q is NOT capped like search is.
    _, ids = await seed(
        pat_user.user_id,
        [{"title": f"n{i}", "content_html": "<p>body</p>"} for i in range(55)],
    )
    resp = await api_client.get(
        f"{BASE}/all/entries",
        params={"status": "all", "q": "   ", "limit": 200},
        headers=pat_user.headers,
    )
    body = resp.json()
    assert len(body["entries"]) == 55  # not capped at 50
    assert all(e["snippet"] is None for e in body["entries"])  # no search → no snippet


async def test_search_excludes_other_tenant_via_second_user(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    other = await make_pat_user(email="other@example.com")
    await seed(other.user_id, [{"title": "secret", "content_html": "<p>plutonium recipe</p>"}])
    hits = (await search(api_client, pat_user, "all", "plutonium")).json()["entries"]
    assert hits == []


async def test_search_within_starred_stream(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # A, B, D mention "photon"; C mentions "gluon".
    _, ids = await seed(
        pat_user.user_id,
        [
            {"title": "a", "content_html": "<p>photon drive</p>"},
            {"title": "b", "content_html": "<p>photon sail</p>"},
            {"title": "c", "content_html": "<p>gluon field</p>"},
            {"title": "d", "content_html": "<p>photon torpedo</p>"},
        ],
    )
    a, b, c, d = ids
    # Star A, C and D (not B).
    await api_client.post(
        "/api/v1/entries/state",
        json={"ids": [a, c, d], "starred": True},
        headers=pat_user.headers,
    )
    # Searching the starred stream returns only entries that are BOTH starred and a
    # match: A and D (B is unstarred; C is starred but has no "photon").
    hits = {
        e["id"] for e in (await search(api_client, pat_user, "starred", "photon")).json()["entries"]
    }
    assert hits == {a, d}


async def test_feed_name_match_respects_subscription_and_tenant(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # The feed-name arm queries the GLOBAL feeds table, so prove it can't leak
    # entries from a name-matching feed the user can't see. All three feeds match
    # "alpha" by name; only the user's own subscribed one may return.
    _, mine = await seed(
        pat_user.user_id,
        [{"title": "x", "content_html": "<p>morning coffee</p>"}],  # content does NOT match
        feed_title="Alpha Report",
    )
    # Name-matching feed this user is not subscribed to.
    await seed(
        None, [{"title": "y", "content_html": "<p>evening tea</p>"}], feed_title="Alpha Digest"
    )
    # Another tenant's subscribed, name-matching feed.
    other = await make_pat_user(email="alpha-other@example.com")
    await seed(
        other.user_id,
        [{"title": "z", "content_html": "<p>noon soup</p>"}],
        feed_title="Alpha Vault",
    )

    hits = {e["id"] for e in (await search(api_client, pat_user, "all", "alpha")).json()["entries"]}
    assert hits == set(mine)
