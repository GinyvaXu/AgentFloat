# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 快报数据源抓取（B 线 · 日报 2.0）

多源聚合 → 硬过滤 → 去重 / 相似合并 → 五因子评分 → 分类配额 + MMR
→ 结构化条目（纯标准库 + urllib，超时与失败降级）。

B 线契约（2026-10-21 风暴稿 §3.B）：
- 首批 15 源：Wave 1（10）+ Wave 2（5），每源带 layer / trust / wave 元数据；
- 硬过滤：空字段、屏蔽词、7 天时效、源信任 < 0.5、URL 重复、标题相似 ≥ 0.9；
- 评分：信任 25 / 新鲜 20 / 兴趣 20 / 重要性 25 / 多样性 10（0–100）；
- 分类配额单类 ≤3 + MMR（λ=0.7）；每条至少两个可解释理由；
- AI 契约：news-v3、schema 校验、修复 1 次、逐条降级、缓存 key 含 prompt_version；
- 报告向后兼容：旧 latest.json 可直接读，新增字段只增不删。

架构参考致谢（详见 README「致谢」与 docs/AI快报与多功能浮窗助手调研报告.md）：
- TrendRadar / agents-radar：多源 RSS 聚合 + 分类 + 单一时区计划表
- horizonnews / dailybrief：双语生成 + 主题聚类
- ai-daily-skill：一句话摘要 + 分类的轻量快报格式
"""
import copy
import difflib
import hashlib
import html as html_lib
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

from agentfloat.core.paths import config_dir as _app_config_dir

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 AgentFloat/1.2")

NEWS_PROMPT_VERSION = "news-v3"
AI_CATEGORIES = ("模型", "工具", "论文", "产品", "行业", "综合")
SOURCE_LAYERS = {
    "official": "官方",
    "paper": "论文",
    "community": "社区",
    "chinese": "中文",
    "product": "产品",
}

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
    # Wave 1 默认开启（arXiv 按 B2 约定默认未开）；Wave 2 验证后再由用户勾选
    "sources": [
        "hackernews", "github_trending", "sspai", "qbitai",
        "openai_news", "anthropic_news", "deepmind_blog", "jiqizhixin", "infoq_ai",
    ],
    "per_source": 12,            # v3.9.0 每源抓取条数
    "ai_max_items": 6,           # v3.9.0 送 AI 摘要的条数上限
    "blocked_keywords": [],      # v3.9.0 屏蔽关键词（标题命中即丢弃）
    "retention_days": 14,        # v3.9.0 历史保留天数
    "max_age_days": 7,           # B 线：硬过滤时效窗口
    "category_cap": 3,           # B 线：单分类最多条数
    "mmr_lambda": 0.7,           # B 线：MMR 相关性权重
    "retry_failed_sources": True,  # B 线：失败源自动重试一次
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


# ── HTTP / 文本工具 ────────────────────────────────
def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _http_json(url, timeout=20):
    return json.loads(_http_get(url, timeout))


def _clean_text(text, limit=400):
    """去 HTML 标签 / 实体 / 多余空白，截断到 limit 字符"""
    raw = html_lib.unescape(str(text or ""))
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:limit]


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
            "desc": _clean_text(it.get("text") or ""),
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


def _fetch_rss(url, source, limit=12):
    """通用 RSS 2.0 / Atom 抓取（description/summary 作为抽取式摘要）"""
    text = _http_get(url)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # 部分源返回 XML 声明前有 BOM/空白，去掉后重试
        text = text.lstrip("\ufeff \t\r\n")
        root = ET.fromstring(text)
    items = []
    is_rss = root.tag.split("}")[-1].lower() == "rss"
    wanted = "item" if is_rss else "entry"
    nodes = [n for n in root.iter() if n.tag.split("}")[-1].lower() == wanted]
    for node in nodes:
        title = ""
        link = ""
        guid = ""
        pub = None
        desc = ""
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "title":
                title = _clean_text(child.text or "", 300)
            elif tag == "link":
                link = (child.text or "").strip() or child.get("href", "").strip()
            elif tag == "guid":
                guid = (child.text or "").strip()
            elif tag in ("pubDate", "published", "updated"):
                pub = (child.text or "").strip()
            elif tag in ("description", "summary", "content", "encoded"):
                desc = _clean_text(child.text or "", 400) or desc
        if not link and guid.startswith("http"):
            link = guid
        if not title:
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source,
            "ts": _parse_rss_time(pub),
            "extra": "",
            "desc": desc,
        })
        if len(items) >= limit:
            break
    return items


def _fetch_html_links(url, source, href_re, limit=12):
    """从 HTML 页面提取文章链接（接口不稳时的降级方案）"""
    html = _http_get(url)
    seen, out = set(), []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href = html_lib.unescape(m.group(1)).strip()
        if href_re and not re.search(href_re, href):
            continue
        title = _clean_text(m.group(2), 200)
        if len(title) < 8:
            continue
        full = urljoin(url, href)
        if not full.startswith("http") or full in seen:
            continue
        seen.add(full)
        out.append({
            "title": title,
            "url": full,
            "source": source,
            "ts": int(time.time()),
            "extra": "网页",
        })
        if len(out) >= limit:
            break
    return out


def _fetch_rss_or_html(rss_url, page_url, source, href_re, limit=12):
    """先试 RSS，失败或为空时降级 HTML 解析"""
    try:
        items = _fetch_rss(rss_url, source, limit)
        if items:
            return items
    except Exception:  # noqa: BLE001
        pass
    return _fetch_html_links(page_url, source, href_re, limit)


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
        summary = _clean_text(entry.findtext("a:summary", "", ns), 400)
        out.append({
            "title": _clean_text(title, 300),
            "url": link,
            "source": "arXiv AI",
            "ts": _parse_rss_time(published),
            "extra": "论文",
            "desc": summary,
        })
    return out


def _fetch_openai_news(limit=12):
    """OpenAI News 官方 RSS"""
    return _fetch_rss("https://openai.com/news/rss.xml", "OpenAI News", limit)


def _fetch_anthropic_news(limit=12):
    """Anthropic News：优先 RSS，缺失时解析官网列表"""
    return _fetch_rss_or_html(
        "https://www.anthropic.com/rss.xml",
        "https://www.anthropic.com/news",
        "Anthropic News", r"/news/[^\"'#?]+", limit)


def _fetch_deepmind_blog(limit=12):
    """Google DeepMind Blog：优先 RSS，缺失时解析官网列表"""
    return _fetch_rss_or_html(
        "https://deepmind.google/blog/rss.xml",
        "https://deepmind.google/discover/blog/",
        "Google DeepMind Blog", r"/(?:discover/)?blog/[^\"'#?]+", limit)


def _fetch_jiqizhixin(limit=12):
    """机器之心 RSS"""
    return _fetch_rss("https://www.jiqizhixin.com/rss", "机器之心", limit)


def _fetch_infoq_ai(limit=12):
    """InfoQ AI 频道 RSS（失败时降级首页 AI 列表）"""
    return _fetch_rss_or_html(
        "https://www.infoq.cn/feed/ai",
        "https://www.infoq.cn/topic/AI",
        "InfoQ AI", r"/article/[^\"'#?]+", limit)


def _fetch_hf_papers(limit=12):
    """Hugging Face Papers（RSS 优先，HTML 兜底）"""
    return _fetch_rss_or_html(
        "https://huggingface.co/papers/rss",
        "https://huggingface.co/papers",
        "Hugging Face Papers", r"/papers/[^\"'#?]+", limit)


def _fetch_reddit_localllama(limit=12):
    """Reddit r/LocalLLaMA RSS"""
    return _fetch_rss("https://www.reddit.com/r/LocalLLaMA/.rss",
                      "Reddit r/LocalLLaMA", limit)


def _fetch_product_hunt(limit=12):
    """Product Hunt 官方 RSS"""
    return _fetch_rss("https://www.producthunt.com/feed", "Product Hunt", limit)


def _fetch_qwen_blog(limit=12):
    """Qwen 官方博客（Hugo RSS）"""
    return _fetch_rss_or_html(
        "https://qwenlm.github.io/blog/index.xml",
        "https://qwenlm.github.io/blog/",
        "Qwen Blog", r"/blog/[^\"'#?]+", limit)


def _fetch_deepseek_news(limit=12):
    """DeepSeek News：优先 RSS，缺失时解析文档站新闻列表"""
    return _fetch_rss_or_html(
        "https://api-docs.deepseek.com/news/rss.xml",
        "https://api-docs.deepseek.com/news",
        "DeepSeek News", r"/news/[^\"'#?]+", limit)


# 可插拔源注册表（B 线：layer / trust / wave / default_on）
SOURCES = [
    {"id": "hackernews", "name": "Hacker News", "zh": "Hacker News",
     "layer": "community", "trust": 0.80, "wave": 1, "default_on": True,
     "fetch": _fetch_hackernews},
    {"id": "github_trending", "name": "GitHub Trending", "zh": "GitHub 趋势",
     "layer": "product", "trust": 0.75, "wave": 1, "default_on": True,
     "fetch": _fetch_github_trending},
    {"id": "sspai", "name": "少数派", "zh": "少数派",
     "layer": "chinese", "trust": 0.78, "wave": 1, "default_on": True,
     "fetch": _fetch_sspai},
    {"id": "qbitai", "name": "量子位", "zh": "量子位",
     "layer": "chinese", "trust": 0.80, "wave": 1, "default_on": True,
     "fetch": _fetch_qbitai},
    {"id": "arxiv_ai", "name": "arXiv AI", "zh": "arXiv AI",
     "layer": "paper", "trust": 0.90, "wave": 1, "default_on": False,
     "fetch": _fetch_arxiv_ai},
    {"id": "openai_news", "name": "OpenAI News", "zh": "OpenAI News",
     "layer": "official", "trust": 0.95, "wave": 1, "default_on": True,
     "fetch": _fetch_openai_news},
    {"id": "anthropic_news", "name": "Anthropic News", "zh": "Anthropic News",
     "layer": "official", "trust": 0.95, "wave": 1, "default_on": True,
     "fetch": _fetch_anthropic_news},
    {"id": "deepmind_blog", "name": "Google DeepMind Blog", "zh": "DeepMind 博客",
     "layer": "official", "trust": 0.95, "wave": 1, "default_on": True,
     "fetch": _fetch_deepmind_blog},
    {"id": "jiqizhixin", "name": "机器之心", "zh": "机器之心",
     "layer": "chinese", "trust": 0.80, "wave": 1, "default_on": True,
     "fetch": _fetch_jiqizhixin},
    {"id": "infoq_ai", "name": "InfoQ AI", "zh": "InfoQ AI",
     "layer": "chinese", "trust": 0.78, "wave": 1, "default_on": True,
     "fetch": _fetch_infoq_ai},
    {"id": "hf_papers", "name": "Hugging Face Papers", "zh": "Hugging Face 论文",
     "layer": "paper", "trust": 0.88, "wave": 2, "default_on": False,
     "fetch": _fetch_hf_papers},
    {"id": "reddit_localllama", "name": "Reddit r/LocalLLaMA", "zh": "Reddit 本地模型",
     "layer": "community", "trust": 0.65, "wave": 2, "default_on": False,
     "fetch": _fetch_reddit_localllama},
    {"id": "product_hunt", "name": "Product Hunt", "zh": "Product Hunt",
     "layer": "product", "trust": 0.60, "wave": 2, "default_on": False,
     "fetch": _fetch_product_hunt},
    {"id": "qwen_blog", "name": "Qwen Blog", "zh": "Qwen 博客",
     "layer": "official", "trust": 0.95, "wave": 2, "default_on": False,
     "fetch": _fetch_qwen_blog},
    {"id": "deepseek_news", "name": "DeepSeek News", "zh": "DeepSeek 新闻",
     "layer": "official", "trust": 0.95, "wave": 2, "default_on": False,
     "fetch": _fetch_deepseek_news},
]
SOURCE_MAP = {s["id"]: s for s in SOURCES}


def source_catalog(enabled_ids=None):
    """源注册表快照（供设置页 / Web API 使用）"""
    enabled = set(enabled_ids or [])
    rows = []
    for s in SOURCES:
        rows.append({
            "id": s["id"],
            "name": s.get("name") or s["id"],
            "zh": s.get("zh") or s.get("name") or s["id"],
            "layer": s.get("layer") or "community",
            "layer_label": SOURCE_LAYERS.get(s.get("layer") or "community", "社区"),
            "trust": float(s.get("trust") or 0.6),
            "wave": int(s.get("wave") or 1),
            "default_on": bool(s.get("default_on")),
            "enabled": s["id"] in enabled,
        })
    return rows


def _source_for_item(item):
    """按 source_id / 来源名反查注册表条目"""
    sid = (item or {}).get("source_id")
    if sid and sid in SOURCE_MAP:
        return SOURCE_MAP[sid]
    name = str((item or {}).get("source") or "").strip().lower()
    if name:
        for s in SOURCES:
            if name in (str(s.get("name") or "").lower(), str(s.get("zh") or "").lower()):
                return s
    return None


def source_trust(item):
    """条目来源信任度：优先条目自带，其次注册表，最后 0.6"""
    row = item or {}
    try:
        if row.get("source_trust") is not None:
            return max(0.0, min(1.0, float(row["source_trust"])))
    except (TypeError, ValueError):
        pass
    src = _source_for_item(row)
    if src:
        return float(src.get("trust") or 0.6)
    try:
        return max(0.0, min(1.0, float(row.get("trust") or 0.6)))
    except (TypeError, ValueError):
        return 0.6


def fetch_all_stats(enabled_ids, per_source=12, timeout=15, progress=None):
    """并发抓取启用源（v3.9.0 增强版）。

    返回 ``(items, errors, sources)``：
    - items: 原始条目列表（带 source_id / source_trust / source_layer）
    - errors: 供 UI 展示的「源名：原因」字符串列表（保持旧行为）
    - sources: 结构化每源结果 [{id,name,ok,count,error,status,trust,layer,wave,...}]

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
                for item in got:
                    if not isinstance(item, dict):
                        continue
                    item["source_id"] = s["id"]
                    item["source_trust"] = float(s.get("trust") or 0.6)
                    item["source_layer"] = s.get("layer") or "community"
                items.extend(got)
                stats.append({
                    "id": s["id"], "name": s.get("zh") or s.get("name") or s["id"],
                    "raw_name": s.get("name") or s.get("zh") or s["id"],
                    "ok": True, "count": len(got), "error": "",
                    "status": "ok" if got else "degraded",
                    "trust": float(s.get("trust") or 0.6),
                    "layer": s.get("layer") or "community",
                    "wave": int(s.get("wave") or 1),
                    "attempts": 1, "retried": False,
                })
            except Exception as e:
                msg = _brief_err(e)
                errors.append("%s：%s" % (s.get("name") or s.get("zh") or s["id"], msg))
                stats.append({
                    "id": s["id"], "name": s.get("zh") or s.get("name") or s["id"],
                    "raw_name": s.get("name") or s.get("zh") or s["id"],
                    "ok": False, "count": 0, "error": msg, "status": "failed",
                    "trust": float(s.get("trust") or 0.6),
                    "layer": s.get("layer") or "community",
                    "wave": int(s.get("wave") or 1),
                    "attempts": 1, "retried": False,
                })
            done += 1
            if progress:
                try:
                    progress(done, total, s.get("zh") or s.get("name") or s["id"])
                except Exception:  # noqa: BLE001
                    pass
    except TimeoutError:
        for fut in list(pending):
            fut.cancel()
            s = futures[fut]
            msg = "超时未完成"
            errors.append("%s：%s" % (s.get("name") or s.get("zh") or s["id"], msg))
            stats.append({
                "id": s["id"], "name": s.get("zh") or s.get("name") or s["id"],
                "raw_name": s.get("name") or s.get("zh") or s["id"],
                "ok": False, "count": 0, "error": msg, "status": "failed",
                "trust": float(s.get("trust") or 0.6),
                "layer": s.get("layer") or "community",
                "wave": int(s.get("wave") or 1),
                "attempts": 1, "retried": False,
            })
            done += 1
            if progress:
                try:
                    progress(done, total, s.get("zh") or s.get("name") or s["id"])
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
    return items, errors, stats


