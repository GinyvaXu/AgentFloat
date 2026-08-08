# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 本地 AI 服务对接

使用用户配置的主 Agent（点击浮窗启动的那一个）以非交互（headless）模式，
自动完成 AgentFloat 的待处理服务：
  1. API 用量端点配置校验 / 补全（含 DeepSeek 等常见平台）
  2. Skills 查找与中英翻译补全

首次启动自动运行一次（config.services.ai_first_run_done 标记），
之后可在「设置 → Skills 辅助 → AI 自检服务」中再次手动运行。

安全策略：Agent 只负责「读取配置并输出结构化 JSON」，所有文件写入
（config.json / 翻译文件）均由本模块校验后自行完成。
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

from agent_registry import resolve_command
from api_monitor_config import validate_endpoint, DEFAULTS as API_MONITOR_DEFAULTS
from skills_translations import SKILL_ZH, _ALIAS

SERVICE_TIMEOUT_SECONDS = 600

logger = logging.getLogger("AgentFloat.LocalAI")


def _config_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_config_dir(), "config.json")
CUSTOM_TRANSLATIONS_PATH = os.path.join(_config_dir(), "skills_translations_ai.json")


# ── headless 命令构建 ──────────────────────────────
def build_headless_command(agent, prompt):
    """构造非交互执行命令（首个元素为解析后的真实路径）"""
    cmd_path, err = resolve_command(agent)
    if cmd_path is None:
        return None, err
    base = os.path.basename(cmd_path).lower()
    mode = agent.get("launch_mode", "normal")
    skip = (agent.get("skip_permissions_arg") or "").strip()
    args = [cmd_path]
    if "claude" in base:
        args += ["-p", prompt, "--output-format", "text", "--max-turns", "30"]
        if mode == "skip_permissions" and skip:
            args.append(skip)
    elif "codex" in base:
        args += ["exec", "--skip-git-repo-check", prompt]
        if mode == "skip_permissions" and skip:
            args.append(skip)
    else:
        # 通用兜底：多数 CLI agent 支持 -p/--print 打印模式
        args += ["-p", prompt]
        if mode == "skip_permissions" and skip:
            args.append(skip)
    return args, None


def _run_headless(agent, prompt, cancel=None):
    """执行 headless 命令；cancel 为可选 threading.Event，置位时终止子进程"""
    args, err = build_headless_command(agent, prompt)
    if args is None:
        return None, err
    working = (agent.get("working_directory") or "").strip()
    if not working or not os.path.isdir(working):
        working = os.path.expanduser("~")
    flags = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
             "text": True, "encoding": "utf-8", "errors": "replace", "cwd": working}
    if sys.platform == "win32":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(args, **flags)
    except Exception as e:
        return None, str(e)
    deadline = time.time() + SERVICE_TIMEOUT_SECONDS
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.kill()
                try:
                    proc.wait(5)
                except Exception:
                    pass
                return None, "用户退出，任务已取消"
            if time.time() > deadline:
                proc.kill()
                try:
                    proc.wait(5)
                except Exception:
                    pass
                return None, "执行超时（%d 秒）" % SERVICE_TIMEOUT_SECONDS
            time.sleep(0.3)
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return None, str(e)
    out = proc.stdout.read() if proc.stdout else ""
    if proc.returncode != 0:
        err_text = (proc.stderr.read() if proc.stderr else "").strip()[-1200:]
        return None, "退出码 %s：%s" % (proc.returncode, err_text or "无错误输出")
    return out, None


# ── JSON 提取 ──────────────────────────────────────
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def extract_json(text):
    """从 AI 输出中提取 JSON 对象（优先取 ```json 代码块）"""
    m = _JSON_BLOCK_RE.search(text or "")
    candidate = m.group(1) if m else (text or "")
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(candidate[start:end + 1])


# ── 任务提示词 ─────────────────────────────────────
def _api_task_prompt(config_path):
    return (
        "你是 AgentFloat 的配置助手。\n"
        "任务：检查并修正 AgentFloat 的 API 用量监控配置。\n\n"
        "请使用 Read 工具读取以下配置文件（不要运行任何 shell 命令，不要修改任何文件）：\n"
        "%s\n\n"
        "重点关注 api_monitor.endpoints 数组。对每个端点请核对：\n"
        "1. url / method 是否为该 API 平台官方提供的余额或用量查询接口；\n"
        "2. headers 中的鉴权方式是否正确（如 Authorization: Bearer {{env:XXX_API_KEY}}）；\n"
        "3. fields[].jsonpath 是否与官方接口真实返回结构一致（用于读取剩余额度 / 用量）；\n"
        "如果发现仍是示例占位端点（url 含 api.example.com 或名称为 My API），应基于已知平台给出真实端点；"
        "4. 已知参考：DeepSeek 余额接口 GET https://api.deepseek.com/user/balance 返回 "
        "{\"is_available\":true,\"balance_infos\":[{\"currency\":\"CNY\",\"total_balance\":\"...\","
        "\"granted_balance\":\"...\",\"topped_up_balance\":\"...\"}]}，"
        "剩余额度对应 $.balance_infos[0].total_balance，货币对应 $.balance_infos[0].currency。\n\n"
        "请只输出一个 JSON 对象（用 ```json 代码块包裹，不要输出其他文字）：\n"
        "{\n"
        "  \"endpoints\": [修正或补全后的 endpoints 数组，结构与原配置一致],\n"
        "  \"notes\": [\"对每处修改的简要说明\"]\n"
        "}\n"
        "若某个端点无法确认正确配置，请保留原配置并在 notes 中说明。"
    )


