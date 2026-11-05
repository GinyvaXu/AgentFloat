# -*- coding: utf-8 -*-
"""已安装内容读取 + 备份时间线/恢复（临时目录，不触碰真实 Agent）。"""
import os

from agentfloat.services.skills import installer
from agentfloat.services.skills.bundle import read_bundle
from agentfloat.services.skills.workshop import SkillWorkshop


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_bundle_reads_readme_license_files(tmp_path):
    skill = tmp_path / "demo"
    _write(str(skill / "SKILL.md"), "---\nname: demo\n---\n\n# Demo\n")
    _write(str(skill / "README.md"), "# Demo Readme\n\nUsage.\n")
    _write(str(skill / "LICENSE"), "MIT License\n\nPermission is hereby granted...\n")
    _write(str(skill / "references" / "a.md"), "ref\n")

    data = read_bundle(str(skill))
    assert data["ok"] is True
    assert data["readmeName"] == "README.md"
    assert "Usage" in data["readme"]
    assert data["license"] == "MIT"
    assert {f["path"] for f in data["files"]} == {"SKILL.md", "README.md", "LICENSE", "references/a.md"}


def test_backup_list_and_restore(tmp_path):
    src = tmp_path / "src"
    target = tmp_path / "target"
    data_dir = tmp_path / "data"
    os.makedirs(str(target))
    _write(str(src / "SKILL.md"), "# Demo v1\n")
    _write(str(src / "README.md"), "# v1\n")

    ws = SkillWorkshop(targets=[{"id": "test", "label": "测试", "root": str(target)}],
                       data_dir=str(data_dir))
    meta = {"entryId": "local:demo", "sourceType": "local"}
    installer.install_tree(str(src), str(target), "demo", meta=meta,
                           backups_root=ws.backups_dir, entry_id="local:demo")

    _write(str(src / "README.md"), "# v2\n")
    installer.install_tree(str(src), str(target), "demo", meta=meta,
                           backups_root=ws.backups_dir, entry_id="local:demo")

    listed = ws.list_backups()
    assert listed["ok"] is True
    assert len(listed["backups"]) == 1
    backup = listed["backups"][0]
    assert backup["name"] == "demo"
    assert backup["files"] >= 1

    restored = ws.restore_backup(backup["id"], "test")
    assert restored["ok"] is True
    with open(str(target / "demo" / "README.md"), encoding="utf-8") as fh:
        assert fh.read().startswith("# v1")