def fetch_with_retry(enabled_ids, per_source=12, timeout=15, progress=None, retries=1):
    """抓取 + 失败源自动重试（B 线：生成流程内的一次重试）。

    单源重试走 fetch_all_stats 的同一通道，保持超时/异常语义一致；
    最终 errors 由源健康状态重建，失败源只保留最后一次原因。
    进度按「首轮源数 + 每轮失败源数」累计，避免重试时进度条倒退。
    """
    items, errors, stats = fetch_all_stats(enabled_ids, per_source, timeout, progress)
    attempts = 0
    try:
        retries = max(0, int(retries))
    except (TypeError, ValueError):
        retries = 0
    completed = len(stats)
    grand_total = len(stats)
    while attempts < retries:
        failed = [s["id"] for s in stats if not s.get("ok")]
        if not failed:
            break
        attempts += 1
        grand_total += len(failed)
        if progress:
            try:
                progress(completed, grand_total,
                         "重试 %d 个失败源（第 %d 次）" % (len(failed), attempts))
            except Exception:  # noqa: BLE001
                pass

        def _retry_progress(done, total, label, offset=completed, all_total=grand_total):
            if progress:
                try:
                    progress(min(offset + done, all_total), all_total,
                             "重试：%s" % label)
                except Exception:  # noqa: BLE001
                    pass

        more_items, _more_errors, more_stats = fetch_all_stats(
            failed, per_source, timeout, _retry_progress)
        items.extend(more_items)
        completed += len(failed)
        by_id = {s["id"]: s for s in stats}
        for new in more_stats:
            old = by_id.get(new["id"])
            if old is None:
                stats.append(new)
                continue
            old["attempts"] = int(old.get("attempts") or 1) + 1
            old["retried"] = True
            if new.get("ok"):
                old["ok"] = True
                old["count"] = new.get("count") or 0
                old["error"] = ""
                old["status"] = new.get("status") or "ok"
            else:
                old["ok"] = False
                old["error"] = new.get("error") or "重试失败"
                old["status"] = "failed"
        errors = ["%s：%s" % (s.get("raw_name") or s.get("name") or s["id"],
                              s.get("error") or "失败")
                  for s in stats if not s.get("ok")]
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
        got = src["fetch"](per_source) or []
        for item in got:
            if isinstance(item, dict):
                item["source_id"] = src["id"]
                item["source_trust"] = float(src.get("trust") or 0.6)
                item["source_layer"] = src.get("layer") or "community"
        return got, ""
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
                         str(it.get("desc", "")), str(it.get("source", ""))]).lower()
        if any(w in text for w in words):
            continue
        out.append(it)
    return out


