# -*- coding: utf-8 -*-
"""skills.sh 详情抓取 + 仓库归档提取（无需 GitHub Token）。

用于「发现」页展示技能内容/优势，以及一键安装时把仓库里的
目标 skill 目录取出来。网络失败只抛出 SkillShError，由上层转成提示。
"""
from __future__ import annotations

import html as html_mod
import io
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

TARBALL_LIMIT = 30 * 1024 * 1024  # 30 MB，超出则提示改用 npx 命令
DETAIL_TTL = 600

_DETAIL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class SkillShError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _strip_tags(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|li|h[1-6]|div)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (AgentFloat Skills Workshop)",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data.decode("utf-8", "replace")


def _summary_bullets(html_text: str) -> list:
    m = re.search(r">Summary<.*?<ul[^>]*>(.*?)</ul>", html_text, re.S)
    if not m:
        return []
    bullets = re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)
    out = []
    for b in bullets:
        clean = _strip_tags(b)
        if clean:
            out.append(clean[:300])
    return out[:8]


def _skill_md_text(html_text: str) -> str:
    i = html_text.find(">SKILL.md<")
    if i < 0:
        return ""
    chunk = html_text[i:i + 60000]
    m = re.search(r'<div class="prose[^"]*">(.*?)</div>\s*</div>', chunk, re.S)
    body = m.group(1) if m else chunk
    text = _strip_tags(body)
    # 去掉导航/页脚噪声
    for cut in ("Browse All skills", "Related skills", "Installation"):
        j = text.find(cut)
        if j > 200:
            text = text[:j]
    return text.strip()[:6000]


def _meta_number(html_text: str, label: str) -> str:
    m = re.search(re.escape(label) + r".{0,400}?font-mono[^>]*>\s*([0-9][0-9.,]*\s*[KMB]?)\s*<",
                  html_text, re.S)
    return m.group(1).strip() if m else ""


def _audits(html_text: str) -> list:
    m = re.search(r">Security Audits<(.{0,3000}?)(?:Browse All|</section>)", html_text, re.S)
    if not m:
        return []
    chunk = m.group(1)
    rows = re.findall(
        r">([A-Za-z][A-Za-z0-9 .&-]{2,40})</[^>]+>.{0,200}?>(Pass|Warn|Fail|Pending)<",
        chunk, re.S,
    )
    seen, out = set(), []
    for name, status in rows:
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name.strip(), "status": status})
    return out[:6]


def fetch_detail(source: str, slug: str, use_cache: bool = True) -> Dict[str, Any]:
    source = str(source or "").strip().strip("/")
    slug = str(slug or "").strip()
    if not _SOURCE_RE.match(source) or not _SLUG_RE.match(slug):
        raise SkillShError("invalid", "非法的 skill 标识")
    key = "%s/%s" % (source, slug)
    now = time.time()
    if use_cache:
        hit = _DETAIL_CACHE.get(key)
        if hit and now - hit[0] < DETAIL_TTL:
            return hit[1]
    url = "https://skills.sh/%s" % key
    try:
        html_text = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        raise SkillShError("fetch_failed", "读取 skills.sh 失败：%s" % exc)
    summary = _summary_bullets(html_text)
    skill_md = _skill_md_text(html_text)
    plain = _strip_tags(html_text)
    stars = _meta_number(html_text, "GitHub Stars")
    if not stars:
        sm = re.search(r"GitHub Stars\s*([0-9][0-9.,]*\s*[KMB]?)", plain)
        stars = sm.group(1).strip() if sm else ""
    installs = _meta_number(html_text, "Installs")
    if not installs:
        im = re.search(r"\bInstalls\s*([0-9][0-9.,]*\s*[KMB]?)", plain)
        installs = im.group(1).strip() if im else ""
    data = {
        "ok": True,
        "source": source,
        "slug": slug,
        "url": url,
        "summary": summary,
        "skillMd": skill_md,
        "stars": stars,
        "installs": installs,
        "audits": _audits(html_text),
        "installCommand": "npx skills add https://github.com/%s --skill %s" % (source, slug),
    }
    # 摘要兜底：SKILL.md 前几段
    if not data["summary"] and skill_md:
        paras = [p.strip() for p in skill_md.split("\n") if p.strip()]
        data["summary"] = [p[:300] for p in paras[1:5]]
    _DETAIL_CACHE[key] = (now, data)
    return data


