# -*- coding: utf-8 -*-
"""Content Catalog — schema 校验单测（P1 第一刀）

覆盖风暴稿冻结的四条硬规则：三值 platforms、一记录 + variants、status 三态、
verifiedAt 保鲜；以及安装方式、正则、未知字段等边界。
"""
import copy
from datetime import date, timedelta

import pytest

from agentfloat.services.catalog.schema import (
    AgentSpec,
    CatalogError,
    CatalogManifest,
    semver_key,
    validate_agents,
)


def opencode_spec():
    """冻结名单第 04 条（OpenCode），含 v1/v2 variants。"""
    return {
        "schemaVersion": 1,
        "id": "opencode",
        "name": "OpenCode",
        "vendor": "Anomaly",
        "group": "intl-cli",
        "platforms": {"windows": "native", "macos": "native", "linux": "native"},
        "install": [
            {"type": "npm", "packageOrUrl": "@opencode/cli", "verify": "opencode --version"},
            {"type": "script", "packageOrUrl": "https://opencode.ai/v2/install", "reversible": False},
        ],
        "launch": {
            "command": "opencode",
            "variants": [
                {"id": "v2", "package": "@opencode/cli", "minVersion": "2.0.0"},
                {"id": "v1", "command": "opencode2"},
            ],
            "modes": ["interactive", "headless", "desktop"],
            "headless": {"args": ["run", "--format", "json"], "verified": False},
        },
        "capability": {"headless": True, "mcp": True, "skills": True, "resume": True},
        "health": {"versionCmd": "opencode --version", "versionPattern": r"v?(\d+\.\d+\.\d+)"},
        "status": "active",
        "verifiedAt": "2026-10-23",
        "source": "https://github.com/anomalyco/opencode",
    }


def test_parse_frozen_entry():
    spec = AgentSpec.from_dict(opencode_spec())
    assert spec.id == "opencode"
    assert spec.group == "intl-cli"
    assert spec.launch.command == "opencode"
    assert [v.id for v in spec.launch.variants] == ["v2", "v1"]
    assert spec.capability.headless is True
    assert spec.primary_install().type == "npm"   # npm 优先于官方脚本


def test_round_trip_is_stable():
    spec = AgentSpec.from_dict(opencode_spec())
    again = AgentSpec.from_dict(spec.to_dict())
    assert again.to_dict() == spec.to_dict()


def test_platforms_is_three_valued_enum():
    """布尔写法必须被拒——Amp 是「Windows 能装、只能 WSL 跑」，布尔会误报。"""
    raw = opencode_spec()
    raw["platforms"] = {"windows": True, "macos": "native"}
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("platforms.windows" in msg and "native/wsl/none" in msg for msg in exc.value.errors)


def test_platforms_default_and_partial_fill():
    raw = opencode_spec()
    raw.pop("platforms")
    spec = AgentSpec.from_dict(raw)
    assert spec.support("windows") == "native"
    assert spec.runs_on("linux") is True

    raw = opencode_spec()
    raw["platforms"] = {"windows": "wsl"}
    spec = AgentSpec.from_dict(raw)
    assert spec.support("windows") == "wsl"
    assert spec.runs_on("windows") is True          # wsl 也算能跑
    assert spec.support("macos") == "none"


def test_unknown_platform_key_rejected():
    raw = opencode_spec()
    raw["platforms"] = {"windows": "native", "android": "native"}
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("android" in msg for msg in exc.value.errors)


def test_missing_and_malformed_id():
    raw = opencode_spec()
    raw.pop("id")
    with pytest.raises(CatalogError):
        AgentSpec.from_dict(raw)

    raw = opencode_spec()
    raw["id"] = "OpenCode CLI"
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("小写字母" in msg for msg in exc.value.errors)


def test_group_must_be_known():
    raw = opencode_spec()
    raw["group"] = "cli"
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("group" in msg for msg in exc.value.errors)


def test_install_requires_at_least_one_step():
    raw = opencode_spec()
    raw["install"] = []
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("install 至少" in msg for msg in exc.value.errors)


def test_script_install_requires_http_url():
    raw = opencode_spec()
    raw["install"] = [{"type": "script", "packageOrUrl": "install.sh"}]
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("http(s)" in msg for msg in exc.value.errors)


def test_install_accepts_url_alias():
    raw = opencode_spec()
    raw["install"] = [{"type": "script", "url": "https://codex.example/install.ps1"}]
    spec = AgentSpec.from_dict(raw)
    assert spec.install[0].package_or_url == "https://codex.example/install.ps1"
    assert spec.install[0].reversible is True


