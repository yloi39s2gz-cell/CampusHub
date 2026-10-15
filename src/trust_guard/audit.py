"""审计日志 - 线程安全的追加式日志（带容量上限）"""

import threading
import time
from collections import deque
from dataclasses import dataclass


# 审计日志最大保留条数，防止无界增长导致内存泄漏
_MAX_ENTRIES = 2000


@dataclass
class AuditEntry:
    """审计日志条目"""
    time: float
    caller: str
    action: str
    target: str
    ok: bool
    detail: str | None = None


class AuditLogger:
    """线程安全的审计日志记录器（超过容量上限时淘汰最旧条目）"""

    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def log(
        self,
        caller: str,
        action: str,
        target: str,
        ok: bool,
        detail: str | None = None,
    ) -> None:
        """
        记录审计日志

        Args:
            caller: 调用者标识
            action: 操作类型
            target: 操作目标
            ok: 是否成功
            detail: 详细信息
        """
        entry = AuditEntry(
            time=time.time(),
            caller=caller,
            action=action,
            target=target,
            ok=ok,
            detail=detail,
        )

        with self._lock:
            self._entries.append(entry)

    def query_by_caller(self, caller: str) -> list[AuditEntry]:
        """按调用者查询日志"""
        with self._lock:
            return [e for e in self._entries if e.caller == caller]

    def export(self) -> list[dict]:
        """导出所有日志为字典列表"""
        with self._lock:
            return [
                {
                    "time": e.time,
                    "caller": e.caller,
                    "action": e.action,
                    "target": e.target,
                    "ok": e.ok,
                    "detail": e.detail,
                }
                for e in self._entries
            ]

    def clear(self) -> None:
        """清空日志"""
        with self._lock:
            self._entries.clear()
