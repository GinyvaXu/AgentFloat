# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 快报生成线程

抓取（news_fetcher）→ 可选本地 Agent 摘要 → 落盘 news/<date>.json|md → 通知主线程。

复用 local_ai_service 的 headless 调用（与 AI 自检服务同一套 Agent 通道），
架构参考致谢：TrendRadar / agents-radar / condenseit / ai-daily-skill
（详见 docs/AI快报与多功能浮窗助手调研报告.md）。
"""
import json
import logging
import os
import re
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

from agentfloat.services.skills.ai_service import run_headless, build_headless_command
from agentfloat.services.news.fetcher import (
    DEFAULT_NEWS, fetch_all_stats, dedupe, guess_category, filter_blocked,
    build_raw_markdown, save_report, news_storage_dir, cleanup_old,
)

logger = logging.getLogger("AgentFloat.News")

NEWS_TIMEOUT_SECONDS = 420  # 生成一整期快报的宽限超时


def _cur_date():
    return time.strftime("%Y-%m-%d")


def _pick_agent(agents, agent_id):
    """按 agent_id 选 Agent；空 / 找不到 → 默认主 Agent"""
    if agent_id:
        for a in agents or []:
            if a.get("id") == agent_id:
                return a
    for a in agents or []:
        if a.get("primary"):
            return a
    return (agents or [None])[0]


def _interests_block(interests):
    """关注主题 → 提示词段落（按权重降序）"""
    rows = [r for r in (interests or []) if (r.get("label") or "").strip()]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: int(r.get("weight") or 0), reverse=True)
    lines = "\n".join("- [权重%d] %s" % (int(r.get("weight") or 1), r["label"].strip())
                       for r in rows)
    return (
        "用户关注主题（权重从高到低，越靠前越要优先覆盖）：\n%s\n\n"
        "要求：优先收录与上述主题相关的条目；若某主题当日无相关内容可跳过，不要硬凑。\n\n" % lines
    )


def build_ai_prompt(items, language="zh", max_items=6, interests=None):
    """构造快报摘要提示词（结构化 JSON 输出）"""
    lang_rule = {
        "zh": "使用简体中文撰写摘要",
        "en": "Write summaries in English",
        "both": "摘要使用简体中文，同时保留英文原标题（格式：中文摘要 — 英文标题）",
    }.get(language, "使用简体中文撰写摘要")
    lines = []
    for i, it in enumerate(items[:max_items * 3], 1):
        lines.append("%d. [%s] %s | %s" % (i, it.get("source", "?"),
                                           (it.get("title") or "?").replace("\n", " "),
                                           it.get("url", "")))
    items_text = "\n".join(lines)
    return (
        "你是 AgentFloat 的 AI 快报编辑。\n"
        "任务：把下面抓取到的 AI 行业资讯精选并改写为今日速览。\n\n"
        "%s"
        "抓取条目（标题 + 来源 + 链接）：\n%s\n\n"
        "要求：\n"
        "1. 精选最值得关注的 %d 条，去重、去广告与无关内容；\n"
        "2. %s；\n"
        "3. 每条给出：分类标签（模型/工具/论文/产品/行业/综合）、"
        "一句话 30~70 字的摘要、原始链接；\n"
        "4. headline：一句话概括今日主题（20 字内）；\n"
        "5. 只输出一个 JSON 对象（```json 代码块包裹，不要输出其他文字）：\n"
        "{\n"
        "  \"headline\": \"...\",\n"
        "  \"items\": [\n"
        "    {\"title\": \"原文标题\", \"url\": \"原文链接\", \"category\": \"模型\", "
        "\"summary\": \"一句话摘要\"}\n"
        "  ]\n"
        "}\n"
        "URL 必须原样保留上面给出的链接，禁止捏造。"
    ) % (_interests_block(interests), items_text, max_items, lang_rule)


def parse_ai_result(text):
    """解析 AI 输出 JSON；失败抛 ValueError"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text or "", re.S | re.I)
    candidate = m.group(1) if m else (text or "")
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(candidate[start:end + 1])


