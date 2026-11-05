# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 日报 2.0 生成线程

生成流程（B 线）：抓取（失败源自动重试）→ 硬过滤 / 去重（相关来源）→
五因子评分 + 分类配额 + MMR → 可选本地 CLI Agent 结构化摘要（schema 校验 +
修复 1 次 + 逐条降级）→ 落盘 news/<date>.json|md → 通知主线程。

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
from agentfloat.services import llm as llm_service
from agentfloat.services.news.fetcher import (
    DEFAULT_NEWS, NEWS_PROMPT_VERSION, AI_CATEGORIES, fetch_with_retry,
    filter_blocked, prefilter_items, rank_items, guess_category, item_id,
    extractive_summary, build_raw_markdown, save_report, news_storage_dir,
    cleanup_old, score_reasons, ai_cache_key, load_ai_cache, save_ai_cache,
    retry_source_report,
)

logger = logging.getLogger("AgentFloat.News")

NEWS_TIMEOUT_SECONDS = 420  # 生成一整期快报的宽限超时
AI_SUMMARY_TIMEOUT_S = 180  # v3.11.0：AI 摘要单次上限（原来跟随 600s，等待过久）


def _cur_date():
    return time.strftime("%Y-%m-%d")


def is_headless_capable(agent):
    """能否用于 headless 调用（v3.11.0）

    GUI 型（launcher == "app"）与 Web 型（launcher == "web"）都不能当 CLI 跑：
    - app：会启动一个桌面应用实例，超时后被 kill → 用户正在用的程序会被关掉；
    - web：会拉起一个 Web 服务，不适合一次性问答。
    """
    if not agent:
        return False
    if str(agent.get("launcher") or "terminal").lower() in ("app", "web"):
        return False
    return bool((agent.get("command") or "").strip())


def _pick_agent(agents, agent_id):
    """选用于 headless 的 Agent（v3.11.0 修正）

    1) 指定了 agent_id → 仅当它可 headless 时使用；
    2) 否则优先主 Agent（需可 headless）；
    3) 再否则挑第一个可 headless 的 Agent；
    4) 都不行 → None（调用方跳过 AI 摘要，绝不去启动 GUI 程序）。
    """
    agents = [a for a in (agents or []) if a]
    if agent_id:
        for a in agents:
            if a.get("id") == agent_id:
                return a if is_headless_capable(a) else None
    for a in agents:
        if a.get("primary") and is_headless_capable(a):
            return a
    for a in agents:
        if is_headless_capable(a):
            return a
    return None


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


def _ai_ok(result, meta) -> bool:
    """AI 结果是否可用（≥2 条通过校验的条目）。"""
    return bool(result and int((meta or {}).get("valid") or 0) >= 2)


def generate_ai_with_fallback(llm_ready, agent_ready, run_llm, run_agent,
                              emit=None, log=None):
    """按「AI 接入 → 本地 CLI Agent」优先级生成摘要，LLM 失败/输出不足时回退。

    返回 (result, meta, used_ai, channel)，channel ∈ {"llm", "agent", ""}。
    抽成独立函数便于单测：4.0 的回归面就是「LLM 坏了不再回退 Agent」。
    """
    emit = emit or (lambda label="": None)
    log = log or logger
    if llm_ready:
        emit("调用「AI 接入」当前供应商生成摘要…")
        result, meta = run_llm()
        if _ai_ok(result, meta):
            return result, meta, True, "llm"
        errors = list((meta or {}).get("errors") or [])
        if agent_ready:
            why = str(errors[0] if errors else "无有效结果")[:120]
            log.warning("AI 接入不可用（%s），回退本地 CLI Agent", why)
            emit("AI 接入不可用（%s），回退本地 CLI Agent…" % why[:60])
            result2, meta2 = run_agent()
            return result2, meta2, _ai_ok(result2, meta2), "agent"
        return result, meta, False, "llm"
    if agent_ready:
        emit("调用本地 CLI Agent 生成摘要…")
        result, meta = run_agent()
        return result, meta, _ai_ok(result, meta), "agent"
    emit("未找到可用的 AI 通道（CLI Agent / AI 接入供应商），跳过 AI 摘要")
    log.info("AI 摘要跳过：没有可 headless 的 CLI Agent，也没有可用的 AI 接入供应商")
    return None, {"valid": 0, "errors": [], "repaired": False, "cache": False,
                  "translation_coverage": 0.0}, False, ""


