# -*- coding: utf-8 -*-
"""C 线安装链路深测：inspect → install → marker → disable → uninstall（全离线、临时目录）。"""
import os

from agentfloat.services.skills import installer


def _make_skill(root, name="demo-skill"):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: demo-skill\ndescription: demo skill\n---\n\n# Demo\n")
    with open(os.path.join(d, "extra.txt"), "w", encoding="utf-8") as f:
        f.write("payload")
    return d


def _dirs(tmp_path):
    targets = tmp_path / "targets"
    backups = tmp_path / "backups"
    trash = tmp_path / "trash"
    for d in (targets, backups, trash):
        d.mkdir()
    return str(targets), str(backups), str(trash)


def test_inspect_tree_reports_files_and_digest(tmp_path):
    src = _make_skill(str(tmp_path / "src"))
    info = installer.inspect_tree(src)
    assert info.files and info.total_bytes > 0 and info.digest


def test_install_then_marker(tmp_path):
    src = _make_skill(str(tmp_path / "src"))
    targets, backups, _trash = _dirs(tmp_path)
    res = installer.install_tree(src, targets, "demo-skill",
                                 meta={"source": "test"}, backups_root=backups,
                                 entry_id="demo-skill")
    assert isinstance(res, dict)
    installed = os.path.join(targets, "demo-skill")
    assert os.path.isdir(installed)
    assert os.path.isfile(os.path.join(installed, "SKILL.md"))
    marker = installer.read_marker(installed)
    assert isinstance(marker, dict) and marker


def test_disable_then_uninstall(tmp_path):
    src = _make_skill(str(tmp_path / "src"))
    targets, backups, trash = _dirs(tmp_path)
    installer.install_tree(src, targets, "demo-skill", backups_root=backups,
                           entry_id="demo-skill")
    assert isinstance(installer.set_enabled(targets, "demo-skill", False), dict)
    out = installer.uninstall_tree(targets, "demo-skill", backups, trash)
    assert isinstance(out, dict)
    assert not os.path.exists(os.path.join(targets, "demo-skill"))


def test_safe_name_and_join():
    assert installer.safe_skill_name("demo-skill") is True
    assert installer.safe_skill_name("../evil") is False
    assert installer.is_within("/a/b", "/a/b/c") is True
    assert installer.is_within("/a/b", "/a/c") is False