def _render_ai_markdown(data, date, language):
    """AI 摘要 → Markdown（面板展示 + 存档）"""
    items = data.get("items") or []
    headline = (data.get("headline") or "").strip()
    if language == "en":
        title = "AI Daily Brief (%s)" % date
        head = "**%s**  %s" % (headline, date)
    else:
        title = "今日 AI 速览（%s）" % date
        head = "**%s**  %s" % (headline, date)
    lines = ["# %s" % title, "", head, ""]
    for it in items:
        cat = it.get("category") or "综合"
        title_txt = (it.get("title") or "?").strip()
        summary = (it.get("summary") or "").strip()
        url = (it.get("url") or "#").strip()
        lines.append("## [%s] %s" % (cat, title_txt))
        if summary:
            lines.append(summary)
        if url and url != "#":
            lines.append("来源：[%s](%s)" % (url.split("//")[-1].split("/")[0], url))
        lines.append("")
    return "\n".join(lines)


class NewsWorker(QThread):
    """快报生成线程（v3.9.0 重写）：阶段化进度 → 抓取 → 去重 → AI 摘要 → 落盘

    新增：
    - progress(phase, done, total, label)：阶段化进度（抓取逐源 / 去重 / AI / 保存）
    - 可取消：每个阶段与每源之间检查 cancel，取消后不落盘
    - 逐源结果 sources：失败源可在界面上单独重试
    - 屏蔽关键词 / 每源条数 / AI 摘要条数上限
    """
    done = pyqtSignal(dict)                          # save_report 的 payload
    failed = pyqtSignal(str)
    progress = pyqtSignal(str, int, int, str)        # phase, done, total, label

    PHASES = {
        "fetch": "抓取数据源",
        "dedupe": "去重与筛选",
        "ai": "AI 摘要",
        "save": "写入快报",
    }

    def __init__(self, news_cfg, agents, parent=None):
        super().__init__(parent)
        self._cfg = dict(news_cfg or DEFAULT_NEWS)
        self._agents = agents or []
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _emit(self, phase, done=0, total=0, label=""):
        try:
            self.progress.emit(phase, int(done), int(total), label or self.PHASES.get(phase, ""))
        except Exception:  # noqa: BLE001
            pass

    def run(self):
        try:
            self._run()
        except Exception as e:
            import traceback
            try:
                logger.error("AI 快报生成异常:\n%s", traceback.format_exc())
            except Exception:
                pass
            self.failed.emit("AI 快报生成失败: %s" % str(e))

    def _run(self):
        cfg = self._cfg
        enabled = cfg.get("sources") or DEFAULT_NEWS["sources"]
        max_items = max(1, min(20, int(cfg.get("max_items") or 6)))
        per_source = max(3, min(30, int(cfg.get("per_source") or 12)))
        ai_max = max(1, min(20, int(cfg.get("ai_max_items") or 6)))
        blocked = cfg.get("blocked_keywords") or []
        language = cfg.get("language") or "zh"
        interests = cfg.get("interests") or []
        date = _cur_date()

        logger.info("AI 快报开始生成: date=%s sources=%s max=%d per=%d",
                    date, enabled, max_items, per_source)

        self._emit("fetch", 0, len(enabled), "准备抓取 %d 个源" % len(enabled))
        items, errors, sources = fetch_all_stats(
            enabled, per_source=per_source,
            progress=lambda done, total, label: self._emit("fetch", done, total, label))
        if self._cancel.is_set():
            self.failed.emit("已取消生成")
            return
        if not items:
            self.failed.emit("所有数据源抓取失败：\n%s" % ("\n".join(errors[:5]) or "无数据"))
            return

        self._emit("dedupe", 0, 0, "去重与筛选（原始 %d 条）" % len(items))
        before_block = len(items)
        items = filter_blocked(items, blocked)
        blocked_count = before_block - len(items)
        items = dedupe(items, max_items * 3)
        stats = {"raw": before_block, "blocked": blocked_count,
                 "deduped": len(items), "shown": 0, "ai_max": ai_max}

        used_ai = False
        data = None
        if cfg.get("use_ai", True):
            agent = _pick_agent(self._agents, cfg.get("agent_id"))
            if agent and build_headless_command(agent, "ping")[0] is not None:
                self._emit("ai", 0, 0, "调用 %s 生成摘要…" % (agent.get("name") or "本地 Agent"))
                try:
                    prompt = build_ai_prompt(items, language, ai_max, interests)
                    out, err = run_headless(agent, prompt, cancel=self._cancel)
                    if out is None:
                        raise RuntimeError(err or "Agent 调用失败")
                    data = parse_ai_result(out)
                    if not (data.get("items") or []):
                        raise RuntimeError("AI 未返回任何条目")
                    used_ai = True
                except Exception as e:
                    if self._cancel.is_set():
                        self.failed.emit("已取消生成")
                        return
                    logger.warning("AI 摘要失败，回退纯列表: %s", e)
                    data = None
            else:
                self._emit("ai", 0, 0, "未找到可用的本地 Agent，跳过 AI 摘要")
        else:
            self._emit("ai", 0, 0, "已关闭 AI 摘要，使用标题列表")

        if data:
            final_items = []
            for it in data.get("items") or []:
                title = (it.get("title") or "").strip()
                url = (it.get("url") or "").strip()
                if not title or not url or url == "#":
                    continue
                final_items.append({
                    "title": title,
                    "url": url,
                    "category": it.get("category") or guess_category(title, url),
                    "summary": (it.get("summary") or "").strip(),
                    "source": _guess_source(url, items),
                })
            headline = (data.get("headline") or "").strip()
            raw_md = _render_ai_markdown({"items": final_items, "headline": headline},
                                         date, language)
        else:
            ranked = _boost_by_interests(items, interests)
            final_items = [{
                "title": it.get("title", "?"),
                "url": it.get("url", "#"),
                "category": guess_category(it.get("title", ""), it.get("url", "")),
                "summary": "",
                "source": it.get("source", ""),
            } for it in ranked[:max_items]]
            headline = ""
            raw_md = build_raw_markdown(ranked[:max_items], date, language)

        if self._cancel.is_set():
            self.failed.emit("已取消生成")
            return

        self._emit("save", 0, 0, "写入快报（%d 条）" % len(final_items))
        stats["shown"] = len(final_items)
        payload = save_report(date, final_items, raw_md, language, used_ai, errors,
                              sources=sources, stats=stats, headline=headline)
        try:
            cleanup_old(cfg.get("retention_days", 14))
        except Exception as e:  # noqa: BLE001
            logger.warning("清理历史快报失败: %s", e)
        logger.info("AI 快报完成: date=%s count=%d used_ai=%s blocked=%d",
                    date, len(final_items), used_ai, blocked_count)
        self.done.emit(payload)