def _skills_task_prompt(skills, max_desc_len=160):
    """skills 为 [(name, description), ...] 紧凑列表，避免 AI 逐个读文件"""
    lines = []
    for name, desc in skills:
        d = (desc or "").replace("\n", " ").strip()
        if len(d) > max_desc_len:
            d = d[:max_desc_len] + "…"
        lines.append("- %s：%s" % (name, d))
    list_text = "\n".join(lines)
    return (
        "你是 AgentFloat 的 Skills 翻译助手。\n"
        "任务：为以下本地 AI Agent skills 生成中文翻译。\n\n"
        "以下是 skill 名称与英文简介（来自 SKILL.md frontmatter，已由本地扫描器提取）：\n"
        "%s\n\n"
        "请为每一个 skill 生成：\n"
        "1. 中文名称：简洁贴切（2~12 字）；\n"
        "2. 中文简介：一句 20~80 字的说明，准确概括该 skill 的用途。\n\n"
        "请只输出一个 JSON 对象（用 ```json 代码块包裹，不要输出其他文字）：\n"
        "{\n"
        "  \"translations\": {\n"
        "    \"<skill-name>\": [\"<中文名>\", \"<中文简介>\"],\n"
        "    ...\n"
        "  }\n"
        "}\n"
        "必须覆盖上面列出的每一个 skill。"
    ) % list_text


# ── API 端点合并 ───────────────────────────────────
def _is_placeholder(ep):
    """示例占位端点：即使 schema 校验通过也应被替换"""
    url = (ep.get("url") or "").strip().lower()
    name = (ep.get("name") or "").strip().lower()
    return "api.example.com" in url or name in ("my api", "myapi", "示例")


def _merge_api_endpoints(config, data):
    """校验并合并 AI 修正后的 endpoints；返回 (changed_count, notes, api_config_or_None)"""
    api_cfg = dict(config.get("api_monitor") or API_MONITOR_DEFAULTS)
    cur = [e for e in (api_cfg.get("endpoints") or []) if isinstance(e, dict)]
    raw = data.get("endpoints")
    ai_list = []
    if isinstance(raw, list):
        for ep in raw:
            if isinstance(ep, dict) and not validate_endpoint(ep):
                ai_list.append(ep)
    notes = [str(n) for n in (data.get("notes") or [])]
    if not ai_list:
        return 0, notes, None

    changed = 0
    merged = list(cur)
    # 1) 修正现有校验失败或示例占位的端点（按 name 匹配；validate_endpoint 返回错误列表，非空=失败）
    for i, ep in enumerate(merged):
        if validate_endpoint(ep) or _is_placeholder(ep):
            nm = (ep.get("name") or "").strip()
            for ai_ep in ai_list:
                if (ai_ep.get("name") or "").strip() == nm or _is_placeholder(ep):
                    merged[i] = ai_ep
                    changed += 1
                    break
    # 2) 当前没有任何端点时，采用 AI 给出的完整列表
    if not cur:
        merged = ai_list
        changed = len(ai_list)
    if changed == 0:
        return 0, notes, None
    api_cfg["endpoints"] = merged
    return changed, notes, api_cfg