def item_id(url="", title=""):
    """条目稳定 id（同一链接跨次生成保持同一 id → 已读/收藏可延续）"""
    key = _norm_url(url) or (title or "").strip()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _brief_err(e):
    return str(e)[:120]


# ── 去重 / 相似 / 质量过滤 ─────────────────────────
def _norm_url(url):
    u = (url or "").strip().lower()
    for p in ("https://", "http://", "www."):
        u = u.replace(p, "")
    return u.rstrip("/")


def _title_norm(title):
    text = _clean_text(title, 300).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(a, b):
    """标题相似度 0–1（中英文字符级，用于 0.9 硬去重 / MMR）"""
    ta, tb = _title_norm(a), _title_norm(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def _add_related(target, item, reason=""):
    """把被合并/相似条目挂到保留条目的 related 上（详情「相关来源」）"""
    if not isinstance(target, dict) or not isinstance(item, dict):
        return
    url = (item.get("url") or "").strip()
    title = (item.get("title") or "").strip()
    if not url and not title:
        return
    if (target.get("url") or "").strip() == url:
        return
    rel = target.setdefault("related", [])
    if any((r.get("url") or "") == url and (r.get("title") or "") == title for r in rel):
        return
    rel.append({
        "title": title,
        "url": url,
        "source": item.get("source") or "",
        "source_id": item.get("source_id") or "",
        "reason": reason,
    })
    if len(rel) > 4:
        del rel[4:]


def prefilter_items(items, blocked_keywords=None, now=None, max_age_days=7,
                    min_trust=0.5):
    """B 线硬过滤（纯函数）。

    顺序：空字段 → 屏蔽词 → 时效 → 源信任 → URL 重复 → 标题相似（≥0.9）。
    重复/相似项不直接丢弃，而是挂到保留项的 related 上，供「相关来源」展示。

    返回 ``(kept, stats)``；stats 字段用于 G4 质量指标。
    """
    now = int(now if now is not None else time.time())
    try:
        max_age = max(0, int(max_age_days)) * 86400
    except (TypeError, ValueError):
        max_age = 7 * 86400
    try:
        min_trust = max(0.0, min(1.0, float(min_trust)))
    except (TypeError, ValueError):
        min_trust = 0.5
    blocked = [w.strip().lower() for w in (blocked_keywords or []) if str(w).strip()]
    stats = {"raw": 0, "empty": 0, "blocked": 0, "stale": 0, "low_trust": 0,
             "duplicate": 0, "similar": 0, "kept": 0, "filtered": 0, "related": 0}
    kept = []
    by_url = {}
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        stats["raw"] += 1
        title = (raw.get("title") or "").strip()
        url = (raw.get("url") or "").strip()
        if not title or not url or url == "#":
            stats["empty"] += 1
            continue
        blob = " ".join([title, str(raw.get("summary") or ""),
                         str(raw.get("desc") or ""), str(raw.get("source") or "")]).lower()
        if any(w in blob for w in blocked):
            stats["blocked"] += 1
            continue
        try:
            ts = int(raw.get("ts") or now)
        except (TypeError, ValueError):
            ts = now
        if ts > now + 2 * 86400:       # 未来时间视为现在，避免破坏时效计算
            ts = now
        if max_age and now - ts > max_age:
            stats["stale"] += 1
            continue
        trust = source_trust(raw)
        if trust < min_trust:
            stats["low_trust"] += 1
            continue
        row = dict(raw)
        row["ts"] = ts
        key = _norm_url(url) or _title_norm(title)
        if key in by_url:
            _add_related(by_url[key], row, "URL 重复")
            stats["duplicate"] += 1
            continue
        similar_to = None
        for prev in kept:
            if title_similarity(title, prev.get("title", "")) >= 0.9:
                similar_to = prev
                break
        if similar_to is not None:
            _add_related(similar_to, row, "标题相似")
            stats["similar"] += 1
            continue
        by_url[key] = row
        kept.append(row)
    kept.sort(key=lambda x: x.get("ts", 0), reverse=True)
    stats["kept"] = len(kept)
    stats["filtered"] = stats["raw"] - len(kept)
    stats["related"] = sum(len(it.get("related") or []) for it in kept)
    return kept, stats


def dedupe(items, max_total):
    """按归一化 URL 去重，保留先抓到的条目，再按时间倒序截断（旧接口保留）"""
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
    "模型": ["llm", "gpt", "claude", "gemini", "deepseek", "qwen", "openai", "anthropic",
             "deepmind", "model", "模型", "大模型", "基座", "推理", "diffusion",
             "文生", "多模态", "vllm", "ollama", "权重", "开源模型"],
    "工具": ["工具", "cli", "sdk", "api", "框架", "库", "开源", "github", "插件", "app",
             "release", "v0.", "代码", "agent"],
    "论文": ["论文", "arxiv", "research", "paper", "研究", "benchmark", "评测"],
    "产品": ["发布", "上线", "产品", "体验", "实测", "更新", "升级", "app store", "新品"],
    "行业": ["融资", "收购", "监管", "政策", "公司", "财报", "裁员", "合作", "亿元", "美元",
             "行业", "市场"],
}


