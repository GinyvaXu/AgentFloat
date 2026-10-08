# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 快报数据源抓取

多源聚合 → 过滤去重 → 生成结构化条目（纯标准库 + urllib，超时与失败降级）。

架构参考致谢（详见 README「致谢」与 docs/AI快报与多功能浮窗助手调研报告.md）：
- TrendRadar / agents-radar：多源 RSS 聚合 + 分类 + 单一时区计划表
- horizonnews / dailybrief：双语生成 + 主题聚类
- ai-daily-skill：一句话摘要 + 分类的轻量快报格式

数据源为可插拔注册表：新增源只需在 SOURCES 中注册 fetch 函数，
返回 [{"title","url","source","ts"} ...]；单个源失败不影响整体。
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from agentfloat.core.paths import config_dir as _app_config_dir

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 AgentFloat/1.2")

# 默认配置（load_config 引用；用户可在「设置 → AI 快报」修改）
DEFAULT_NEWS = {
    "enabled": False,
    "language": "zh",            # zh / en / both
    "schedule_mode": "daily_startup",  # off / daily / startup / daily_startup
    "schedule_time": "09:00",
    "max_items": 6,
    "panel_width": 860,          # 快报窗口宽度
    "panel_height": 680,         # 快报窗口高度
    "font_size": 13,             # 快报正文字号 (px)
    "density": "comfortable",    # v3.9.0 阅读密度：comfortable / compact
    "use_ai": True,              # False = 纯标题列表（不调用本地 Agent）
    "agent_id": "",              # 空 = 默认主 Agent
    "sources": ["hackernews", "github_trending", "sspai", "qbitai"],
    "per_source": 12,            # v3.9.0 每源抓取条数
    "ai_max_items": 6,           # v3.9.0 送 AI 摘要的条数上限
    "blocked_keywords": [],      # v3.9.0 屏蔽关键词（标题命中即丢弃）
    "retention_days": 14,        # v3.9.0 历史保留天数
    "notify": True,
    "auto_show_panel": True,
    "unread_count": 0,
    "last_generated": "",
    "interests": [],   # [{"label": "新模型发布", "weight": 3, "color": "#5B8DEF"}]
}


def news_storage_dir():
    """快报数据目录：打包后存 %APPDATA%/AgentFloat/news/，开发时存脚本目录/news/"""
    d = os.path.join(_app_config_dir(), "news")
    os.makedirs(d, exist_ok=True)
    return d


# ── HTTP 工具 ──────────────────────────────────────
def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _http_json(url, timeout=20):
    return json.loads(_http_get(url, timeout))


# ── 各数据源抓取 ───────────────────────────────────
def _fetch_hackernews(limit=12):
    """Hacker News 官方 Firebase API：topstories + 条目详情"""
    ids = _http_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:40]
    out = []
    for sid in ids[:limit]:
        try:
            it = _http_json("https://hacker-news.firebaseio.com/v0/item/%s.json" % sid)
        except Exception:
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        url = (it.get("url") or "").strip() or "https://news.ycombinator.com/item?id=%s" % sid
        out.append({
            "title": title,
            "url": url,
            "source": "Hacker News",
            "ts": int(it.get("time") or time.time()),
            "extra": "▲ %s" % (it.get("score") or 0),
        })
        if len(out) >= limit:
            break
    return out


def _fetch_github_trending(limit=12):
    """GitHub Trending（HTML 解析，正则提取仓库与描述）"""
    html = _http_get("https://github.com/trending?since=daily")
    # 仓库链接形如 <h2 class="h3 lh-condensed"><a href="/owner/repo">
    repos = re.findall(r'href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', html)
    seen, out = set(), []
    for rep in repos:
        if rep in seen:
            continue
        seen.add(rep)
        out.append({
            "title": rep,
            "url": "https://github.com/%s" % rep,
            "source": "GitHub Trending",
            "ts": int(time.time()),
            "extra": "⭐ trending",
        })
        if len(out) >= limit:
            break
    return out