# ── Skills 翻译合并 ────────────────────────────────
def _load_custom_translations():
    try:
        with open(CUSTOM_TRANSLATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_custom_translations(data):
    os.makedirs(os.path.dirname(CUSTOM_TRANSLATIONS_PATH), exist_ok=True)
    with open(CUSTOM_TRANSLATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _merge_translations(data):
    """合并 AI 生成翻译到自定义翻译文件；返回 (added_count, added_map)"""
    raw = data.get("translations")
    if not isinstance(raw, dict):
        return 0, None
    existing = _load_custom_translations()
    added = {}
    for key, val in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if key in SKILL_ZH or key in _ALIAS or key in existing:
            continue  # 内置已收录，跳过
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            zh_name = str(val[0]).strip()
            zh_desc = str(val[1]).strip()
            if zh_name and zh_desc:
                added[key] = [zh_name, zh_desc]
    if not added:
        return 0, None
    merged = dict(existing)
    merged.update(added)
    _save_custom_translations(merged)
    return len(added), added


# ── 报告 ───────────────────────────────────────────
def _save_report(text):
    from datetime import datetime
    d = os.path.join(_config_dir(), "debug_logs")
    os.makedirs(d, exist_ok=True)
    name = "ai_service_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)
        return os.path.join(d, name)
    except Exception:
        return None


def _build_summary(result):
    api = result.get("api") or {}
    sk = result.get("skills") or {}
    lines = []
    if api.get("changed"):
        lines.append("API 用量配置：修正 %d 个端点" % api["changed"])
        for n in (api.get("notes") or [])[:4]:
            if n:
                lines.append("  · %s" % n)
    else:
        lines.append("API 用量配置：现有端点校验通过，无需修正")
    if sk.get("added"):
        lines.append("Skills 翻译：新增 %d 条" % sk["added"])
    else:
        lines.append("Skills 翻译：未发现缺失条目")
    for w in (result.get("warnings") or []):
        lines.append("⚠ %s" % w)
    return "\n".join(lines)


# ── 服务主流程 ─────────────────────────────────────
def run_services(config, agent, tasks=("api", "skills")):
    """同步执行全部服务；返回结构化结果 dict"""
    result = {"ok": False, "agent_name": (agent or {}).get("name") or "Agent"}
    if not agent:
        result["error"] = "未配置主 Agent，请先在「设置 → Agent 管理」中配置。"
        return result
    report_lines = ["AgentFloat 本地 AI 服务报告",
                    "Agent: %s" % result["agent_name"],
                    "配置: %s" % CONFIG_PATH,
                    "-" * 40]
    cancel = None
    if getattr(_CURRENT_CANCEL, "cancel", None) is not None:
        cancel = _CURRENT_CANCEL.cancel
    for task in tasks:
        if task == "api":
            prompt = _api_task_prompt(CONFIG_PATH)
        elif task == "skills":
            from skills_scanner import default_skill_roots, scan_skills
            roots = (config.get("skills") or {}).get("roots") or []
            if not roots:
                roots = default_skill_roots()
            missing = []
            for s in scan_skills(roots):
                if s.name in SKILL_ZH or s.name in _ALIAS:
                    continue
                if s.name in _load_custom_translations():
                    continue
                missing.append((s.name, s.description))
            if not missing:
                logger.info("[skills] 无需翻译：所有已扫描 skill 均已有中文条目")
                result["skills"] = {"added": 0, "notes": "已扫描 skill 全部有中文翻译，无需补充"}
                report_lines.append("[skills] 无需翻译：扫描到 %d 个 skill，全部已有中文" % len(scan_skills(roots)))
                continue
            prompt = _skills_task_prompt(missing)
        else:
            continue
        logger.info("[%s] 正在调用本地 Agent 执行任务…", task)
        out, err = _run_headless(agent, prompt, cancel=cancel)
        if out is None:
            result["error"] = "%s 任务失败：%s" % (task, err)
            report_lines.append("[%s] 执行失败：%s" % (task, err))
            result["report"] = "\n".join(report_lines)
            _save_report(result["report"])
            return result
        report_lines.append("[%s] Agent 原始输出长度 %d 字符" % (task, len(out)))
        try:
            data = extract_json(out)
        except Exception as e:
            msg = "%s 任务输出无法解析：%s" % (task, e)
            logger.warning(msg)
            result.setdefault("warnings", []).append(msg)
            report_lines.append("[%s] %s" % (task, msg))
            report_lines.append("[%s] 输出片段:\n%s" % (task, out[-2000:]))
            continue
        if task == "api":
            changed, notes, api_cfg = _merge_api_endpoints(config, data)
            result["api"] = {"changed": changed, "notes": notes, "api_config": api_cfg}
            report_lines.append("[api] 解析成功；修正端点 %d 个" % changed)
            for n in (notes or [])[:6]:
                if n:
                    report_lines.append("  note: %s" % n)
        elif task == "skills":
            added, added_map = _merge_translations(data)
            result["skills"] = {"added": added, "translations": added_map}
            report_lines.append("[skills] 解析成功；新增翻译 %d 条" % added)
            if added_map:
                report_lines.append("  " + "；".join(list(added_map.keys())[:20]))
    result["ok"] = True
    result["report"] = "\n".join(report_lines)
    result["summary"] = _build_summary(result)
    path = _save_report(result["report"])
    if path:
        logger.info("本地 AI 服务报告已保存: %s", path)
    return result


# ── 后台线程封装 ───────────────────────────────────
_CURRENT_CANCEL = threading.local()


class LocalAiWorker(QThread):
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config, agent, parent=None):
        super().__init__(parent)
        self._config = config
        self._agent = agent
        self._cancel = threading.Event()

    def cancel(self):
        """请求取消当前任务（终止正在运行的本地 Agent 子进程）"""
        self._cancel.set()

    def run(self):
        try:
            _CURRENT_CANCEL.cancel = self._cancel
            result = run_services(self._config, self._agent)
            if self._cancel.is_set():
                self.failed.emit("用户退出，任务已取消")
            elif result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.failed.emit(result.get("error", "未知错误"))
        except Exception as e:
            import traceback
            try:
                logger.error("本地 AI 服务异常:\n%s", traceback.format_exc())
            except Exception:
                pass
            self.failed.emit("本地 AI 服务异常: %s" % str(e))
