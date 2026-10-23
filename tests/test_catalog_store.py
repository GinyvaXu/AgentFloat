# -*- coding: utf-8 -*-
"""Content Catalog — 缓存层单测（原子写 / last-known-good / 文件名白名单 / TTL）"""
import json
import os
import time

from agentfloat.services.catalog.store import CatalogStore


def test_round_trip(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    assert store.write_json("manifest.json", {"catalogVersion": 7}) is True
    assert store.read_json("manifest.json") == {"catalogVersion": 7}


def test_backup_is_kept_and_used_when_primary_corrupts(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    store.write_json("manifest.json", {"catalogVersion": 1})
    store.write_json("manifest.json", {"catalogVersion": 2})

    path = tmp_path / "catalog" / "manifest.json"
    assert path.exists()
    path.write_text("{ this is not json", encoding="utf-8")

    # 主文件坏 → 自动回退 last-known-good（上一份）
    assert store.read_json("manifest.json") == {"catalogVersion": 1}


def test_rejects_path_traversal(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    assert store.write_json("../evil.json", {"x": 1}) is False
    assert store.read_json("../../etc/passwd.json") is None
    assert not (tmp_path / "evil.json").exists()


def test_shard_hash_verification(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    blob = json.dumps([{"id": "opencode"}]).encode("utf-8")
    digest = store.write_shard("intl-abc.json", blob)
    assert digest and len(digest) == 64

    assert store.read_shard("intl-abc.json", expect_sha256=digest) == [{"id": "opencode"}]
    # 哈希对不上：拒绝使用（防止被替换的分包）
    assert store.read_shard("intl-abc.json", expect_sha256="0" * 64) is None


def test_state_freshness(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    assert store.is_fresh() is False           # 从未刷新

    store.save_state(etag="abc", catalog_version=42)
    assert store.is_fresh() is True
    state = store.read_state()
    assert state["catalogVersion"] == 42 and state["etag"] == "abc"

    # 25 小时后过期
    later = time.time() + 25 * 3600
    assert store.is_fresh(ttl_hours=24, now=later) is False


def test_corrupt_state_counts_as_stale(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog"))
    os.makedirs(tmp_path / "catalog", exist_ok=True)
    (tmp_path / "catalog" / "state.json").write_text('{"fetchedAt": "not-a-date"}', encoding="utf-8")
    assert store.is_fresh() is False


def test_env_override_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFLOAT_CATALOG_DIR", str(tmp_path / "from-env"))
    store = CatalogStore()
    assert store.root == os.path.abspath(str(tmp_path / "from-env"))
    store.write_json("state.json", {"ok": True})
    assert (tmp_path / "from-env" / "state.json").exists()