def guess_category(title, url=""):
    text = ("%s %s" % (title or "", url or "")).lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text:
                return cat
    return "综合"


# ── 五因子评分 / 分类配额 / MMR ────────────────────
_HOT_RE = re.compile(r"([0-9]+)")
_IMPORTANT_RE = re.compile(
    r"发布|开源|上线|推出|升级|融资|收购|突破|刷新|sota|benchmark|release|launch|"
    r"open.?source|breakthrough|state.of.the.art", re.I)


def _hot_value(item):
    text = "%s %s" % (item.get("extra") or "", item.get("desc") or "")
    nums = [int(x) for x in _HOT_RE.findall(text)[:3] if str(x).isdigit()]
    if nums:
        return max(nums)
    if re.search(r"trending|热门|hot", text, re.I):
        return 50
    return 0


def interest_score(item, interests=None):
    """关注主题命中分（0–20）：权重 1–5，命中多个可叠加"""
    rows = [r for r in (interests or []) if (r.get("label") or "").strip()]
    if not rows:
        return 0.0
    text = " ".join([str(item.get("title") or ""), str(item.get("desc") or ""),
                     str(item.get("summary") or "")]).lower()
    total = 0
    for row in rows:
        try:
            weight = max(1, min(5, int(row.get("weight") or 1)))
        except (TypeError, ValueError):
            weight = 1
        labels = re.split(r"[,，、;；]+", str(row.get("label") or ""))
        if any(kw.strip() and kw.strip().lower() in text for kw in labels):
            total += weight
    return float(min(20, total * 4))