def _fetch_rss(url, source, limit=12):
    """通用 RSS 2.0 / Atom 抓取"""
    text = _http_get(url)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # 部分源返回 XML 声明前有 BOM/空白，去掉后重试
        text = text.lstrip("\ufeff \t\r\n")
        root = ET.fromstring(text)
    items = []
    # RSS: channel/item；Atom: feed/entry
    for node in (root.iter("item") if root.tag.endswith("rss") else root.iter("entry")):
        title = ""
        link = ""
        pub = None
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "title":
                title = (child.text or "").strip()
            elif tag == "link":
                link = (child.text or "").strip() or child.get("href", "").strip()
            elif tag in ("pubDate", "published", "updated"):
                pub = (child.text or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source,
            "ts": _parse_rss_time(pub),
            "extra": "",
        })
        if len(items) >= limit:
            break
    return items


def _parse_rss_time(text):
    """RSS 时间解析（尽力而为，失败返回当前时间）"""
    if not text:
        return int(time.time())
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            import datetime
            dt = datetime.datetime.strptime(text.strip(), fmt)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            continue
    return int(time.time())


def _fetch_sspai(limit=12):
    """少数派 RSS：https://sspai.com/feed"""
    return _fetch_rss("https://sspai.com/feed", "少数派", limit)


def _fetch_qbitai(limit=12):
    """量子位 RSS：https://www.qbitai.com/feed"""
    return _fetch_rss("https://www.qbitai.com/feed", "量子位", limit)


def _fetch_arxiv_ai(limit=12):
    """arXiv cs.AI 最新论文（Atom API）"""
    url = ("http://export.arxiv.org/api/query?search_query=cat:cs.AI"
           "&sortBy=submittedDate&sortOrder=descending&max_results=%d" % limit)
    text = _http_get(url, timeout=30)
    root = ET.fromstring(text.lstrip("\ufeff \t\r\n"))
    out = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("a:entry", ns):
        title = "".join(entry.findtext("a:title", "", ns)).strip().replace("\n", " ")
        link_el = entry.find("a:link", ns)
        link = (link_el.get("href") if link_el is not None else "") or ""
        published = entry.findtext("a:published", "", ns)
        out.append({
            "title": title,
            "url": link,
            "source": "arXiv AI",
            "ts": _parse_rss_time(published),
            "extra": "论文",
        })
    return out


# 可插拔源注册表
SOURCES = [
    {"id": "hackernews",     "name": "Hacker News",   "zh": "Hacker News",   "fetch": _fetch_hackernews},
    {"id": "github_trending","name": "GitHub Trending","zh": "GitHub 趋势",  "fetch": _fetch_github_trending},
    {"id": "sspai",          "name": "少数派",         "zh": "少数派",        "fetch": _fetch_sspai},
    {"id": "qbitai",         "name": "量子位",         "zh": "量子位",        "fetch": _fetch_qbitai},
    {"id": "arxiv_ai",       "name": "arXiv AI",      "zh": "arXiv AI",     "fetch": _fetch_arxiv_ai},
]
SOURCE_MAP = {s["id"]: s for s in SOURCES}


