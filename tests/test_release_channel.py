# -*- coding: utf-8 -*-
"""v3.10.0 测试版通道测试：版本标签 / 每次当第一次打开 / 策略文档存在"""
import io
import os

from agentfloat.core import version as ver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_is_numeric_semver():
    """版本号必须保持纯数字（带 -beta 会导致后续正式版无法被判定为更新）"""
    assert ver.VERSION.replace(".", "").isdigit(), ver.VERSION
    assert "-" not in ver.VERSION and "beta" not in ver.VERSION.lower()


def test_beta_channel_default():
    assert ver.CHANNEL == ver.CHANNEL_BETA
    assert ver.is_beta() is True


def test_version_label_marks_beta():
    assert ver.version_label() == "v%s 测试版" % ver.VERSION
    assert ver.version_label("9.9.9").endswith("测试版")


def test_version_label_stable_when_channel_switches(monkeypatch):
    monkeypatch.setattr(ver, "CHANNEL", ver.CHANNEL_STABLE)
    assert ver.is_beta() is False
    assert ver.version_label() == "v%s" % ver.VERSION


def test_policy_doc_exists():
    p = os.path.join(ROOT, "docs", "发布与版本策略.md")
    assert os.path.isfile(p), "缺少发布策略文档"
    text = io.open(p, encoding="utf-8").read()
    for kw in ("测试版", "本地安装", "push 源码", "打 git tag", "建 GitHub Release",
               "官网镜像同步", "第一次打开"):
        assert kw in text, "策略文档缺少要点：%s" % kw


def test_agents_md_records_policy():
    text = io.open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read()
    assert "发布通道" in text and "测试版" in text


def test_onboarding_replays_on_beta():
    """测试版忽略已看标记（每次打开都当第一次打开）"""
    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball.FloatingWidget.maybe_start_onboarding)
    assert "is_beta()" in src, "引导应检查测试版通道"
    assert "not is_beta() and" in src, "测试版下应忽略 onboarding_done"


def test_state_exposes_version_label():
    import inspect
    from agentfloat.webshell import handlers
    src = inspect.getsource(handlers)
    assert "version_label" in src, "/api/state 应提供带通道标记的版本号"