def freshness_score(ts, now=None):
    """新鲜度 0–20：≤24h=20，≤3d=14，≤7d=7"""
    now = int(now if now is not None else time.time())
    try:
        age = max(0, now - int(ts or now))
    except (TypeError, ValueError):
        age = 0
    if age <= 86400:
        return 20.0
    if age <= 3 * 86400:
        return 14.0
    if age <= 7 * 86400:
        return 7.0
    return 0.0


def importance_score(item, trust=None):
    """重要性 0–25：AI importance(1–5) 优先，否则用官方/热门/关键词信号"""
    raw = item.get("ai_importance")
    if raw is None:
        raw = item.get("importance")
    try:
        if raw is not None and 1 <= int(raw) <= 5:
            return float(int(raw) * 5)
    except (TypeError, ValueError):
        pass
    trust = source_trust(item) if trust is None else float(trust)
    ratio = 0.35
    if trust >= 0.9:
        ratio += 0.25
    hot = _hot_value(item)
    ratio += 0.20 if hot >= 100 else (0.12 if hot > 0 else 0.0)
    if _IMPORTANT_RE.search("%s %s" % (item.get("title") or "", item.get("desc") or "")):
        ratio += 0.20
    if (item.get("source_layer") or "") == "paper":
        ratio += 0.05
    return round(min(1.0, ratio) * 25, 1)


def score_breakdown(item, interests=None, now=None):
    """单条五因子中的前四项（0–90）；多样性在 rank_items 选择时计算"""
    now = int(now if now is not None else time.time())
    trust = source_trust(item)
    factors = {
        "trust": round(trust * 25, 1),
        "freshness": freshness_score(item.get("ts"), now),
        "interest": interest_score(item, interests),
        "importance": importance_score(item, trust),
    }
    return {"score": round(sum(factors.values()), 1), "factors": factors}


def score_reasons(item, factors, trust=None, hot=None):
    """可解释排序理由：至少两个（B2「每条至少显示两个理由」）"""
    trust = source_trust(item) if trust is None else float(trust)
    hot = _hot_value(item) if hot is None else hot
    reasons = []
    if trust >= 0.9:
        reasons.append("官方源")
    if factors.get("freshness", 0) >= 16:
        reasons.append("24 小时内")
    elif factors.get("freshness", 0) >= 7:
        reasons.append("7 天内")
    if factors.get("interest", 0) > 0:
        reasons.append("命中关注")
    if factors.get("importance", 0) >= 18:
        reasons.append("重要性高")
    if hot > 0:
        reasons.append("本周热门")
    if len(reasons) < 2:
        reasons.append("来源可信 %.2f" % trust)
    if len(reasons) < 2:
        reasons.append("综合排序")
    return reasons[:3]


def rank_items(items, max_items=6, interests=None, now=None,
               category_cap=3, mmr_lambda=0.7, relax_cap=False):
    """评分 + 分类配额 + MMR 排序（纯函数，返回新列表）。

    - 基础相关度 = 信任 25 + 新鲜 20 + 兴趣 20 + 重要性 25（0–90）
    - 多样性 = (1 - 与已选条目最大标题相似度) × 10
    - 选择分 = λ × 相关度/90 − (1−λ) × 相似度；最终展示分 = 相关度 + 多样性
    """
    now = int(now if now is not None else time.time())
    try:
        max_items = max(1, int(max_items))
    except (TypeError, ValueError):
        max_items = 6
    try:
        category_cap = max(1, int(category_cap))
    except (TypeError, ValueError):
        category_cap = 3
    try:
        lam = min(1.0, max(0.0, float(mmr_lambda)))
    except (TypeError, ValueError):
        lam = 0.7
    pool = []
    for idx, raw in enumerate(items or []):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row.setdefault("id", item_id(row.get("url", ""), row.get("title", "")))
        row.setdefault("category", guess_category(row.get("title", ""), row.get("url", "")))
        bd = score_breakdown(row, interests, now)
        row["factors"] = dict(bd["factors"])
        row["_base"] = bd["score"]
        row["_idx"] = idx
        row["_sim"] = 0.0
        pool.append(row)
    selected = []
    used = set()
    cat_count = {}

    def pick(cap_enabled):
        best = None
        best_key = None
        for row in pool:
            key = id(row)
            if key in used:
                continue
            cat = row.get("category") or "综合"
            if cap_enabled and cat_count.get(cat, 0) >= category_cap:
                continue
            sim = 0.0
            for chosen in selected:
                sim = max(sim, title_similarity(row.get("title", ""), chosen.get("title", "")))
            mmr = lam * (row["_base"] / 90.0) - (1 - lam) * sim
            sort_key = (mmr, row["_base"], row.get("ts") or 0, -row["_idx"])
            if best is None or sort_key > best_key:
                best, best_key, best_sim = row, sort_key, sim
        if best is None:
            return None
        best["_sim"] = best_sim
        return best

    while len(selected) < max_items:
        row = pick(True)
        if row is None:
            break
        used.add(id(row))
        cat = row.get("category") or "综合"
        cat_count[cat] = cat_count.get(cat, 0) + 1
        selected.append(row)
    # 默认严格守住「单类 ≤ cap」；仅在显式 relax_cap=True 时补足名额
    if relax_cap:
        while len(selected) < max_items:
            row = pick(False)
            if row is None:
                break
            used.add(id(row))
            cat = row.get("category") or "综合"
            cat_count[cat] = cat_count.get(cat, 0) + 1
            selected.append(row)

    out = []
    for row in selected:
        sim = float(row.pop("_sim", 0.0) or 0.0)
        base = float(row.pop("_base", 0.0) or 0.0)
        row.pop("_idx", None)
        diversity = round((1.0 - sim) * 10, 1)
        factors = dict(row.get("factors") or {})
        factors["diversity"] = diversity
        reason_list = score_reasons(row, factors)
        row["factors"] = factors
        row["score"] = round(min(100.0, base + diversity), 1)
        row["reasons"] = reason_list
        row["why"] = "；".join(reason_list)
        out.append(row)
    return out