def fetch_all_stats(enabled_ids, per_source=12, timeout=15, progress=None):
    """并发抓取启用源（v3.9.0 增强版）。

    返回 ``(items, errors, sources)``：
    - items: 原始条目列表
    - errors: 供 UI 展示的「源名：原因」字符串列表（保持旧行为）
    - sources: 结构化的每源结果 [{id,name,ok,count,error}]，供失败源单源重试

    progress(done, total, label) 每完成一个源回调一次（用于阶段化进度）。
    """
    enabled = [SOURCE_MAP[i] for i in enabled_ids if i in SOURCE_MAP]
    items, errors, stats = [], [], []
    if not enabled:
        return items, errors, stats
    total = len(enabled)
    done = 0
    pool = ThreadPoolExecutor(max_workers=max(2, len(enabled)))
    futures = {pool.submit(s["fetch"], per_source): s for s in enabled}
    pending = set(futures)
    try:
        for fut in as_completed(futures, timeout=timeout + 5):
            pending.discard(fut)
            s = futures[fut]
            try:
                got = fut.result() or []
                items.extend(got)
                stats.append({"id": s["id"], "name": s["zh"], "ok": True,
                              "count": len(got), "error": ""})
            except Exception as e:
                msg = _brief_err(e)
                errors.append("%s：%s" % (s["name"], msg))
                stats.append({"id": s["id"], "name": s["zh"], "ok": False,
                              "count": 0, "error": msg})
            done += 1
            if progress:
                try:
                    progress(done, total, s["zh"])
                except Exception:  # noqa: BLE001
                    pass
    except TimeoutError:
        for fut in list(pending):
            fut.cancel()
            s = futures[fut]
            errors.append("%s：超时未完成" % s["name"])
            stats.append({"id": s["id"], "name": s["zh"], "ok": False,
                          "count": 0, "error": "超时未完成"})
            done += 1
            if progress:
                try:
                    progress(done, total, s["zh"])
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
    return items, errors, stats


def fetch_all(enabled_ids, per_source=12, timeout=15):
    """并发抓取启用源；返回 (items, errors)。

    单个源超时不中断整体：as_completed 到点抛 TimeoutError 时，
    取消剩余任务并记为错误，已抓到的部分结果照常返回。
    """
    items, errors, _stats = fetch_all_stats(enabled_ids, per_source, timeout)
    return items, errors


def fetch_one(source_id, per_source=12, timeout=15):
    """单源重试：返回 (items, error_str)。未知 id 返回空与原因。"""
    src = SOURCE_MAP.get(source_id)
    if src is None:
        return [], "未知数据源：%s" % source_id
    try:
        return (src["fetch"](per_source) or []), ""
    except Exception as e:  # noqa: BLE001
        return [], _brief_err(e)


def filter_blocked(items, keywords):
    """按屏蔽关键词过滤（标题 + 摘要 + 来源，大小写不敏感）"""
    words = [str(w).strip().lower() for w in (keywords or []) if str(w).strip()]
    if not words:
        return list(items or [])
    out = []
    for it in items or []:
        text = " ".join([str(it.get("title", "")), str(it.get("summary", "")),
                         str(it.get("source", ""))]).lower()
        if any(w in text for w in words):
            continue
        out.append(it)
    return out


def item_id(url="", title=""):
    """条目稳定 id（同一链接跨次生成保持同一 id → 已读/收藏可延续）"""
    import hashlib
    key = _norm_url(url) or (title or "").strip()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _brief_err(e):
    return str(e)[:120]


# ── 去重与分类 ─────────────────────────────────────
def _norm_url(url):
    u = (url or "").strip().lower()
    for p in ("https://", "http://", "www."):
        u = u.replace(p, "")
    return u.rstrip("/")