def build_ai_prompt(items, language="zh", max_items=6, interests=None, date=""):
    """构造日报摘要提示词（news-v3 固定 JSON schema）"""
    lang_rule = {
        "zh": "title_zh / summary_zh 使用简体中文撰写",
        "en": "Write title_zh / summary_zh in English",
        "both": "title_zh / summary_zh 使用简体中文，同时保留英文原标题（原文已单独提供）",
    }.get(language, "title_zh / summary_zh 使用简体中文撰写")
    lines = []
    limit = max(1, int(max_items)) * 3
    for i, it in enumerate((items or [])[:limit], 1):
        iid = it.get("id") or item_id(it.get("url", ""), it.get("title", ""))
        lines.append(
            "%d. id=%s | [%s] %s | %s | 来源信任 %.2f | 分类 %s"
            % (i, iid, it.get("source", "?"),
               (it.get("title") or "?").replace("\n", " "),
               it.get("url", ""),
               float(it.get("source_trust") or 0.6),
               it.get("category") or "综合"))
    items_text = "\n".join(lines)
    return (
        "你是 AgentFloat 的 AI 日报编辑。prompt_version=%s\n"
        "日期：%s\n"
        "任务：把下面抓取到的 AI 行业资讯精选并改写为今日日报。\n\n"
        "%s"
        "抓取条目（id + 标题 + 来源 + 链接 + 信任度 + 分类）：\n%s\n\n"
        "要求：\n"
        "1. 精选最值得关注的 %d 条，去重、去广告与无关内容；\n"
        "2. %s；\n"
        "3. 每条给出：id（必须原样来自上面列表）、分类、一句话摘要、排序理由与重要性；\n"
        "4. headline：一句话概括今日主题（20 字内）；\n"
        "5. 分类只能是：模型 / 工具 / 论文 / 产品 / 行业 / 综合；\n"
        "6. importance 为 1–5 的整数（5 = 今日最重要）；why 为 40 字内的排序理由；\n"
        "7. 翻译不全时保留原文，不得捏造内容；标题与摘要都要覆盖；\n"
        "8. 只输出一个 JSON 对象（```json 代码块包裹，不要输出其他文字）：\n"
        "{\n"
        "  \"headline\": \"...\",\n"
        "  \"items\": [\n"
        "    {\"id\": \"上面给出的 id\", \"title_zh\": \"标题\", "
        "\"summary_zh\": \"一句话摘要\", \"why\": \"排序理由\", "
        "\"category\": \"模型\", \"importance\": 5}\n"
        "  ]\n"
        "}\n"
        "id 必须存在于输入列表，禁止编造 URL 或条目。"
    ) % (NEWS_PROMPT_VERSION, date or _cur_date(), _interests_block(interests),
         items_text, int(max_items), lang_rule)