def extractive_summary(item, max_len=90):
    """无 AI 时的抽取式摘要：优先 desc，其次现有 summary，最后 extra"""
    text = ""
    for key in ("summary", "desc", "extra"):
        text = _clean_text((item or {}).get(key) or "", 400)
        if text and text.lower() != str((item or {}).get("title") or "").lower():
            break
    if not text:
        return ""
    if len(text) > max_len:
        text = text[:max_len].rstrip("，。,. ") + "…"
    return text


def enrich_item(item, now=None, compute_score=False, interests=None):
    """补齐报告条目字段（id/category/read/starred/why/score/factors/related）"""
    now = int(now if now is not None else time.time())
    row = dict(item or {})
    row.setdefault("id", item_id(row.get("url", ""), row.get("title", "")))
    row.setdefault("category", guess_category(row.get("title", ""), row.get("url", "")))
    row.setdefault("read", False)
    row.setdefault("starred", False)
    row.setdefault("summary", "")
    row.setdefault("related", [])
    row.setdefault("translated", bool(row.get("summary")))
    row.setdefault("degraded", False)
    if compute_score and not row.get("factors"):
        bd = score_breakdown(row, interests, now)
        factors = dict(bd["factors"])
        factors["diversity"] = float(row.get("factors", {}).get("diversity") or 0.0)
        reasons = score_reasons(row, factors)
        row["factors"] = factors
        row["score"] = round(min(100.0, bd["score"] + factors["diversity"]), 1)
        row["reasons"] = reasons
        row["why"] = "；".join(reasons)
    else:
        row.setdefault("score", 0.0)
        row.setdefault("factors", {})
        row.setdefault("reasons", [])
        row.setdefault("why", "")
    row.setdefault("importance", 3)
    return row


# ── 落盘 ───────────────────────────────────────────
def build_raw_markdown(items, date, language="zh"):
    """纯列表模式 / AI 失败兜底：标题 + 来源链接"""
    head = "今日 AI 速览（%s）" % date if language != "en" else "AI Daily Brief (%s)" % date
    lines = [head, ""]
    for i, it in enumerate(items, 1):
        lines.append("%d. [%s](%s) — %s" % (i, it.get("title", "?"),
                                            it.get("url", "#"), it.get("source", "")))
    return "\n".join(lines)


def normalize_sources(sources):
    """补齐每源健康字段；兼容旧报告只有 {id,ok,count,error} 的情况"""
    out = []
    for raw in sources or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        meta = SOURCE_MAP.get(row.get("id")) or {}
        row.setdefault("name", meta.get("zh") or meta.get("name") or row.get("id") or "")
        row.setdefault("trust", float(meta.get("trust") or 0.6))
        row.setdefault("layer", meta.get("layer") or "community")
        row.setdefault("wave", int(meta.get("wave") or 1))
        try:
            row["count"] = int(row.get("count") or 0)
        except (TypeError, ValueError):
            row["count"] = 0
        row.setdefault("error", "")
        if "ok" not in row:
            row["ok"] = not bool(row.get("error"))
        status = str(row.get("status") or "")
        if status not in ("ok", "degraded", "failed"):
            if not row.get("ok"):
                status = "failed"
            elif row["count"] > 0:
                status = "ok"
            else:
                status = "degraded"
        row["status"] = status
        row.setdefault("attempts", 1)
        row.setdefault("retried", False)
        out.append(row)
    return out


def source_health(sources):
    """源健康摘要（正常 / 降级 / 失败 + 成功率）"""
    rows = normalize_sources(sources)
    total = len(rows)
    counts = {"ok": 0, "degraded": 0, "failed": 0}
    for row in rows:
        counts[row.get("status") or "failed"] = counts.get(row.get("status") or "failed", 0) + 1
    return {
        "total": total,
        "ok": counts.get("ok", 0),
        "degraded": counts.get("degraded", 0),
        "failed": counts.get("failed", 0),
        "success_rate": round((counts.get("ok", 0) / total), 3) if total else 0.0,
    }


def normalize_report(report):
    """就地补齐报告默认字段（旧 latest.json / 归档可继续读）"""
    if not isinstance(report, dict):
        return report
    report.setdefault("version", 2)
    report.setdefault("date", "")
    report.setdefault("generated_at", "")
    report.setdefault("language", "zh")
    report.setdefault("used_ai", False)
    report.setdefault("source_errors", [])
    report.setdefault("stats", {})
    report.setdefault("quality", {})
    report.setdefault("batch", {})
    report.setdefault("prompt_version", "")
    report.setdefault("headline", "")
    report.setdefault("summary", "")
    report.setdefault("count", len(report.get("items") or []))
    report["sources"] = normalize_sources(report.get("sources"))
    items = []
    for raw in report.get("items") or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row.setdefault("id", item_id(row.get("url", ""), row.get("title", "")))
        row.setdefault("category", guess_category(row.get("title", ""), row.get("url", "")))
        row.setdefault("read", False)
        row.setdefault("starred", False)
        row.setdefault("summary", "")
        row.setdefault("why", "")
        row.setdefault("score", 0.0)
        row.setdefault("factors", {})
        row.setdefault("reasons", [])
        row.setdefault("related", [])
        row.setdefault("translated", bool(row.get("summary")))
        row.setdefault("degraded", False)
        row.setdefault("importance", 3)
        items.append(row)
    report["items"] = items
    report["count"] = len(items)
    return report


