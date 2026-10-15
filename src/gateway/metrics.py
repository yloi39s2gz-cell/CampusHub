"""可观测性指标收集器 - 线程安全，用于统计调用次数、成功率、时延分位"""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _InvokeRecord:
    """单次 invoke 调用记录"""
    agent_id: str
    duration_ms: float
    ok: bool


@dataclass
class _TaskRecord:
    """单次 task 调用记录"""
    duration_ms: float
    ok: bool
    node_count: int


class MetricsCollector:
    """
    线程安全的指标收集器

    记录 /invoke 与 /task 的调用次数、成功率、时延，
    并提供 snapshot() 方法输出当前统计信息。
    """

    def __init__(self):
        # 读写锁，保证并发安全
        self._lock = threading.Lock()
        # /invoke 调用记录
        self._invoke_records: list[_InvokeRecord] = []
        # /task 调用记录
        self._task_records: list[_TaskRecord] = []

    def record_invoke(self, agent_id: str, duration_ms: float, ok: bool) -> None:
        """
        记录一次 /invoke 调用

        Args:
            agent_id: 被调用的智能体 ID
            duration_ms: 调用耗时（毫秒）
            ok: 是否成功
        """
        with self._lock:
            self._invoke_records.append(_InvokeRecord(
                agent_id=agent_id,
                duration_ms=duration_ms,
                ok=ok,
            ))

    def record_task(self, duration_ms: float, ok: bool, node_count: int) -> None:
        """
        记录一次 /task 调用

        Args:
            duration_ms: 任务执行耗时（毫秒）
            ok: 是否成功（status == "success"）
            node_count: DAG 节点数量
        """
        with self._lock:
            self._task_records.append(_TaskRecord(
                duration_ms=duration_ms,
                ok=ok,
                node_count=node_count,
            ))

    def snapshot(self) -> dict:
        """
        返回当前指标快照

        Returns:
            {
              "invoke": {"total", "ok", "fail", "success_rate", "avg_latency_ms", "p95_latency_ms"},
              "task":   {"total", "ok", "fail", "success_rate", "avg_latency_ms", "p95_latency_ms", "avg_node_count"},
              "agents": {agent_id: {"total", "ok"}}
            }
        """
        with self._lock:
            invoke_snap = self._summarize_records(
                [r.duration_ms for r in self._invoke_records],
                [r.ok for r in self._invoke_records],
            )
            task_snap = self._summarize_records(
                [r.duration_ms for r in self._task_records],
                [r.ok for r in self._task_records],
            )
            # 平均节点数
            if self._task_records:
                avg_node = sum(r.node_count for r in self._task_records) / len(self._task_records)
                task_snap["avg_node_count"] = round(avg_node, 2)
            else:
                task_snap["avg_node_count"] = 0.0

            # 按 agent_id 聚合
            agents: dict[str, dict] = {}
            for r in self._invoke_records:
                if r.agent_id not in agents:
                    agents[r.agent_id] = {"total": 0, "ok": 0}
                agents[r.agent_id]["total"] += 1
                if r.ok:
                    agents[r.agent_id]["ok"] += 1

            return {
                "invoke": invoke_snap,
                "task": task_snap,
                "agents": agents,
            }

    @staticmethod
    def _summarize_records(durations: list[float], oks: list[bool]) -> dict:
        """
        对一组记录做统计汇总

        Args:
            durations: 时延列表（毫秒）
            oks: 成功标记列表

        Returns:
            包含 total/ok/fail/success_rate/avg_latency_ms/p95_latency_ms 的字典
        """
        total = len(oks)
        ok_count = sum(1 for o in oks if o)
        fail_count = total - ok_count
        success_rate = (ok_count / total * 100) if total else 0.0

        if durations:
            avg_latency = sum(durations) / len(durations)
            # p95 计算：排序后取 95% 分位
            sorted_d = sorted(durations)
            p95_index = int(len(sorted_d) * 0.95)
            # 防止索引越界
            p95_index = min(p95_index, len(sorted_d) - 1)
            p95_latency = sorted_d[p95_index]
        else:
            avg_latency = 0.0
            p95_latency = 0.0

        return {
            "total": total,
            "ok": ok_count,
            "fail": fail_count,
            "success_rate": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
        }