def dedupe(items, max_total):
    """按归一化 URL 去重，保留先抓到的条目，再按时间倒序截断"""
    seen, out = set(), []
    for it in items:
        key = _norm_url(it.get("url")) or it.get("title", "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out[:max_total]


_CATEGORY_KEYWORDS = {
    "模型": ["llm", "gpt", "claude", "gemini", "deepseek", "qwen", "model", "推理", "diffusion",
             "文生", "多模态", "vllm", "ollama", "权重", "开源模型"],
    "工具": ["工具", "cli", "sdk", "api", "框架", "库", "开源", "github", "插件", "app",
             "release", "v0.", "代码", "agent"],
    "论文": ["论文", "arxiv", "research", "paper", "研究", "benchmark", "评测"],
    "产品": ["发布", "上线", "产品", "体验", "实测", "更新", "升级", "app store", "新品"],
    "行业": ["融资", "收购", "监管", "政策", "公司", "财报", "裁员", "合作", "亿元", "美元"],
}


def guess_category(title, url=""):
    text = ("%s %s" % (title or "", url or "")).lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text:
                return cat
    return "综合"


# ── 落盘 ───────────────────────────────────────────
def build_raw_markdown(items, date, language="zh"):
    """纯列表模式 / AI 失败兜底：标题 + 来源链接"""
    head = "今日 AI 速览（%s）" % date if language != "en" else "AI Daily Brief (%s)" % date
    lines = [head, ""]
    for i, it in enumerate(items, 1):
        lines.append("%d. [%s](%s) — %s" % (i, it.get("title", "?"),
                                            it.get("url", "#"), it.get("source", "")))
    return "\n".join(lines)


def load_latest():
    """读取最新一期结构化数据；无则返回 None"""
    p = os.path.join(news_storage_dir(), "latest.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def list_archives():
    """按日期倒序列出历史快报 [(date, item_count), ...]"""
    d = news_storage_dir()
    out = []
    try:
        for name in os.listdir(d):
            if not name.endswith(".json") or name == "latest.json":
                continue
            p = os.path.join(d, name)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                out.append((name[:-5], len(data.get("items") or [])))
            except (IOError, json.JSONDecodeError):
                continue
    except OSError:
        pass
    out.sort(reverse=True)
    return out


def load_archive(date):
    """读取指定日期的快报数据"""
    p = os.path.join(news_storage_dir(), "%s.json" % date)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def save_report(date, items, raw_md, language, used_ai, source_errors,
                sources=None, stats=None, headline="", summary=""):
    """写入 news/<date>.json + news/<date>.md + news/latest.json，返回 latest 数据。

    v3.9.0：报告结构升级（version=2）——条目带 id/category/read/starred，
    并记录每源结果与统计，供阅读器、失败源重试与状态展示使用。
    旧字段（count/items/raw_md/source_errors）保持不变以兼容既有调用。
    """
    d = news_storage_dir()
    enriched = []
    for it in items or []:
        row = dict(it)
        row.setdefault("id", item_id(row.get("url", ""), row.get("title", "")))
        row.setdefault("category", guess_category(row.get("title", ""), row.get("url", "")))
        row.setdefault("read", False)
        row.setdefault("starred", False)
        row.setdefault("summary", "")
        enriched.append(row)
    payload = {
        "version": 2,
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "language": language,
        "used_ai": used_ai,
        "source_errors": list(source_errors or []),
        "sources": list(sources or []),
        "stats": dict(stats or {}),
        "headline": headline or "%s AI 速览" % date,
        "summary": summary or "",
        "count": len(enriched),
        "items": enriched,
        "raw_md": raw_md,
    }
    with open(os.path.join(d, "%s.json" % date), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "%s.md" % date), "w", encoding="utf-8") as f:
        f.write(raw_md)
    with open(os.path.join(d, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


# ── 已读 / 收藏状态（跨次生成延续）────────────────
def _state_path():
    return os.path.join(news_storage_dir(), "news_state.json")


def load_state():
    """读取 {read:{id:ts}, starred:[id]}；损坏时返回空状态"""
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"read": {}, "starred": []}
        return {"read": dict(data.get("read") or {}),
                "starred": list(data.get("starred") or [])}
    except (IOError, json.JSONDecodeError):
        return {"read": {}, "starred": []}


def save_state(state):
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def mark_read(iid, flag=True):
    """标记已读/未读；返回更新后的状态"""
    st = load_state()
    if flag:
        st["read"][iid] = int(time.time())
    else:
        st["read"].pop(iid, None)
    save_state(st)
    return st


def mark_all_read(report=None):
    """把某期（默认最新）所有条目标为已读"""
    st = load_state()
    for it in ((report or load_latest()) or {}).get("items") or []:
        st["read"][it.get("id") or item_id(it.get("url", ""), it.get("title", ""))] = int(time.time())
    save_state(st)
    return st


def toggle_star(iid):
    """收藏/取消收藏；返回 (状态, 是否已收藏)"""
    st = load_state()
    if iid in st["starred"]:
        st["starred"].remove(iid)
        starred = False
    else:
        st["starred"].append(iid)
        starred = True
    save_state(st)
    return st, starred


def apply_state(report, state=None):
    """把已读/收藏状态套用到报告条目上（返回同一 dict，便于链式调用）"""
    if not isinstance(report, dict):
        return report
    st = state or load_state()
    read = st.get("read") or {}
    starred = set(st.get("starred") or [])
    for it in report.get("items") or []:
        iid = it.get("id") or item_id(it.get("url", ""), it.get("title", ""))
        it["id"] = iid
        it["read"] = iid in read
        it["starred"] = iid in starred
    report["unread"] = sum(1 for it in (report.get("items") or []) if not it.get("read"))
    return report


def cleanup_old(days=14):
    """清理超过 N 天的历史快报（<date>.json / <date>.md）；返回删除数量"""
    import datetime
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 14
    if days <= 0:
        return 0
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    removed = 0
    for name in list(os.listdir(news_storage_dir())):
        if name == "latest.json" or not (name.endswith(".json") or name.endswith(".md")):
            continue
        date = os.path.splitext(name)[0]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or date >= cutoff:
            continue
        try:
            os.remove(os.path.join(news_storage_dir(), name))
            removed += 1
        except OSError:
            pass
    return removed


def export_markdown(date=None):
    """导出某期快报为 Markdown（写入数据目录），返回 (路径, 错误)"""
    d = news_storage_dir()
    if date:
        src = os.path.join(d, "%s.md" % date)
        name = "AI快报_%s.md" % date
    else:
        src = os.path.join(d, "latest.md")
        name = "AI快报_最新.md"
    try:
        text = open(src, "r", encoding="utf-8").read() if os.path.isfile(src) else ""
    except IOError as e:
        return "", str(e)
    if not text:
        report = load_archive(date) if date else load_latest()
        if not report:
            return "", "该日期没有快报数据"
        text = build_export_markdown(report)
    out = os.path.join(d, name)
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    except IOError as e:
        return "", str(e)
    return out, ""


def build_export_markdown(report):
    """把报告（v1/v2 均可）导出为带分类与链接的 Markdown"""
    rep = report or {}
    lines = ["# %s" % (rep.get("headline") or ("AI 速览 %s" % rep.get("date", ""))), ""]
    if rep.get("summary"):
        lines += [rep["summary"], ""]
    by_cat = {}
    for it in rep.get("items") or []:
        by_cat.setdefault(it.get("category") or "综合", []).append(it)
    for cat in sorted(by_cat):
        lines.append("## %s" % cat)
        for it in by_cat[cat]:
            star = "⭐ " if it.get("starred") else ""
            lines.append("- %s[%s](%s) — %s" % (star, it.get("title", "?"),
                                                it.get("url", "#"),
                                                it.get("source", "")))
            if it.get("summary"):
                lines.append("  %s" % it["summary"])
        lines.append("")
    lines.append("> 导出时间：%s · 共 %d 条 · 来源：AgentFloat AI 快报"
                 % (time.strftime("%Y-%m-%d %H:%M"), len(rep.get("items") or [])))
    return "\n".join(lines)


def next_run_time(cfg=None, now=None):
    """计算下次自动生成时间（人类可读）；不适用时返回 ""。

    daily / daily_startup：今天 HH:MM，若已过则明天；startup：仅启动时补生成。
    """
    import datetime
    cfg = cfg or {}
    mode = str(cfg.get("schedule_mode") or "daily_startup")
    if mode not in ("daily", "daily_startup"):
        return "启动时" if mode == "startup" else ""
    hhmm = str(cfg.get("schedule_time") or "09:00")
    try:
        hh, mm = [int(x) for x in hhmm.split(":")[:2]]
    except (ValueError, TypeError):
        hh, mm = 9, 0
    now = now or datetime.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target.strftime("%m-%d %H:%M")
