# -*- coding: utf-8 -*-
"""注意力路由：只在任务首次进入 need_input / failed 时提醒一次。"""


def new_attention(sessions, seen):
    """返回本轮需要提醒的会话，并把去重键写入 seen。"""
    out = []
    for data in sessions:
        status = str(data.get("status") or "")
        if status not in ("need_input", "failed"):
            continue
        key = "%s:%s:%s" % (data.get("sessionId"), status, data.get("updatedAt"))
        if key in seen:
            continue
        seen.add(key)
        out.append(data)
    if len(seen) > 200:
        for key in list(seen)[:100]:
            seen.discard(key)
    return out