def _write_payload(payload):
    d = news_storage_dir()
    date = payload.get("date") or time.strftime("%Y-%m-%d")
    with open(os.path.join(d, "%s.json" % date), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "%s.md" % date), "w", encoding="utf-8") as f:
        f.write(payload.get("raw_md") or "")
    with open(os.path.join(d, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def save_report(date, items, raw_md, language, used_ai, source_errors,
                sources=None, stats=None, headline="", summary="",
                quality=None, batch=None, prompt_version=""):
    """写入 news/<date>.json + news/<date>.md + news/latest.json，返回 latest 数据。

    v3.9.0：报告结构 version=2；B 线新增字段只增不删：
    - batch：生成批次 {id, started_at, finished_at, duration_ms, status, retries}
    - quality：G4 指标（重复率 / 翻译覆盖 / 平均分 / AI 合法率等）
    - prompt_version：AI prompt 版本（news-v3）
    - items：score / factors / reasons / why / related / translated / importance
    旧字段（count/items/raw_md/source_errors）保持不变以兼容既有调用。
    """
    now = int(time.time())
    enriched = [enrich_item(it, now, compute_score=True) for it in (items or [])]
    source_rows = normalize_sources(sources)
    stats_row = dict(stats or {})
    stats_row.setdefault("raw", len(enriched))
    stats_row.setdefault("blocked", 0)
    stats_row.setdefault("deduped", len(enriched))
    stats_row.setdefault("shown", len(enriched))
    quality_row = dict(quality or {})
    scores = [float(it.get("score") or 0) for it in enriched]
    quality_row.setdefault("avg_score", round(sum(scores) / len(scores), 1) if scores else 0.0)
    quality_row.setdefault("translation_coverage",
                           round(sum(1 for it in enriched if it.get("translated")) / len(enriched), 3)
                           if enriched else 0.0)
    quality_row.setdefault("duplicate_rate", 0.0)
    batch_row = dict(batch or {})
    batch_row.setdefault("id", "%s-%s" % (date, time.strftime("%H%M%S", time.localtime(now))))
    batch_row.setdefault("started_at", "")
    batch_row.setdefault("finished_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))
    batch_row.setdefault("duration_ms", 0)
    batch_row.setdefault("status", "partial" if source_errors else "ok")
    batch_row.setdefault("retries", [])
    payload = {
        "version": 2,
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "language": language,
        "used_ai": bool(used_ai),
        "source_errors": list(source_errors or []),
        "sources": source_rows,
        "source_health": source_health(source_rows),
        "stats": stats_row,
        "quality": quality_row,
        "batch": batch_row,
        "prompt_version": prompt_version or "",
        "headline": headline or "%s AI 速览" % date,
        "summary": summary or "",
        "count": len(enriched),
        "items": enriched,
        "raw_md": raw_md,
    }
    return _write_payload(payload)


def persist_report(report):
    """把已加工的报告（如单源重试合并后）重新落盘，返回最新数据"""
    rep = normalize_report(report or {})
    rep["count"] = len(rep.get("items") or [])
    rep.setdefault("generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    rep["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return _write_payload(rep)


def load_latest():
    """读取最新一期结构化数据；无则返回 None（旧格式自动补齐字段）"""
    p = os.path.join(news_storage_dir(), "latest.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return normalize_report(json.load(f))
    except (IOError, json.JSONDecodeError):
        return None


def list_archives():
    """按日期倒序列出历史快报 [(date, item_count), ...]（忽略状态/缓存文件）"""
    d = news_storage_dir()
    out = []
    try:
        for name in os.listdir(d):
            if not name.endswith(".json") or name == "latest.json":
                continue
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", name[:-5]):
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
    """读取指定日期的快报数据（旧格式自动补齐字段）"""
    p = os.path.join(news_storage_dir(), "%s.json" % date)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return normalize_report(json.load(f))
    except (IOError, json.JSONDecodeError):
        return None


# ── 单源重试合并（Web / Qt 共用）────────────────────
def merge_source_retry(report, source_id, items, blocked_keywords=None, now=None,
                       interests=None, error="", max_age_days=7, category_cap=3):
    """把单源重抓结果并回报告（纯函数，返回 ``(new_report, result)``）。

    - 新条目走同一套硬过滤 / 评分 / 理由生成；
    - 重复或相似条目挂到已有条目的 related（相关来源）；
    - 遵守单类配额（默认 ≤3），超额条目不写入；
    - 更新源健康、批次 retries 与质量统计，不重跑 AI。
    """
    rep = normalize_report(copy.deepcopy(report or {}))
    now = int(now if now is not None else time.time())
    meta = SOURCE_MAP.get(source_id) or {"id": source_id, "zh": source_id}
    source_name = meta.get("zh") or meta.get("name") or source_id
    added = 0
    duplicates = 0
    quota_skipped = 0
    try:
        category_cap = max(1, int(category_cap))
    except (TypeError, ValueError):
        category_cap = 3
    category_counts = {}
    for old in rep.get("items") or []:
        cat = old.get("category") or "综合"
        category_counts[cat] = category_counts.get(cat, 0) + 1
    if not error:
        incoming = []
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            row.setdefault("source_id", source_id)
            row.setdefault("source_trust", float(meta.get("trust") or 0.6))
            row.setdefault("source_layer", meta.get("layer") or "community")
            row.setdefault("source", source_name)
            incoming.append(row)
        incoming, _fstats = prefilter_items(
            incoming, blocked_keywords, now, max_age_days)
        existing = rep.get("items") or []
        by_url = {_norm_url(it.get("url")): it for it in existing if it.get("url")}
        for raw in incoming:
            url = (raw.get("url") or "").strip()
            title = (raw.get("title") or "").strip()
            key = _norm_url(url) or _title_norm(title)
            if key in by_url:
                _add_related(by_url[key], raw, "URL 重复")
                duplicates += 1
                continue
            similar = None
            for prev in existing:
                if title_similarity(title, prev.get("title", "")) >= 0.9:
                    similar = prev
                    break
            if similar is not None:
                _add_related(similar, raw, "标题相似")
                duplicates += 1
                continue
            category = raw.get("category") or guess_category(title, url)
            if category not in AI_CATEGORIES:
                category = guess_category(title, url)
            if category_counts.get(category, 0) >= category_cap:
                quota_skipped += 1
                continue
            raw = dict(raw, category=category)
            row = enrich_item(raw, now, compute_score=True, interests=interests)
            existing.append(row)
            by_url[key] = row
            category_counts[category] = category_counts.get(category, 0) + 1
            added += 1
        rep["items"] = existing
    rep["count"] = len(rep.get("items") or [])
    stats = dict(rep.get("stats") or {})
    stats["shown"] = rep["count"]
    stats["retry_added"] = int(stats.get("retry_added") or 0) + added
    stats["retry_duplicates"] = int(stats.get("retry_duplicates") or 0) + duplicates
    stats["retry_quota_skipped"] = int(stats.get("retry_quota_skipped") or 0) + quota_skipped
    rep["stats"] = stats
    quality = dict(rep.get("quality") or {})
    quality["duplicate"] = int(quality.get("duplicate") or 0) + duplicates
    quality["quota_skipped"] = int(quality.get("quota_skipped") or 0) + quota_skipped
    quality["avg_score"] = round(
        sum(float(it.get("score") or 0) for it in (rep.get("items") or []))
        / max(1, len(rep.get("items") or [])), 1)
    rep["quality"] = quality
    sources = rep.get("sources") or []
    found = None
    for src in sources:
        if src.get("id") == source_id:
            found = src
            break
    if found is None:
        found = {
            "id": source_id, "name": source_name,
            "trust": float(meta.get("trust") or 0.6),
            "layer": meta.get("layer") or "community",
            "wave": int(meta.get("wave") or 1),
            "attempts": 1, "retried": False,
        }
        sources.append(found)
    found["attempts"] = int(found.get("attempts") or 1) + 1
    found["retried"] = True
    if error:
        found["ok"] = False
        found["status"] = "failed"
        found["error"] = error
    else:
        found["ok"] = True
        found["count"] = int(found.get("count") or 0) + added
        found["error"] = ""
        found["status"] = "ok" if (found.get("count") or added) else "degraded"
    rep["sources"] = normalize_sources(sources)
    rep["source_health"] = source_health(rep["sources"])
    batch = dict(rep.get("batch") or {})
    retries = list(batch.get("retries") or [])
    retries.append({
        "source_id": source_id, "source": source_name,
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "added": added, "duplicates": duplicates,
        "quota_skipped": quota_skipped,
        "error": error, "ok": not bool(error),
    })
    batch["retries"] = retries[-20:]
    batch["status"] = "partial" if any(not s.get("ok") for s in rep["sources"]) else "ok"
    rep["batch"] = batch
    prefixes = [source_name + "："]
    if meta.get("name"):
        prefixes.append(str(meta["name"]) + "：")
    errs = [e for e in (rep.get("source_errors") or [])
            if not any(str(e).startswith(p) for p in prefixes)]
    if error:
        errs.append(prefixes[0] + error)
    rep["source_errors"] = errs
    rep["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    return rep, {"ok": not bool(error), "added": added,
                 "duplicates": duplicates, "quota_skipped": quota_skipped,
                 "error": error}


def retry_source_report(source_id, per_source=12, timeout=15, cfg=None, now=None):
    """抓取单个源并并回最新报告，成功后落盘；返回 UI 可用结果。"""
    cfg = cfg or {}
    report = load_latest()
    if not report:
        return {"ok": False, "added": 0, "error": "还没有快报，请先生成今日快报"}
    items, err = fetch_one(source_id, per_source=per_source, timeout=timeout)
    new_report, result = merge_source_retry(
        report, source_id, items,
        blocked_keywords=cfg.get("blocked_keywords"),
        now=now,
        interests=cfg.get("interests"),
        error=err,
        max_age_days=cfg.get("max_age_days", 7),
        category_cap=cfg.get("category_cap", 3))
    try:
        persist_report(new_report)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "added": 0, "error": "写入快报失败：%s" % e}
    return result


# ── AI 结果缓存（prompt_version 进入 key）────────────
def _ai_cache_path():
    return os.path.join(news_storage_dir(), "news_ai_cache.json")


def ai_cache_key(date, language, interests, items, prompt_version=NEWS_PROMPT_VERSION):
    """AI 缓存 key：日期 + 语言 + 关注主题 + 条目 id + prompt 版本"""
    rows = []
    for row in interests or []:
        if not (row.get("label") or "").strip():
            continue
        rows.append([str(row.get("label") or "").strip().lower(),
                     int(row.get("weight") or 1)])
    rows.sort()
    ids = []
    for it in items or []:
        ids.append(str(it.get("id") or item_id(it.get("url", ""), it.get("title", ""))))
    blob = json.dumps({
        "prompt_version": prompt_version,
        "date": date,
        "language": language,
        "interests": rows,
        "items": ids,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]


def load_ai_cache(key):
    try:
        with open(_ai_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = (data or {}).get(key)
        if isinstance(entry, dict):
            payload = entry.get("payload")
            return payload if isinstance(payload, dict) else None
    except (IOError, json.JSONDecodeError):
        pass
    return None


def save_ai_cache(key, payload, meta=None):
    """保存 AI 校验后的结果；最多保留 30 个 key（按时间淘汰）"""
    if not key or not isinstance(payload, dict):
        return False
    try:
        try:
            with open(_ai_cache_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (IOError, json.JSONDecodeError):
            data = {}
        data[key] = {
            "saved_at": int(time.time()),
            "prompt_version": NEWS_PROMPT_VERSION,
            "meta": dict(meta or {}),
            "payload": payload,
        }
        if len(data) > 30:
            rows = sorted(data.items(), key=lambda kv: int((kv[1] or {}).get("saved_at") or 0),
                          reverse=True)[:30]
            data = dict(rows)
        with open(_ai_cache_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


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
    normalize_report(report)
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
    """把报告（v1/v2 均可）导出为带分类、评分与理由的 Markdown"""
    rep = normalize_report(report or {})
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
            meta = []
            if it.get("score"):
                meta.append("%s 分" % it["score"])
            if it.get("why"):
                meta.append(str(it["why"]))
            if meta:
                lines.append("  > %s" % " · ".join(meta))
            for rel in it.get("related") or []:
                if rel.get("url"):
                    lines.append("  - 相关来源：[%s](%s) — %s"
                                 % (rel.get("title") or "链接", rel["url"],
                                    rel.get("source") or ""))
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
