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
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 AgentFloat/1.2")

# 默认配置（load_config 引用；用户可在「设置 → AI 快报」修改）
DEFAULT_NEWS = {
    "enabled": False,
    "language": "zh",            # zh / en / both
    "schedule_mode": "daily_startup",  # off / daily / startup / daily_startup
    "schedule_time": "09:00",
    "max_items": 6,
    "use_ai": True,              # False = 纯标题列表（不调用本地 Agent）
    "agent_id": "",              # 空 = 默认主 Agent
    "sources": ["hackernews", "github_trending", "sspai", "qbitai"],
    "notify": True,
    "badge": True,
    "unread_count": 0,
    "last_generated": "",
}


def news_storage_dir():
    """快报数据目录：打包后存 %APPDATA%/AgentFloat/news/，开发时存脚本目录/news/"""
    if getattr(sys, "frozen", False):
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "news")
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


def fetch_all(enabled_ids, per_source=12, timeout=15):
    """并发抓取启用源；返回 (items, errors)"""
    enabled = [SOURCE_MAP[i] for i in enabled_ids if i in SOURCE_MAP]
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=max(2, len(enabled))) as pool:
        futures = {pool.submit(s["fetch"], per_source): s for s in enabled}
        for fut in as_completed(futures, timeout=timeout + 5):
            s = futures[fut]
            try:
                got = fut.result() or []
                items.extend(got)
            except Exception as e:
                errors.append("%s：%s" % (s["name"], _brief_err(e)))
    return items, errors


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


def save_report(date, items, raw_md, language, used_ai, source_errors):
    """写入 news/<date>.json + news/<date>.md + news/latest.json，返回 latest 数据"""
    d = news_storage_dir()
    payload = {
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "language": language,
        "used_ai": used_ai,
        "source_errors": source_errors,
        "count": len(items),
        "items": items,
        "raw_md": raw_md,
    }
    with open(os.path.join(d, "%s.json" % date), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "%s.md" % date), "w", encoding="utf-8") as f:
        f.write(raw_md)
    with open(os.path.join(d, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
