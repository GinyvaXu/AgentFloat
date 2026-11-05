# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 发现层（GitHub / 周榜 / Awesome / 粘贴 URL）

C1 要求的四条发现路径都在这里，统一走可注入的 ``Fetcher``：
- GitHub 搜索（关键词 + stars 排序）
- 周榜（最近 7 天有 push 的仓库，按热度/活跃排序）
- Awesome 精选（解析 README 里的 GitHub 链接）
- 用户粘贴 URL（仓库 / 子目录 / SKILL.md 链接）

网络层只使用标准库 ``urllib``，不引入第三方依赖。所有失败都归类为
``SourceError``，单个仓库失败不会拖垮整次发现（调用方逐条降级）。

安全：下载只读取文本/字节并落盘到暂存目录；**从不执行仓库脚本**。
安装阶段要求 40 位固定 commit，见 ``installer`` / ``workshop``。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from agentfloat.services.skills import metadata
from agentfloat.services.skills.models import (
    SkillEntry, SkillSource, as_int, canonical_entry_id, now_iso,
)

GITHUB_API = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"
USER_AGENT = "AgentFloat-SkillWorkshop/1.0"
DEFAULT_TIMEOUT = 10
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_TREE_FILES = 120
MAX_SKILL_BYTES = 120 * 1024
HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

#: Awesome 源（按顺序尝试；任意一个可用即可）
AWESOME_REPOS = (
    "travisvn/awesome-claude-skills",
    "hesreallyhim/awesome-claude-code",
)
AWESOME_URL_RE = re.compile(
    r"\[[^\]]{1,120}\]\((https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^\s)]*)?)\)")


class SourceError(Exception):
    """发现/下载错误：code 用于 UI 分流，message 是可直接展示的中文。"""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = str(code or "source_error")
        self.message = str(message or "发现失败")
        self.detail = str(detail or "")

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "error": self.message, "detail": self.detail}


class Fetcher:
    """网络抓取接口（可注入假实现做纯单测）。"""

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        raise NotImplementedError

    def get_text(self, url: str) -> str:
        raise NotImplementedError

    def get_bytes(self, url: str) -> bytes:
        raise NotImplementedError