def test_launch_command_required_and_modes_checked():
    raw = opencode_spec()
    raw["launch"] = {"command": "", "modes": ["interactive", "telepathy"]}
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    errors = " ".join(exc.value.errors)
    assert "launch.command" in errors
    assert "telepathy" in errors


def test_variants_reject_duplicate_and_bad_semver():
    raw = opencode_spec()
    raw["launch"]["variants"] = [
        {"id": "v2", "minVersion": "2.0.0"},
        {"id": "v2", "minVersion": "two"},
    ]
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    errors = " ".join(exc.value.errors)
    assert "重复 id" in errors
    assert "semver" in errors


def test_status_eol_requires_note():
    raw = opencode_spec()
    raw["status"] = "eol"
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("statusNote" in msg for msg in exc.value.errors)

    raw["statusNote"] = "已停服，改用 opencode"
    assert AgentSpec.from_dict(raw).status == "eol"


def test_status_only_three_states():
    raw = opencode_spec()
    raw["status"] = "legacy"
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("active/deprecated/eol" in msg for msg in exc.value.errors)


def test_verified_at_format_and_staleness():
    raw = opencode_spec()
    raw["verifiedAt"] = "2026/10/23"
    with pytest.raises(CatalogError):
        AgentSpec.from_dict(raw)

    raw = opencode_spec()
    raw["verifiedAt"] = "2026-07-01"
    spec = AgentSpec.from_dict(raw)
    today = date(2026, 10, 23)
    assert spec.is_stale(today) is True                       # 114 天
    assert spec.is_stale(today - timedelta(days=30)) is False  # 84 天


def test_health_pattern_must_compile():
    raw = opencode_spec()
    raw["health"] = {"versionCmd": "opencode --version", "versionPattern": "v(\\d+"}
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("正则" in msg for msg in exc.value.errors)


def test_unknown_field_is_rejected():
    raw = opencode_spec()
    raw["installerType"] = "npm"      # 拼写/历史字段
    with pytest.raises(CatalogError) as exc:
        AgentSpec.from_dict(raw)
    assert any("未知字段" in msg for msg in exc.value.errors)


def test_validate_agents_drops_only_bad_entries():
    good = opencode_spec()
    bad = copy.deepcopy(opencode_spec())
    bad["id"] = "broken"
    bad["group"] = "nope"
    dup = copy.deepcopy(opencode_spec())

    valid, dropped = validate_agents([good, bad, dup])
    assert [spec.id for spec in valid] == ["opencode"]
    reasons = dict(dropped)
    assert "broken" in reasons and "nope" in reasons["broken"]
    assert "重复 id" in reasons["opencode"]


def test_semver_key():
    assert semver_key("1.2.3") == (1, 2, 3)
    assert semver_key("2.0.0-beta.1") == (2, 0, 0)
    assert semver_key("2.0") is None
    assert semver_key("") is None


# ── manifest ───────────────────────────────────────
def manifest_payload():
    return {
        "schemaVersion": 1,
        "catalogVersion": 42,
        "minAfVersion": "3.16.0",
        "channel": "beta",
        "publishedAt": "2026-10-23T10:00:00+08:00",
        "shards": [
            {"name": "intl-a1b2c3.json", "sha256": "a" * 64, "group": "intl-cli", "count": 10},
        ],
        "mirrors": ["https://dl.ginyva.site/catalog/"],
        "signature": "c2ln",
    }


def test_manifest_round_trip():
    manifest = CatalogManifest.from_dict(manifest_payload(), require_signature=True)
    assert manifest.catalog_version == 42
    assert manifest.shards[0].count == 10
    assert CatalogManifest.from_dict(manifest.to_dict()).to_dict() == manifest.to_dict()


def test_manifest_signature_required_on_release():
    raw = manifest_payload()
    raw.pop("signature")
    with pytest.raises(CatalogError) as exc:
        CatalogManifest.from_dict(raw, require_signature=True)
    assert any("signature" in msg for msg in exc.value.errors)
    # beta 灰度允许先不签名
    assert CatalogManifest.from_dict(raw).signature == ""


def test_manifest_rejects_path_traversal_shard_name():
    raw = manifest_payload()
    raw["shards"] = [{"name": "../../evil.json", "sha256": "b" * 64}]
    with pytest.raises(CatalogError) as exc:
        CatalogManifest.from_dict(raw)
    assert any("安全文件名" in msg for msg in exc.value.errors)


def test_manifest_rejects_bad_sha_and_version():
    raw = manifest_payload()
    raw["catalogVersion"] = 0
    raw["shards"] = [{"name": "cn.json", "sha256": "xyz"}]
    with pytest.raises(CatalogError) as exc:
        CatalogManifest.from_dict(raw)
    errors = " ".join(exc.value.errors)
    assert "catalogVersion" in errors
    assert "sha256" in errors
