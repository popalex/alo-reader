"""Folder CRUD endpoints + cross-tenant isolation (WP-06)."""

import httpx

from .conftest import PatUser, make_pat_user

BASE = "/api/v1/folders"


async def test_folder_crud_roundtrip(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    h = pat_user.headers

    created = await api_client.post(BASE, json={"name": "Tech", "position": 2}, headers=h)
    assert created.status_code == 201
    folder = created.json()
    assert folder["name"] == "Tech" and folder["position"] == 2
    fid = folder["id"]

    listed = await api_client.get(BASE, headers=h)
    assert listed.status_code == 200
    assert [f["id"] for f in listed.json()] == [fid]

    patched = await api_client.patch(f"{BASE}/{fid}", json={"name": "News"}, headers=h)
    assert patched.status_code == 200
    assert patched.json()["name"] == "News"
    assert patched.json()["position"] == 2  # unchanged

    deleted = await api_client.delete(f"{BASE}/{fid}", headers=h)
    assert deleted.status_code == 204
    assert (await api_client.get(BASE, headers=h)).json() == []


async def test_create_folder_rejects_empty_name(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    resp = await api_client.post(BASE, json={"name": ""}, headers=pat_user.headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_cross_tenant_folder_is_404_not_403(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # User A owns a folder.
    created = await api_client.post(BASE, json={"name": "A's"}, headers=pat_user.headers)
    fid = created.json()["id"]

    # User B cannot see, patch, or delete it — every attempt is an indistinguishable 404.
    other = await make_pat_user("bob@example.com")
    assert (await api_client.get(BASE, headers=other.headers)).json() == []
    patch = await api_client.patch(f"{BASE}/{fid}", json={"name": "hijack"}, headers=other.headers)
    assert patch.status_code == 404
    assert patch.json()["error"]["code"] == "not_found"
    delete = await api_client.delete(f"{BASE}/{fid}", headers=other.headers)
    assert delete.status_code == 404

    # A's folder is untouched.
    a_list = await api_client.get(BASE, headers=pat_user.headers)
    assert a_list.json()[0]["name"] == "A's"


async def test_patch_missing_folder_is_404(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    resp = await api_client.patch(f"{BASE}/999999", json={"name": "x"}, headers=pat_user.headers)
    assert resp.status_code == 404