class UrllibFetcher(Fetcher):
    """标准库实现；可选 ``GITHUB_TOKEN`` 环境变量（只放请求头，不写日志）。"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, token: Optional[str] = None):
        self.timeout = max(2, int(timeout or DEFAULT_TIMEOUT))
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")

    def _request(self, url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
        req = urllib.request.Request(url, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = "rate_limited" if exc.code in (403, 429) else "http_error"
            msg = "GitHub 请求失败（HTTP %s）" % exc.code
            if exc.code in (403, 429):
                msg = "GitHub 接口限流或拒绝访问（可配置 GITHUB_TOKEN 后重试）"
            elif exc.code == 404:
                msg = "仓库或文件不存在（HTTP 404）"
            raise SourceError(code, msg, str(exc))
        except urllib.error.URLError as exc:
            raise SourceError("network_error", "网络连接失败（检查代理/网络）：%s" % exc.reason)
        except TimeoutError:
            raise SourceError("timeout", "网络请求超时（%d 秒）" % self.timeout)
        if len(data) > MAX_RESPONSE_BYTES:
            raise SourceError("response_too_large", "远程内容超过 4MB，已拒绝")
        return data

    def _headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        out = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            out["Authorization"] = "Bearer %s" % self.token
        if headers:
            out.update({str(k): str(v) for k, v in headers.items()})
        return out

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        data = self._request(url, headers=headers)
        try:
            return json.loads(data.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise SourceError("bad_json", "远程返回的不是合法 JSON", str(exc))

    def get_text(self, url: str) -> str:
        return self._request(url).decode("utf-8", errors="replace")

    def get_bytes(self, url: str) -> bytes:
        return self._request(url)


def default_fetcher() -> Fetcher:
    return UrllibFetcher()


# ── URL 解析 ─────────────────────────────────────────
def _clean_subpath(path: str) -> str:
    text = urllib.parse.unquote(str(path or "")).strip().strip("/")
    if not text:
        return ""
    parts = []
    for part in text.replace("\\", "/").split("/"):
        if part in ("", ".", ".."):
            raise SourceError("bad_url", "URL 路径包含非法片段")
        if any(ord(ch) < 32 for ch in part) or ":" in part:
            raise SourceError("bad_url", "URL 路径包含非法字符")
        parts.append(part)
    return "/".join(parts)


def parse_github_url(url: str) -> Dict[str, str]:
    """解析 GitHub 链接，返回 ``{repo, subpath, ref, url}``。

    支持：仓库主页、``/tree/<ref>/<path>``、``/blob/<ref>/<path>/SKILL.md``、
    ``git@github.com:owner/repo.git``、raw.githubusercontent.com 链接。
    """
    text = str(url or "").strip()
    if not text:
        raise SourceError("bad_url", "请粘贴 GitHub 仓库或 Skill 目录链接")
    if text.startswith("git@github.com:"):
        text = "https://github.com/" + text[len("git@github.com:"):]
    if text.startswith("github.com/"):
        text = "https://" + text
    parsed = urllib.parse.urlsplit(text)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in ("github.com", "raw.githubusercontent.com"):
        raise SourceError("bad_url", "只支持 GitHub 链接（github.com）")
    if parsed.username or parsed.password:
        raise SourceError("bad_url", "链接不能包含账号密码")
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        raise SourceError("bad_url", "链接里没有仓库名")
    if host == "raw.githubusercontent.com":
        if len(parts) < 3:
            raise SourceError("bad_url", "raw 链接缺少仓库或 ref")
        repo = "%s/%s" % (parts[0], parts[1])
        ref = parts[2]
        rest = parts[3:]
        subpath = ""
        if rest:
            if rest[-1].lower() == "skill.md":
                rest = rest[:-1]
            subpath = _clean_subpath("/".join(rest))
        return _parsed(repo, subpath, ref, text)
    repo = "%s/%s" % (parts[0], parts[1])
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not REPO_RE.match(repo):
        raise SourceError("bad_url", "仓库名格式不正确")
    ref = ""
    subpath = ""
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        ref = parts[3]
        rest = parts[4:]
        if parts[2] == "blob":
            if not rest or rest[-1].lower() != "skill.md":
                raise SourceError("bad_url", "blob 链接必须指向 SKILL.md")
            rest = rest[:-1]
        subpath = _clean_subpath("/".join(rest))
    return _parsed(repo, subpath, ref, text)


def _parsed(repo: str, subpath: str, ref: str, url: str) -> Dict[str, str]:
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    if not REPO_RE.match(repo):
        raise SourceError("bad_url", "仓库名格式不正确")
    return {
        "repo": repo,
        "subpath": subpath,
        "ref": ref or "",
        "url": "https://github.com/%s" % repo + (
            "/tree/%s/%s" % (ref, subpath) if ref and subpath else ""),
        "raw_url": url,
    }


def parse_awesome_readme(text: str, limit: int = 40) -> List[str]:
    """从 Awesome README 提取 GitHub 仓库链接（去重、过滤自身/非仓库）。"""
    out: List[str] = []
    seen = set()
    for m in AWESOME_URL_RE.finditer(text or ""):
        try:
            parsed = parse_github_url(m.group(1))
        except SourceError:
            continue
        repo = parsed["repo"]
        key = repo.lower()
        if key in seen or key.endswith("/awesome-claude-skills") or key.endswith(
                "/awesome-claude-code"):
            continue
        seen.add(key)
        out.append(repo)
        if len(out) >= limit:
            break
    return out


# ── GitHub API ───────────────────────────────────────
def _api(path: str) -> str:
    return GITHUB_API + path


def _repo_meta(repo: str, fetcher: Fetcher) -> Dict[str, Any]:
    if not REPO_RE.match(str(repo or "")):
        raise SourceError("bad_repo", "仓库名格式不正确")
    data = fetcher.get_json(_api("/repos/%s" % repo))
    if not isinstance(data, dict):
        raise SourceError("bad_response", "仓库信息格式异常")
    license_info = data.get("license") if isinstance(data.get("license"), dict) else {}
    return {
        "repo": data.get("full_name") or repo,
        "url": data.get("html_url") or ("https://github.com/%s" % repo),
        "stars": as_int(data.get("stargazers_count")),
        "pushed_at": str(data.get("pushed_at") or ""),
        "default_branch": str(data.get("default_branch") or "main"),
        "license": str(license_info.get("spdx_id") or license_info.get("name") or ""),
        "description": str(data.get("description") or ""),
        "archived": bool(data.get("archived")),
        "topics": [str(x) for x in (data.get("topics") or [])],
    }


def resolve_commit(repo: str, ref: str, fetcher: Fetcher) -> str:
    """把分支/tag 解析成固定 commit；已传入 40 位 SHA 时直接返回。"""
    text = str(ref or "").strip()
    if HEX40_RE.match(text):
        return text.lower()
    data = fetcher.get_json(_api("/repos/%s/commits/%s" % (
        repo, urllib.parse.quote(text or "HEAD"))))
    sha = str((data or {}).get("sha") or "") if isinstance(data, dict) else ""
    if not HEX40_RE.match(sha):
        raise SourceError("commit_missing", "无法解析仓库的固定 commit")
    return sha.lower()


def list_tree(repo: str, ref: str, fetcher: Fetcher) -> Dict[str, Any]:
    """读取仓库文件树；返回 ``{files: [...], truncated: bool, sha: ...}``。"""
    data = fetcher.get_json(_api("/repos/%s/git/trees/%s?recursive=1" % (
        repo, urllib.parse.quote(str(ref or "HEAD")))))
    if not isinstance(data, dict):
        raise SourceError("bad_response", "仓库文件树格式异常")
    files = []
    for item in data.get("tree") or []:
        if not isinstance(item, dict):
            continue
        files.append({
            "path": str(item.get("path") or ""),
            "type": str(item.get("type") or ""),
            "mode": str(item.get("mode") or ""),
            "size": as_int(item.get("size")),
            "sha": str(item.get("sha") or ""),
        })
    return {"files": files, "truncated": bool(data.get("truncated")), "sha": str(data.get("sha") or "")}


def skill_dirs_from_tree(tree: Dict[str, Any], subpath: str = "",
                         max_skills: int = 30) -> List[str]:
    """从文件树里找 Skill 目录（含 SKILL.md 的目录，忽略根目录之外的危险段）。"""
    base = _clean_subpath(subpath) if subpath else ""
    prefix = (base + "/") if base else ""
    out: List[str] = []
    seen = set()
    for item in (tree or {}).get("files") or []:
        path = str(item.get("path") or "")
        if item.get("type") != "blob" or not path.lower().endswith("/skill.md") and path.lower() != "skill.md":
            continue
        if not path.lower().endswith("skill.md"):
            continue
        if prefix and not path.startswith(prefix):
            continue
        rel = path[len(prefix):] if prefix else path
        if rel.lower() == "skill.md":
            directory = base
        elif rel.lower().endswith("/skill.md"):
            directory = (prefix + rel[:-len("/SKILL.md")]).strip("/")
        else:
            continue
        try:
            directory = _clean_subpath(directory)
        except SourceError:
            continue
        if directory.lower() in seen:
            continue
        seen.add(directory.lower())
        out.append(directory)
        if len(out) >= max(1, int(max_skills)):
            break
    return out


def raw_url(repo: str, ref: str, path: str) -> str:
    path = _clean_subpath(path)
    return "%s/%s/%s/%s" % (RAW_HOST, repo, urllib.parse.quote(str(ref)), path)


def read_raw(repo: str, ref: str, path: str, fetcher: Fetcher) -> str:
    text = fetcher.get_text(raw_url(repo, ref, path))
    if len(text) > MAX_SKILL_BYTES:
        text = text[:MAX_SKILL_BYTES]
    return text


def _skill_entry_from_md(repo: str, meta: Dict[str, Any], subpath: str, commit: str,
                         text: str, source_type: str = "github") -> SkillEntry:
    name_hint = os.path.basename(subpath.rstrip("/")) if subpath else repo.split("/")[-1]
    md = metadata.metadata_from_text(text, name_hint=name_hint, root=subpath)
    entry_id = canonical_entry_id(source_type, md.get("name") or name_hint,
                                  repo=repo, subpath=subpath)
    trust = 0.92 if source_type == "awesome" else 0.72
    source = SkillSource(
        type=source_type,
        repo=repo,
        subpath=subpath,
        url=meta.get("url") or ("https://github.com/%s" % repo),
        commit=commit,
        license=str(meta.get("license") or ""),
        stars=as_int(meta.get("stars")),
        pushed_at=str(meta.get("pushed_at") or ""),
        trust=trust,
        verified=bool(commit),
    )
    return SkillEntry(
        entry_id=entry_id,
        name=str(md.get("name") or name_hint),
        description=str(md.get("description") or meta.get("description") or ""),
        category=str(md.get("category") or "其他"),
        version=str(md.get("version") or ""),
        trigger=str(md.get("trigger") or ""),
        trigger_doc=str(md.get("trigger_doc") or ""),
        has_manual_trigger=bool(md.get("has_manual_trigger")),
        dependencies=list(md.get("dependencies") or []),
        tags=list(md.get("tags") or []) or list(meta.get("topics") or [])[:5],
        source=source,
        has_skill_md=True,
        latest_commit=commit,
    )


def expand_repo(repo: str, fetcher: Optional[Fetcher] = None, source_type: str = "github",
                ref: str = "", subpath: str = "", max_skills: int = 12) -> Dict[str, Any]:
    """把一个仓库展开成 SkillEntry 列表；单仓库内单个 SKILL.md 失败只跳过该项。"""
    f = fetcher or default_fetcher()
    meta = _repo_meta(repo, f)
    target_ref = ref or meta.get("default_branch") or "main"
    commit = resolve_commit(repo, target_ref, f)
    tree = list_tree(repo, commit, f)
    if tree.get("truncated"):
        raise SourceError("tree_truncated", "仓库文件树过大（GitHub 截断），请粘贴具体 Skill 目录")
    dirs = skill_dirs_from_tree(tree, subpath=subpath, max_skills=max_skills)
    entries = []
    warnings = []
    for directory in dirs:
        md_path = (directory + "/SKILL.md") if directory else "SKILL.md"
        try:
            text = read_raw(repo, commit, md_path, f)
            entries.append(_skill_entry_from_md(repo, meta, directory, commit, text,
                                                source_type=source_type))
        except SourceError as exc:
            warnings.append("跳过 %s：%s" % (directory or "(根目录)", exc.message))
    if not entries:
        raise SourceError(
            "not_a_skill",
            "该仓库未找到 SKILL.md；Skill 车间首版只安装 Skill，MCP/插件请按官方命令手动配置",
        )
    return {"ok": True, "repo": repo, "commit": commit, "entries": entries,
            "warnings": warnings, "meta": meta}


def search_repositories(query: str, limit: int = 20, weekly: bool = False,
                        fetcher: Optional[Fetcher] = None) -> List[Dict[str, Any]]:
    """GitHub 仓库搜索；``weekly=True`` 时限定最近 7 天有 push。"""
    f = fetcher or default_fetcher()
    q = str(query or "").strip() or "agent skill"
    q = "%s in:name,description,readme" % q
    if weekly:
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
        q += " pushed:>=%s" % since
    per_page = max(1, min(50, int(limit or 20)))
    url = _api("/search/repositories?q=%s&sort=stars&order=desc&per_page=%d" % (
        urllib.parse.quote(q), per_page))
    data = f.get_json(url)
    items = (data or {}).get("items") if isinstance(data, dict) else None
    return [x for x in (items or []) if isinstance(x, dict)]


def discover(query: str = "", mode: str = "search", limit: int = 12,
             fetcher: Optional[Fetcher] = None, subpath: str = "",
             ref: str = "") -> Dict[str, Any]:
    """四条发现路径的统一入口。

    返回 ``{ok, mode, entries, warnings, sources, fetchedAt}``；
    任何单仓库失败只进 warnings，不影响其他结果。
    """
    f = fetcher or default_fetcher()
    mode = str(mode or "search").strip().lower()
    limit = max(1, min(30, int(limit or 12)))
    warnings: List[str] = []
    entries: List[SkillEntry] = []
    sources: List[Dict[str, Any]] = []

    if mode == "url":
        parsed = parse_github_url(query)
        repo = parsed["repo"]
        _sources_add(sources, "url", repo)
        result = expand_repo(repo, f, source_type="url", ref=ref or parsed.get("ref") or "",
                             subpath=subpath or parsed.get("subpath") or "",
                             max_skills=limit)
        entries.extend(result["entries"])
        warnings.extend(result.get("warnings") or [])
    elif mode == "awesome":
        links = _awesome_links(f, warnings)
        _sources_add(sources, "awesome", "精选列表")
        for repo in links[:max(1, min(8, limit))]:
            try:
                result = expand_repo(repo, f, source_type="awesome", max_skills=3)
                entries.extend(result["entries"])
                warnings.extend(result.get("warnings") or [])
            except SourceError as exc:
                warnings.append("精选仓库 %s 跳过：%s" % (repo, exc.message))
    else:
        weekly = mode == "weekly"
        repos = search_repositories(query, limit=max(6, limit), weekly=weekly, fetcher=f)
        _sources_add(sources, "weekly" if weekly else "search",
                     "GitHub 周榜" if weekly else "GitHub 搜索")
        for item in repos[:max(1, min(8, limit))]:
            repo = str(item.get("full_name") or "")
            if not REPO_RE.match(repo):
                continue
            try:
                result = expand_repo(repo, f, source_type="github", max_skills=4)
                entries.extend(result["entries"])
                warnings.extend(result.get("warnings") or [])
            except SourceError as exc:
                warnings.append("仓库 %s 跳过：%s" % (repo, exc.message))

    # 统一去重（同仓库同目录）
    dedup: Dict[str, SkillEntry] = {}
    for entry in entries:
        dedup[entry.entry_id] = entry
    return {
        "ok": True,
        "mode": mode,
        "entries": list(dedup.values()),
        "warnings": warnings,
        "sources": sources,
        "fetchedAt": now_iso(),
    }


def _sources_add(sources: List[Dict[str, Any]], key: str, label: str) -> None:
    sources.append({"key": key, "label": label, "ok": True})


def _awesome_links(fetcher: Fetcher, warnings: List[str]) -> List[str]:
    for repo in AWESOME_REPOS:
        try:
            meta = _repo_meta(repo, fetcher)
            text = read_raw(repo, meta.get("default_branch") or "main", "README.md", fetcher)
            links = parse_awesome_readme(text, limit=30)
            if links:
                return links
        except SourceError as exc:
            warnings.append("精选源 %s 暂不可用：%s" % (repo, exc.message))
    return []


# ── README / 下载 ────────────────────────────────────
def read_readme(entry: SkillEntry, fetcher: Optional[Fetcher] = None) -> str:
    """按需读取 README（Skill 目录优先，回退仓库根 README / SKILL.md）。"""
    if entry.readme:
        return entry.readme
    f = fetcher or default_fetcher()
    src = entry.source
    if not src.repo:
        return ""
    ref = src.commit or "HEAD"
    candidates = []
    if src.subpath:
        candidates.append(src.subpath + "/README.md")
        candidates.append(src.subpath + "/SKILL.md")
    candidates += ["README.md", "SKILL.md"]
    for path in candidates:
        try:
            text = read_raw(src.repo, ref, path, f)
            if text.strip():
                return text
        except SourceError:
            continue
    return ""


def materialize(entry: SkillEntry, dest: str,
                fetcher: Optional[Fetcher] = None) -> Dict[str, Any]:
    """把条目内容下载到暂存目录。

    - 本地来源：复制 ``source.local_path``（或已安装目录）；
    - 远程来源：必须 40 位 commit，逐文件从 raw 下载；不执行任何脚本。
    """
    src = entry.source
    os.makedirs(dest, exist_ok=True)
    if src.type == "local" or src.local_path:
        source = src.local_path
        if not source:
            for inst in entry.installed:
                if os.path.isdir(inst.path):
                    source = inst.path
                    break
        if not source or not os.path.isdir(source):
            raise SourceError("source_missing", "本地 Skill 目录不存在")
        shutil.copytree(source, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".agentfloat-skill.json"))
        return {"ok": True, "path": dest, "files": 0, "commit": "", "source": "local"}

    repo = src.repo
    commit = src.commit or ""
    if not HEX40_RE.match(commit):
        raise SourceError(
            "commit_required",
            "远程安装必须固定 commit（不允许直接装 HEAD）；请刷新条目后重试",
        )
    f = fetcher or default_fetcher()
    tree = list_tree(repo, commit, f)
    if tree.get("truncated"):
        raise SourceError("tree_truncated", "仓库文件树过大，无法安全安装")
    base = src.subpath.strip("/")
    prefix = (base + "/") if base else ""
    files = []
    for item in tree.get("files") or []:
        path = str(item.get("path") or "")
        if item.get("type") != "blob":
            continue
        if item.get("mode") in ("120000", "160000"):
            raise SourceError("symlink_blocked", "仓库包含符号链接/子模块，已拒绝安装")
        if prefix and not path.startswith(prefix):
            continue
        rel = path[len(prefix):] if prefix else path
        if not rel or rel.startswith(".git/"):
            continue
        files.append((rel, path))
        if len(files) > MAX_TREE_FILES:
            raise SourceError("too_many_files", "Skill 文件数超过 %d 个" % MAX_TREE_FILES)
    if not any(rel.lower() == "skill.md" for rel, _ in files):
        raise SourceError("skill_md_missing", "该目录缺少 SKILL.md，未识别为 Skill")
    total = 0
    for rel, remote_path in files:
        try:
            blob = f.get_bytes(raw_url(repo, commit, remote_path))
        except SourceError as exc:
            raise SourceError("download_failed", "下载 %s 失败：%s" % (rel, exc.message))
        total += len(blob)
        if total > 20 * 1024 * 1024:
            raise SourceError("source_too_large", "Skill 内容超过 20MB，已拒绝")
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(blob)
    return {"ok": True, "path": dest, "files": len(files), "commit": commit,
            "source": "github"}


# ── skills.sh 公开榜单（HTML 解析，无需 Token）────────────────

SKILLSH_VIEWS = {"all-time": "", "trending": "trending", "hot": "hot"}
SKILLSH_LINK_RE = re.compile(
    r'<a[^>]+href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"[^>]*>(.*?)</a>',
    re.S,
)
SKILLSH_NAME_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
SKILLSH_SRC_RE = re.compile(r"<p[^>]*>\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\s*</p>", re.S)
SKILLSH_INSTALLS_RE = re.compile(
    r'<span class="font-mono text-sm text-foreground">\s*([\d.,]+[KMB]?)\s*</span>'
)
SKILLSH_RANK_RE = re.compile(r'font-mono">\s*(\d+)\s*</span>')

SKILLSH_CATEGORY_HINTS = (
    ("视频与动效", ("video", "animation", "motion", "frame", "audio", "music",
                 "slideshow", "hyperframe", "avatar", "imagegen", "image-generation")),
    ("设计与前端", ("design", "ui-", "-ui", "ux", "frontend", "react", "next", "mobile",
                 "ios", "css", "tailwind", "shadcn", "figma", "taste", "visual")),
    ("数据与后端", ("database", "postgres", "prisma", "supabase", "neon", "backend",
                 "api", "sql", "driver")),
    ("增长与文案", ("seo", "copywriting", "marketing", "social", "twitter", "reddit",
                 "content", "brand", "launch")),
    ("质量与测试", ("test", "review", "debug", "audit", "security", "lint", "verify")),
    ("企业与办公", ("azure", "lark", "feishu", "google", "microsoft", "office",
                 "doc", "slide", "sheet", "notion")),
    ("Agent 工作流", ("agent", "skill", "workflow", "subagent", "handoff", "plan",
                    "grill", "brainstorm", "spec", "implement")),
)


def _skillsh_category(name: str, source: str) -> str:
    text = ("%s %s" % (name or "", source or "")).lower()
    for label, keys in SKILLSH_CATEGORY_HINTS:
        if any(k in text for k in keys):
            return label
    return "其他"


def _parse_installs(text: str) -> int:
    raw = (text or "").strip().upper().replace(",", "")
    if not raw:
        return 0
    mult = 1
    if raw.endswith("K"):
        mult, raw = 1000, raw[:-1]
    elif raw.endswith("M"):
        mult, raw = 1000000, raw[:-1]
    elif raw.endswith("B"):
        mult, raw = 1000000000, raw[:-1]
    try:
        return int(float(raw) * mult)
    except ValueError:
        return 0


def fetch_skills_sh(view: str = "trending", limit: int = 60,
                    fetcher: Optional[Fetcher] = None) -> List[Dict[str, Any]]:
    """抓取 skills.sh 公开榜单（HTML），返回技能条目列表。

    不依赖 GitHub API，也不需要 Token；仅用于“发现/榜单”展示。
    """
    f = fetcher or default_fetcher()
    path = SKILLSH_VIEWS.get(str(view or "trending"), "trending")
    url = "https://skills.sh/" + path
    html = f.get_text(url)
    out: List[Dict[str, Any]] = []
    seen = set()
    for match in SKILLSH_LINK_RE.finditer(html or ""):
        href, block = match.group(1), match.group(2)
        parts = href.split("/")
        if len(parts) != 3:
            continue
        source = "/".join(parts[:2])
        slug = parts[2]
        name_m = SKILLSH_NAME_RE.search(block)
        src_m = SKILLSH_SRC_RE.search(block)
        if not name_m or not src_m:
            continue
        key = "%s/%s" % (source, slug)
        if key in seen:
            continue
        seen.add(key)
        inst = SKILLSH_INSTALLS_RE.search(block)
        rank = SKILLSH_RANK_RE.search(block)
        name = re.sub(r"<[^>]+>", "", name_m.group(1)).strip()
        installs_text = inst.group(1) if inst else ""
        out.append({
            "id": key,
            "name": name or slug,
            "slug": slug,
            "source": src_m.group(1),
            "installs": _parse_installs(installs_text),
            "installsText": installs_text,
            "rank": int(rank.group(1)) if rank else len(out) + 1,
            "category": _skillsh_category(name, source),
            "url": "https://skills.sh/%s" % key,
            "installUrl": "https://github.com/%s" % src_m.group(1),
            "installCommand": "npx skills add %s" % src_m.group(1),
        })
        if len(out) >= max(1, int(limit or 60)):
            break
    return out