def _boost_by_interests(items, interests):
    """纯列表模式：命中关注主题关键词的条目按权重提前，其余保持时间序"""
    rows = [r for r in (interests or []) if (r.get("label") or "").strip()]
    if not rows:
        return items
    def score(it):
        text = ("%s %s" % (it.get("title", ""), it.get("url", ""))).lower()
        s = 0
        for r in rows:
            for kw in r["label"].replace("，", ",").split(","):
                kw = kw.strip()
                if kw and kw.lower() in text:
                    s += int(r.get("weight") or 1)
        return s
    return sorted(items, key=lambda it: (-score(it), -(it.get("ts") or 0)))


def _guess_source(url, fetched):
    """按 URL 反查条目来源（AI 返回的链接需要补 source 字段）"""
    u = (url or "").lower()
    for it in fetched:
        if (it.get("url") or "").lower() == u:
            return it.get("source", "")
    for host, src in (("news.ycombinator.com", "Hacker News"), ("github.com", "GitHub"),
                      ("sspai.com", "少数派"), ("qbitai.com", "量子位"),
                      ("arxiv.org", "arXiv AI")):
        if host in u:
            return src
    return ""


def today_news_exists():
    """当日快报是否已生成（用于启动补生成与每日定时防重）"""
    p = os.path.join(news_storage_dir(), "%s.json" % _cur_date())
    return os.path.exists(p)
