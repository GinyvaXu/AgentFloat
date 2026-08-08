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

from local_ai_service import run_headless, build_headless_command
from news_fetcher import (
    DEFAULT_NEWS, fetch_all, dedupe, guess_category,
    build_raw_markdown, save_report, news_storage_dir,
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
    """快报生成线程：fetch → AI 摘要（可选）→ 落盘"""
    done = pyqtSignal(dict)     # save_report 的 payload
    failed = pyqtSignal(str)

    def __init__(self, news_cfg, agents, parent=None):
        super().__init__(parent)
        self._cfg = dict(news_cfg or DEFAULT_NEWS)
        self._agents = agents or []
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

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
        language = cfg.get("language") or "zh"
        interests = cfg.get("interests") or []
        date = _cur_date()

        logger.info("AI 快报开始生成: date=%s sources=%s max=%d", date, enabled, max_items)
        items, errors = fetch_all(enabled, per_source=12)
        if self._cancel.is_set():
            self.failed.emit("用户退出，生成已取消")
            return
        if not items:
            self.failed.emit("所有数据源抓取失败：\n%s" % ("\n".join(errors[:5]) or "无数据"))
            return
        items = dedupe(items, max_items * 3)

        used_ai = False
        if cfg.get("use_ai", True):
            agent = _pick_agent(self._agents, cfg.get("agent_id"))
            if agent and build_headless_command(agent, "ping")[0] is not None:
                try:
                    prompt = build_ai_prompt(items, language, max_items, interests)
                    out, err = run_headless(agent, prompt, cancel=self._cancel)
                    if out is None:
                        raise RuntimeError(err or "Agent 调用失败")
                    data = parse_ai_result(out)
                    curated = data.get("items") or []
                    if not curated:
                        raise RuntimeError("AI 未返回任何条目")
                    used_ai = True
                except Exception as e:
                    logger.warning("AI 摘要失败，回退纯列表: %s", e)
                    data = None
            else:
                data = None
        else:
            data = None

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
            raw_md = build_raw_markdown(ranked[:max_items], date, language)

        if self._cancel.is_set():
            self.failed.emit("用户退出，生成已取消")
            return
        payload = save_report(date, final_items, raw_md, language, used_ai, errors)
        logger.info("AI 快报完成: date=%s count=%d used_ai=%s", date, len(final_items), used_ai)
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