def parse_ai_result(text):
    """解析 AI 输出 JSON；失败抛 ValueError"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text or "", re.S | re.I)
    candidate = m.group(1) if m else (text or "")
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(candidate[start:end + 1])


def build_repair_prompt(raw_output, errors):
    """校验失败后的修复提示词（只修复一次，不扩大输入）"""
    rows = "\n".join("- %s" % str(e)[:200] for e in (errors or [])[:12]) or "- 未知错误"
    raw = (raw_output or "")[:6000]
    return (
        "上一次输出未通过 AgentFloat 日报 news-v3 的 JSON 校验。\n"
        "错误：\n%s\n\n"
        "上一次输出：\n%s\n\n"
        "请修复上述错误，只输出修复后的 JSON 对象；不要解释，不要新增输入中不存在的 id。\n"
        "schema：{\"headline\":\"...\",\"items\":[{\"id\":\"...\","
        "\"title_zh\":\"...\",\"summary_zh\":\"...\",\"why\":\"...\","
        "\"category\":\"模型|工具|论文|产品|行业|综合\",\"importance\":1-5}]}"
    ) % (rows, raw)


def validate_ai_payload(payload, source_items, language="zh"):
    """校验 / 逐条降级 AI 输出（纯函数）。

    返回：{headline, items, errors, valid, fallback, translation_coverage}
    - id 不存在 → 丢弃该条；
    - title_zh / summary_zh / why 缺失 → 用原文或抽取式摘要降级并记错误；
    - category 非法 → 回退规则分类；importance 非法 → 3；
    - 有效项 < 2 → fallback=True（调用方走全量抽取式降级）。
    """
    errors = []
    source_map = {}
    for it in source_items or []:
        iid = str(it.get("id") or item_id(it.get("url", ""), it.get("title", "")))
        source_map[iid] = it
    if not isinstance(payload, dict):
        return {"headline": "", "items": [], "errors": ["输出不是 JSON 对象"],
                "valid": 0, "fallback": True, "translation_coverage": 0.0}
    headline = payload.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        headline = ""
        errors.append("缺少 headline")
    else:
        headline = headline.strip()
        if len(headline) > 60:
            headline = headline[:60]
            errors.append("headline 超过 60 字，已截断")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        errors.append("items 不是数组")
        raw_items = []
    clean, seen = [], set()
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            errors.append("第 %d 条不是对象，已丢弃" % (idx + 1))
            continue
        iid = str(raw.get("id") or "").strip()
        if not iid or iid not in source_map:
            errors.append("第 %d 条 id 不存在，已丢弃：%s" % (idx + 1, iid or "（空）"))
            continue
        if iid in seen:
            errors.append("第 %d 条 id 重复，已丢弃：%s" % (idx + 1, iid))
            continue
        seen.add(iid)
        src = source_map[iid]
        degraded = False
        title_raw = raw.get("title_zh")
        title_ok = isinstance(title_raw, str) and bool(title_raw.strip())
        title = (title_raw or "").strip() if title_ok else (src.get("title") or "").strip()
        if len(title) > 200:
            title = title[:200]
            errors.append("第 %d 条标题超过 200 字，已截断" % (idx + 1))
            degraded = True
        if not title_ok:
            errors.append("第 %d 条缺少 title_zh，已回退原文" % (idx + 1))
            degraded = True
        summary_raw = raw.get("summary_zh")
        summary_ok = isinstance(summary_raw, str) and bool(summary_raw.strip())
        summary = (summary_raw or "").strip() if summary_ok else extractive_summary(src, 120)
        if len(summary) > 240:
            summary = summary[:240]
            errors.append("第 %d 条摘要超过 240 字，已截断" % (idx + 1))
            degraded = True
        if not summary_ok:
            errors.append("第 %d 条缺少 summary_zh，已降级抽取式摘要" % (idx + 1))
            degraded = True
        why = raw.get("why")
        why_ok = isinstance(why, str) and bool(why.strip())
        why = why.strip() if why_ok else ""
        if len(why) > 120:
            why = why[:120]
            errors.append("第 %d 条 why 超过 120 字，已截断" % (idx + 1))
            degraded = True
        if not why_ok:
            errors.append("第 %d 条缺少 why" % (idx + 1))
            degraded = True
        category = str(raw.get("category") or "").strip()
        if category not in AI_CATEGORIES:
            category = guess_category(src.get("title", ""), src.get("url", ""))
            errors.append("第 %d 条分类非法，已回退 %s" % (idx + 1, category))
            degraded = True
        importance_raw = raw.get("importance")
        try:
            importance = int(importance_raw)
        except (TypeError, ValueError):
            importance = 0
        if importance < 1 or importance > 5:
            importance = 3
            errors.append("第 %d 条 importance 非法，已回退 3" % (idx + 1))
            degraded = True
        translated = bool(title_ok and summary_ok)
        clean.append({
            "id": iid,
            "title": title,
            "title_original": src.get("title") or "",
            "summary": summary,
            "category": category,
            "importance": importance,
            "why": why,
            "translated": translated,
            "degraded": degraded,
        })
    coverage = round(sum(1 for it in clean if it.get("translated")) / len(clean), 3) if clean else 0.0
    return {
        "headline": headline,
        "items": clean,
        "errors": errors,
        "valid": len(clean),
        "fallback": len(clean) < 2,
        "translation_coverage": coverage,
    }


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
        if it.get("why"):
            lines.append("> 为什么：%s" % it["why"])
        if url and url != "#":
            lines.append("来源：[%s](%s)" % (url.split("//")[-1].split("/")[0], url))
        lines.append("")
    return "\n".join(lines)


class NewsWorker(QThread):
    """日报生成线程（B 线 2.0）：阶段化进度 → 抓取 → 评分 → AI 摘要 → 落盘

    - progress(phase, done, total, label)：阶段化进度（抓取逐源 / 评分 / AI / 保存）
    - 可取消：每个阶段与每源之间检查 cancel，取消后不落盘
    - 失败源：自动重试 1 次 + 逐源健康状态（ok / degraded / failed）
    - AI：news-v3 契约、schema 校验、修复 1 次、逐条降级、缓存（含 prompt_version）
    """
    done = pyqtSignal(dict)                          # save_report 的 payload
    failed = pyqtSignal(str)
    progress = pyqtSignal(str, int, int, str)        # phase, done, total, label

    PHASES = {
        "fetch": "抓取数据源",
        "dedupe": "过滤、去重与评分",
        "ai": "AI 摘要",
        "save": "写入快报",
    }

    def __init__(self, news_cfg, agents, parent=None, llm_cfg=None):
        super().__init__(parent)
        cfg = dict(DEFAULT_NEWS)
        cfg.update(news_cfg or {})
        self._cfg = cfg
        self._agents = agents or []
        self._llm_cfg = dict(llm_cfg or {})
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
        started = time.time()
        now = int(started)
        enabled = cfg.get("sources") or DEFAULT_NEWS["sources"]
        max_items = max(1, min(20, int(cfg.get("max_items") or 6)))
        per_source = max(3, min(30, int(cfg.get("per_source") or 12)))
        ai_max = max(1, min(20, int(cfg.get("ai_max_items") or 6)))
        blocked = cfg.get("blocked_keywords") or []
        language = cfg.get("language") or "zh"
        interests = cfg.get("interests") or []
        try:
            category_cap = max(1, int(cfg.get("category_cap") or 3))
        except (TypeError, ValueError):
            category_cap = 3
        try:
            mmr_lambda = float(cfg.get("mmr_lambda") or 0.7)
        except (TypeError, ValueError):
            mmr_lambda = 0.7
        date = _cur_date()

        logger.info("AI 日报开始生成: date=%s sources=%s max=%d per=%d",
                    date, enabled, max_items, per_source)

        self._emit("fetch", 0, len(enabled), "准备抓取 %d 个源" % len(enabled))
        retries = 1 if cfg.get("retry_failed_sources", True) else 0
        items, errors, sources = fetch_with_retry(
            enabled, per_source=per_source, progress=lambda done, total, label:
            self._emit("fetch", done, total, label), retries=retries)
        if self._cancel.is_set():
            self.failed.emit("已取消生成")
            return
        if not items:
            self.failed.emit("所有数据源抓取失败：\n%s" % ("\n".join(errors[:5]) or "无数据"))
            return

        self._emit("dedupe", 0, 0, "硬过滤（原始 %d 条）" % len(items))
        raw_count = len(items)
        items = filter_blocked(items, blocked)
        blocked_count = raw_count - len(items)
        try:
            max_age_days = max(1, int(cfg.get("max_age_days") or 7))
        except (TypeError, ValueError):
            max_age_days = 7
        filtered, fstats = prefilter_items(items, [], now=now,
                                           max_age_days=max_age_days, min_trust=0.5)
        fstats["raw"] = raw_count
        fstats["blocked"] = int(fstats.get("blocked") or 0) + blocked_count
        fstats["filtered"] = int(fstats.get("filtered") or 0) + blocked_count
        if not filtered:
            self.failed.emit("抓取到 %d 条，但均未通过过滤（屏蔽词 / 时效 / 重复 / 低信任）"
                             % raw_count)
            return
        self._emit("dedupe", 0, len(filtered),
                   "五因子评分 + 多样性排序（%d 条）" % len(filtered))
        candidate_limit = min(60, max(max_items, ai_max) * 3)
        ranked = rank_items(filtered, max_items=candidate_limit, interests=interests,
                            now=now, category_cap=category_cap, mmr_lambda=mmr_lambda)
        if not ranked:
            self.failed.emit("评分排序后没有可用条目")
            return
        if self._cancel.is_set():
            self.failed.emit("已取消生成")
            return

        used_ai = False
        ai_result = None
        ai_channel = ""
        ai_meta = {"valid": 0, "errors": [], "repaired": False, "cache": False,
                   "translation_coverage": 0.0}
        if cfg.get("use_ai", True):
            llm_ready = llm_service.has_active_provider({"llm": self._llm_cfg})
            agent = _pick_agent(self._agents, cfg.get("agent_id"))
            agent_ready = bool(agent and build_headless_command(agent, "ping")[0] is not None)
            ai_result, ai_meta, used_ai, ai_channel = generate_ai_with_fallback(
                llm_ready, agent_ready,
                lambda: self._generate_ai_llm(ranked, date, language, ai_max, interests),
                lambda: self._generate_ai(agent, ranked, date, language, ai_max, interests),
                emit=lambda label: self._emit("ai", 0, 0, label))
            if self._cancel.is_set():
                self.failed.emit("已取消生成")
                return
        else:
            self._emit("ai", 0, 0, "已关闭 AI 摘要，使用标题列表")

        if used_ai and ai_result:
            final_items = self._apply_ai_result(ai_result, ranked)
            headline = (ai_result.get("headline") or "").strip()
            raw_md = _render_ai_markdown({"items": final_items, "headline": headline},
                                         date, language)
        else:
            final_items = [self._fallback_item(it) for it in ranked[:max_items]]
            headline = ""
            raw_md = build_raw_markdown(final_items, date, language)

        if self._cancel.is_set():
            self.failed.emit("已取消生成")
            return

        self._emit("save", 0, 0, "写入日报（%d 条）" % len(final_items))
        scores = [float(it.get("score") or 0) for it in final_items]
        src_ok = sum(1 for s in sources if s.get("ok"))
        duplicate = int(fstats.get("duplicate") or 0) + int(fstats.get("similar") or 0)
        quality = {
            "raw": raw_count,
            "kept": len(filtered),
            "filtered": int(fstats.get("filtered") or 0),
            "empty": int(fstats.get("empty") or 0),
            "blocked": int(fstats.get("blocked") or 0),
            "stale": int(fstats.get("stale") or 0),
            "low_trust": int(fstats.get("low_trust") or 0),
            "duplicate": int(fstats.get("duplicate") or 0),
            "similar": int(fstats.get("similar") or 0),
            "related": int(fstats.get("related") or 0),
            "source_ok": src_ok,
            "source_total": len(sources),
            "source_success_rate": round(src_ok / len(sources), 3) if sources else 0.0,
            "duplicate_rate": round(duplicate / max(1, raw_count), 3),
            "ai_valid": int(ai_meta.get("valid") or 0),
            "ai_valid_rate": round(min(1.0, int(ai_meta.get("valid") or 0) / max(1, ai_max)), 3),
            "ai_repaired": bool(ai_meta.get("repaired")),
            "ai_cache": bool(ai_meta.get("cache")),
            "fallback": not used_ai,
            "translation_coverage": round(float(ai_meta.get("translation_coverage") or 0.0), 3),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "auto_retried_sources": sum(1 for s in sources if s.get("retried")),
            "duration_ms": int((time.time() - started) * 1000),
        }
        stats = {
            "raw": raw_count,
            "blocked": int(fstats.get("blocked") or 0),
            "deduped": len(filtered),
            "ranked": len(ranked),
            "shown": len(final_items),
            "ai_max": ai_max,
            "ai_valid": int(ai_meta.get("valid") or 0),
            "ai_repaired": bool(ai_meta.get("repaired")),
            "ai_cache": bool(ai_meta.get("cache")),
            "fallback": not used_ai,
            "avg_score": quality["avg_score"],
            "translation_coverage": quality["translation_coverage"],
        }
        source_bad = any(not s.get("ok") for s in sources)
        ai_missing = bool(cfg.get("use_ai", True)) and not used_ai
        batch = {
            "id": "%s-%s" % (date, time.strftime("%H%M%S", time.localtime(started))),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": int((time.time() - started) * 1000),
            "status": "partial" if (source_bad or ai_missing) else "ok",
            "retries": [
                {"source_id": s.get("id"), "source": s.get("name") or s.get("id"),
                 "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
                 "added": 0, "duplicates": 0, "quota_skipped": 0,
                 "auto": True, "ok": bool(s.get("ok")), "error": s.get("error") or ""}
                for s in sources if s.get("retried")
            ],
        }
        payload = save_report(date, final_items, raw_md, language, used_ai, errors,
                              sources=sources, stats=stats, headline=headline,
                              quality=quality, batch=batch,
                              prompt_version=NEWS_PROMPT_VERSION)
        try:
            cleanup_old(cfg.get("retention_days", 14))
        except Exception as e:  # noqa: BLE001
            logger.warning("清理历史快报失败: %s", e)
        logger.info("AI 日报完成: date=%s count=%d used_ai=%s channel=%s blocked=%d "
                    "duplicate=%d fallback=%s",
                    date, len(final_items), used_ai, ai_channel or "-", blocked_count,
                    duplicate, not used_ai)
        self.done.emit(payload)

    def _generate_ai(self, agent, ranked, date, language, ai_max, interests):
        """调用 CLI Agent 生成摘要；缓存 → 校验 → 修复 1 次 → 逐条降级"""
        def invoke(prompt, timeout):
            return run_headless(agent, prompt, cancel=self._cancel, timeout=timeout)
        return self._generate_ai_core(ranked, date, language, ai_max, interests,
                                      invoke, agent.get("name") or "本地 Agent")

    def _generate_ai_llm(self, ranked, date, language, ai_max, interests):
        """通过「AI 接入」当前供应商生成摘要（purpose=news）。"""
        llm_config = {"llm": self._llm_cfg}

        def invoke(prompt, timeout):
            try:
                result = llm_service.chat(
                    llm_config,
                    [{"role": "user", "content": prompt}],
                    purpose="news", timeout=timeout)
                return result.get("content") or "", None
            except llm_service.LLMError as exc:
                return None, str(exc)
            except Exception as exc:  # noqa: BLE001
                return None, "AI 接入调用异常：%s" % exc

        return self._generate_ai_core(ranked, date, language, ai_max, interests,
                                      invoke, "AI 接入")

    def _generate_ai_core(self, ranked, date, language, ai_max, interests,
                          invoke, source_label):
        cache_key = ai_cache_key(date, language, interests, ranked)
        cached = load_ai_cache(cache_key)
        if cached:
            result = validate_ai_payload(cached, ranked, language)
            if result.get("valid", 0) >= 2:
                result["cache"] = True
                result["repaired"] = False
                self._emit("ai", 2, 2, "命中摘要缓存（%d 条）" % result["valid"])
                logger.info("AI 摘要命中缓存: %s", cache_key)
                return result, {
                    "valid": result["valid"],
                    "errors": result.get("errors") or [],
                    "repaired": False,
                    "cache": True,
                    "translation_coverage": result.get("translation_coverage", 0.0),
                }
        prompt = build_ai_prompt(ranked, language, ai_max, interests, date=date)
        self._emit("ai", 0, 2, "调用 %s 生成摘要…" % source_label)
        out, err = invoke(prompt, AI_SUMMARY_TIMEOUT_S)
        if out is None:
            logger.warning("AI 摘要失败: %s", err)
            self._emit("ai", 0, 2, "AI 摘要失败：%s" % (err or "无输出"))
            return None, {"valid": 0, "errors": [err or "无输出"], "repaired": False,
                          "cache": False, "translation_coverage": 0.0}
        result, errors = self._parse_and_validate(out, ranked, language)
        repaired = False
        if result is None or errors:
            self._emit("ai", 1, 2, "校验未通过，自动修复 1 次…")
            repaired = True
            prompt2 = build_repair_prompt(out, errors)
            out2, err2 = invoke(prompt2, AI_SUMMARY_TIMEOUT_S)
            if out2:
                result2, errors2 = self._parse_and_validate(out2, ranked, language)
                if result2 is not None and (
                        result is None or result2["valid"] >= result["valid"]):
                    result, errors = result2, errors2
            else:
                logger.warning("AI 修复调用失败: %s", err2)
        valid = int((result or {}).get("valid") or 0)
        if result and valid >= 2:
            self._emit("ai", 2, 2, "校验通过（%d 条）" % valid)
            save_ai_cache(cache_key, {
                "headline": result.get("headline") or "",
                "items": result.get("items") or [],
            }, meta={"date": date, "language": language})
        else:
            self._emit("ai", 2, 2, "AI 输出不足 2 条有效项，回退抽取式摘要")
        return result, {
            "valid": valid,
            "errors": (result or {}).get("errors") or errors,
            "repaired": repaired,
            "cache": bool((result or {}).get("cache")),
            "translation_coverage": float((result or {}).get("translation_coverage") or 0.0),
        }

    @staticmethod
    def _parse_and_validate(text, ranked, language):
        try:
            payload = parse_ai_result(text)
        except Exception as e:  # noqa: BLE001
            return None, [str(e)]
        result = validate_ai_payload(payload, ranked, language)
        return result, list(result.get("errors") or [])

    @staticmethod
    def _apply_ai_result(ai_result, ranked):
        """把校验后的 AI 条目映射回原始条目（保留 URL / 来源 / 相关来源）"""
        source_map = {str(it.get("id") or item_id(it.get("url", ""), it.get("title", ""))): it
                      for it in ranked}
        out = []
        for raw in ai_result.get("items") or []:
            src = source_map.get(raw.get("id"))
            if src is None:
                continue
            row = dict(src)
            row["title_original"] = src.get("title") or ""
            row["title"] = raw.get("title") or src.get("title") or ""
            row["summary"] = raw.get("summary") or extractive_summary(src)
            row["category"] = raw.get("category") or src.get("category") or "综合"
            row["importance"] = int(raw.get("importance") or 3)
            row["ai_why"] = raw.get("why") or ""
            row["translated"] = bool(raw.get("translated"))
            row["degraded"] = bool(raw.get("degraded"))
            factors = dict(src.get("factors") or {})
            factors["importance"] = round(row["importance"] * 5.0, 1)
            base = sum(v for k, v in factors.items() if k != "diversity")
            row["score"] = round(min(100.0, base + float(factors.get("diversity") or 0.0)), 1)
            reasons = []
            if raw.get("why"):
                reasons.append(raw["why"])
            for reason in src.get("reasons") or []:
                if reason not in reasons:
                    reasons.append(reason)
            if len(reasons) < 2:
                reasons = score_reasons(row, factors)
            row["reasons"] = reasons[:3]
            row["why"] = "；".join(row["reasons"])
            row["factors"] = factors
            out.append(row)
        return out

    @staticmethod
    def _fallback_item(row):
        """AI 不可用 / 输出不足时的逐条抽取式降级。

        translated=None 表示「本次未尝试翻译」（纯标题列表 / AI 关闭），
        与 AI 返回里缺少译文时的 translated=False 区分开。
        """
        item = dict(row)
        item["summary"] = extractive_summary(row)
        item["translated"] = None
        item["degraded"] = False
        item.setdefault("title_original", row.get("title") or "")
        item.setdefault("importance", 3)
        return item


class NewsRetryWorker(QThread):
    """单源重试线程（Qt 快报窗源健康条使用，网络操作不阻塞 GUI）"""

    done = pyqtSignal(dict)

    def __init__(self, source_id, news_cfg, parent=None):
        super().__init__(parent)
        self._source_id = str(source_id or "")
        self._cfg = dict(news_cfg or {})

    def run(self):
        try:
            per = max(3, min(30, int(self._cfg.get("per_source") or 12)))
            result = retry_source_report(self._source_id, per_source=per, cfg=self._cfg)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "added": 0, "error": str(e)[:200]}
        self.done.emit(result)


def _boost_by_interests(items, interests):
    """纯列表模式（兼容旧调用）：命中关注主题关键词的条目按权重提前"""
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
    for host, src in (
            ("news.ycombinator.com", "Hacker News"), ("github.com", "GitHub"),
            ("sspai.com", "少数派"), ("qbitai.com", "量子位"),
            ("arxiv.org", "arXiv AI"), ("openai.com", "OpenAI News"),
            ("anthropic.com", "Anthropic News"), ("deepmind.google", "Google DeepMind Blog"),
            ("jiqizhixin.com", "机器之心"), ("infoq.cn", "InfoQ AI"),
            ("huggingface.co", "Hugging Face Papers"),
            ("reddit.com", "Reddit r/LocalLLaMA"),
            ("producthunt.com", "Product Hunt"), ("qwenlm.github.io", "Qwen Blog"),
            ("deepseek.com", "DeepSeek News")):
        if host in u:
            return src
    return ""


def today_news_exists():
    """当日快报是否已生成（用于启动补生成与每日定时防重）"""
    p = os.path.join(news_storage_dir(), "%s.json" % _cur_date())
    return os.path.exists(p)
