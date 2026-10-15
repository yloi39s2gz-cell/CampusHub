"""执行追踪记录"""

import html as html_lib
import time
from dataclasses import dataclass, field
from enum import Enum


class EventType(Enum):
    """事件类型"""
    START = "start"
    SUCCESS = "success"
    FAIL = "fail"
    RETRY = "retry"
    SKIPPED = "skipped"


@dataclass
class TraceEvent:
    """追踪事件"""
    node_id: str
    event_type: EventType
    timestamp: float
    duration: float | None = None
    detail: str | None = None


class ExecutionTrace:
    """执行追踪记录器"""

    def __init__(self):
        self.events: list[TraceEvent] = []
        self._start_times: dict[str, float] = {}

    def record_start(self, node_id: str) -> None:
        """记录节点开始"""
        self._start_times[node_id] = time.time()
        self.events.append(TraceEvent(
            node_id=node_id,
            event_type=EventType.START,
            timestamp=self._start_times[node_id],
        ))

    def record_success(self, node_id: str, detail: str | None = None) -> None:
        """记录节点成功"""
        start_time = self._start_times.get(node_id)
        duration = time.time() - start_time if start_time else None

        self.events.append(TraceEvent(
            node_id=node_id,
            event_type=EventType.SUCCESS,
            timestamp=time.time(),
            duration=duration,
            detail=detail,
        ))

    def record_fail(self, node_id: str, detail: str | None = None) -> None:
        """记录节点失败"""
        start_time = self._start_times.get(node_id)
        duration = time.time() - start_time if start_time else None

        self.events.append(TraceEvent(
            node_id=node_id,
            event_type=EventType.FAIL,
            timestamp=time.time(),
            duration=duration,
            detail=detail,
        ))

    def record_retry(self, node_id: str, attempt: int) -> None:
        """记录节点重试"""
        self.events.append(TraceEvent(
            node_id=node_id,
            event_type=EventType.RETRY,
            timestamp=time.time(),
            detail=f"第 {attempt} 次重试",
        ))

    def record_skipped(self, node_id: str, reason: str | None = None) -> None:
        """记录节点跳过"""
        self.events.append(TraceEvent(
            node_id=node_id,
            event_type=EventType.SKIPPED,
            timestamp=time.time(),
            detail=reason,
        ))

    def to_dict(self) -> dict:
        """导出为字典"""
        return {
            "events": [
                {
                    "node_id": e.node_id,
                    "event_type": e.event_type.value,
                    "timestamp": e.timestamp,
                    "duration": e.duration,
                    "detail": e.detail,
                }
                for e in self.events
            ]
        }

    def to_list(self) -> list[dict]:
        """导出为列表"""
        return self.to_dict()["events"]

    def export_mermaid(self) -> str:
        """
        导出为 Mermaid flowchart 文本

        节点按状态着色：
        - 成功：绿色（#d4edda）
        - 失败：红色（#f8d7da）
        - 重试：黄色（#fff3cd）
        - 跳过：灰色（#e2e3e5）

        边按执行顺序连接，并标注耗时（毫秒）
        """
        # 收集每个节点的最终状态（以最后一次非 START 事件为准）
        node_status: dict[str, EventType] = {}
        # 收集每个节点的耗时（取最后一次 SUCCESS/FAIL 的 duration）
        node_duration: dict[str, float | None] = {}
        # 收集所有节点 id（保持出现顺序）
        node_order: list[str] = []

        for event in self.events:
            nid = event.node_id
            if nid not in node_order:
                node_order.append(nid)
            if event.event_type == EventType.START:
                continue
            node_status[nid] = event.event_type
            if event.duration is not None:
                node_duration[nid] = event.duration

        # 状态到样式的映射
        style_map = {
            EventType.SUCCESS: ("#d4edda", "#155724", "成功"),
            EventType.FAIL: ("#f8d7da", "#721c24", "失败"),
            EventType.RETRY: ("#fff3cd", "#856404", "重试"),
            EventType.SKIPPED: ("#e2e3e5", "#383d41", "跳过"),
        }

        lines: list[str] = ["flowchart TD"]

        # 节点定义
        for nid in node_order:
            status = node_status.get(nid, EventType.SKIPPED)
            bg, fg, label = style_map.get(status, ("#e2e3e5", "#383d41", "未知"))
            dur = node_duration.get(nid)
            dur_str = f" ({dur*1000:.1f}ms)" if dur is not None else ""
            # 节点文本：id + 状态 + 耗时
            node_text = f"{nid}{dur_str}\\n[{label}]"
            # 对节点 ID 进行转义，避免引号等特殊字符破坏 Mermaid 语法
            # Mermaid 中双引号内的内容需要转义双引号本身
            safe_nid_text = node_text.replace('"', "&quot;")
            # 使用双引号包裹避免特殊字符问题
            lines.append(f'    {nid}["{safe_nid_text}"]')
            # 样式
            lines.append(f"    style {nid} fill:{bg},stroke:{fg},color:{fg}")

        # 边：按事件时间顺序连接相邻节点（START 事件顺序作为执行顺序）
        start_events = [e for e in self.events if e.event_type == EventType.START]
        for i in range(len(start_events) - 1):
            src = start_events[i].node_id
            dst = start_events[i + 1].node_id
            # 标注耗时（源节点耗时）
            dur = node_duration.get(src)
            if dur is not None:
                lines.append(f"    {src} -->|{dur*1000:.1f}ms| {dst}")
            else:
                lines.append(f"    {src} --> {dst}")

        return "\n".join(lines)

    def export_html(self) -> str:
        """
        导出为自包含单文件 HTML（样式内联，零外部依赖）

        包含：
        - 事件时间线表格（时间戳、节点、事件类型、耗时、详情）
        - 耗时统计摘要（总耗时、平均耗时、最长/最短节点）
        """
        import datetime

        # 事件行
        rows: list[str] = []
        for event in self.events:
            ts = datetime.datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            dur_str = f"{event.duration*1000:.2f}" if event.duration is not None else "-"
            detail = event.detail or "-"
            # 事件类型着色
            color_map = {
                EventType.START: "#17a2b8",
                EventType.SUCCESS: "#28a745",
                EventType.FAIL: "#dc3545",
                EventType.RETRY: "#ffc107",
                EventType.SKIPPED: "#6c757d",
            }
            color = color_map.get(event.event_type, "#333")
            # 对节点 ID 和详情进行 HTML 转义，防止 XSS
            safe_node_id = html_lib.escape(event.node_id, quote=True)
            safe_detail = html_lib.escape(detail, quote=True)
            rows.append(
                f"<tr>"
                f"<td>{ts}</td>"
                f"<td>{safe_node_id}</td>"
                f'<td style="color:{color};font-weight:bold">{event.event_type.value}</td>'
                f"<td>{dur_str}</td>"
                f"<td>{safe_detail}</td>"
                f"</tr>"
            )

        # 耗时统计
        durations = [(e.node_id, e.duration) for e in self.events if e.duration is not None]
        if durations:
            total_ms = sum(d for _, d in durations) * 1000
            avg_ms = total_ms / len(durations)
            max_node, max_d = max(durations, key=lambda x: x[1])
            min_node, min_d = min(durations, key=lambda x: x[1])
            # 对节点 ID 进行 HTML 转义
            safe_max_node = html_lib.escape(max_node, quote=True)
            safe_min_node = html_lib.escape(min_node, quote=True)
            stats_html = (
                f"<p><strong>总耗时：</strong>{total_ms:.2f} ms</p>"
                f"<p><strong>平均耗时：</strong>{avg_ms:.2f} ms</p>"
                f"<p><strong>最长节点：</strong>{safe_max_node}（{max_d*1000:.2f} ms）</p>"
                f"<p><strong>最短节点：</strong>{safe_min_node}（{min_d*1000:.2f} ms）</p>"
            )
        else:
            stats_html = "<p>暂无耗时数据</p>"

        rows_html = "\n".join(rows)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>执行追踪报告</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; margin: 2em; color: #333; }}
  h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: .3em; }}
  h2 {{ color: #34495e; margin-top: 1.5em; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #3498db; color: white; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .stats {{ background: #f4f6f8; padding: 1em; border-radius: 6px; margin-top: 1em; }}
</style>
</head>
<body>
<h1>执行追踪报告</h1>
<h2>耗时统计</h2>
<div class="stats">{stats_html}</div>
<h2>事件时间线</h2>
<table>
<thead>
<tr><th>时间戳</th><th>节点</th><th>事件</th><th>耗时 (ms)</th><th>详情</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""
        return html