def _download_tarball(source: str, ref: str = "") -> bytes:
    last_err: Optional[Exception] = None
    refs = [("", str(ref or "").strip())] if str(ref or "").strip() else [("refs/heads/", b) for b in ("main", "master")]
    for prefix, branch in refs:
        url = "https://codeload.github.com/%s/tar.gz/%s%s" % (source, prefix, branch)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AgentFloat"})
            buf = io.BytesIO()
            with urllib.request.urlopen(req, timeout=60) as resp:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    buf.write(chunk)
                    if buf.tell() > TARBALL_LIMIT:
                        raise SkillShError(
                            "too_large",
                            "仓库超过 %d MB，请在终端运行 npx 命令安装" % (TARBALL_LIMIT // 1024 // 1024),
                        )
            return buf.getvalue()
        except SkillShError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise SkillShError("download_failed", "下载仓库失败：%s" % last_err)


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    fh = tar.extractfile(member)
    if not fh:
        return ""
    return fh.read(200000).decode("utf-8", "replace")


def _frontmatter_name(text: str) -> str:
    m = re.search(r"^---\s*\n(.*?)\n---", text or "", re.S)
    if not m:
        return ""
    nm = re.search(r"^name\s*:\s*(.+)$", m.group(1), re.M)
    return nm.group(1).strip().strip('"\'') if nm else ""


def _pick_member(tar: tarfile.TarFile, members: list, slug: str, name: str) -> Optional[tarfile.TarInfo]:
    wanted = {(slug or "").lower(), (name or "").lower()}
    wanted.discard("")
    candidates = []
    for mem in members:
        if not mem.isfile() or not mem.name.endswith("/SKILL.md"):
            continue
        folder = mem.name.rsplit("/SKILL.md", 1)[0]
        base = folder.rsplit("/", 1)[-1].lower()
        candidates.append((mem, folder, base))
    if not candidates:
        return None
    for mem, folder, base in candidates:
        if base in wanted:
            return mem
    for mem, folder, base in candidates:
        try:
            fm = _frontmatter_name(_read_member(tar, mem))
        except Exception:  # noqa: BLE001
            fm = ""
        if fm and fm.lower() in wanted:
            return mem
    if len(candidates) == 1:
        return candidates[0][0]
    for mem, folder, base in candidates:
        if slug.lower() in folder.lower():
            return mem
    return None


def _safe_extract(tar: tarfile.TarFile, prefix: str, dest: str) -> None:
    base = os.path.abspath(dest)
    for mem in tar.getmembers():
        if not mem.name.startswith(prefix):
            continue
        rel = mem.name[len(prefix):].lstrip("/")
        if not rel:
            continue
        target = os.path.abspath(os.path.join(base, *rel.split("/")))
        if not (target == base or target.startswith(base + os.sep)):
            continue
        if mem.isdir():
            os.makedirs(target, exist_ok=True)
            continue
        if not mem.isfile():
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fh = tar.extractfile(mem)
        if not fh:
            continue
        with open(target, "wb") as out:
            shutil.copyfileobj(fh, out)


def materialize(source: str, slug: str, name: str = "", ref: str = "") -> Tuple[str, Dict[str, Any]]:
    """下载仓库并提取目标 skill 目录，返回 (临时目录, 元信息)。"""
    source = str(source or "").strip().strip("/")
    slug = str(slug or "").strip()
    if not _SOURCE_RE.match(source) or not _SLUG_RE.match(slug):
        raise SkillShError("invalid", "非法的 skill 标识")
    blob = _download_tarball(source, ref)
    tmp = tempfile.mkdtemp(prefix="agentfloat-skillsh-")
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            members = tar.getmembers()
            target = _pick_member(tar, members, slug, name)
            if target is None:
                raise SkillShError("not_found", "仓库中未找到该 skill 的 SKILL.md")
            folder = target.name.rsplit("/SKILL.md", 1)[0]
            prefix = folder + "/"
            dest = os.path.join(tmp, "skill")
            os.makedirs(dest, exist_ok=True)
            _safe_extract(tar, prefix, dest)
            skill_md = _read_member(tar, target)
            root_lic_name = ""
            root_lic_text = ""
            for mem in members:
                base = mem.name.rsplit("/", 1)[-1].upper()
                if mem.isfile() and base in ("LICENSE", "LICENSE.MD", "LICENSE.TXT", "COPYING", "NOTICE"):
                    root_lic_name = mem.name.rsplit("/", 1)[-1]
                    root_lic_text = _read_member(tar, mem)
                    break
        if not os.path.isfile(os.path.join(dest, "SKILL.md")):
            raise SkillShError("not_found", "提取后缺少 SKILL.md")
        desc = ""
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", skill_md or "", flags=re.S)
        paras = [p.strip() for p in _strip_tags(body).split("\n") if p.strip()]
        for p in paras:
            if not p.startswith("#") and len(p) > 20:
                desc = p[:300]
                break
        lic_name = ""
        lic_text = ""
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE"):
            path = os.path.join(dest, name)
            if os.path.isfile(path):
                lic_name = name
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lic_text = fh.read(6000)
                break
        if not lic_text:
            lic_name = root_lic_name
            lic_text = root_lic_text
        lic_label = ""
        if lic_text or lic_name:
            from agentfloat.services.skills import bundle as _bundle
            lic_label = _bundle._license_label(lic_text, lic_name)
        meta = {"folder": folder, "description": desc, "source": source, "slug": slug,
                "license": lic_label}
        return dest, meta
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
