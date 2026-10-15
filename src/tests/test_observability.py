"""可观测性测试 - MetricsCollector / ExecutionTrace 导出 / 端到端接口"""

import time

import pytest
from fastapi.testclient import TestClient

from gateway.metrics import MetricsCollector
from orchestrator.trace import ExecutionTrace, EventType


# ═══════════════════════════════════════════════════
# 1. MetricsCollector 单元测试
# ═══════════════════════════════════════════════════

class TestMetricsCollector:
    """指标收集器统计正确性"""

    def test_empty_snapshot(self):
        """空收集器的 snapshot 各字段为零"""
        m = MetricsCollector()
        snap = m.snapshot()
        assert snap["invoke"]["total"] == 0
        assert snap["invoke"]["success_rate"] == 0.0
        assert snap["task"]["total"] == 0
        assert snap["agents"] == {}

    def test_invoke_success_rate_and_avg(self):
        """多次 invoke 后成功率与平均时延正确"""
        m = MetricsCollector()
        # 3 次成功（10ms  each），1 次失败（20ms）
        m.record_invoke("agent-a", 10.0, ok=True)
        m.record_invoke("agent-a", 10.0, ok=True)
        m.record_invoke("agent-a", 10.0, ok=True)
        m.record_invoke("agent-b", 20.0, ok=False)

        snap = m.snapshot()
        assert snap["invoke"]["total"] == 4
        assert snap["invoke"]["ok"] == 3
        assert snap["invoke"]["fail"] == 1
        # 成功率 75%
        assert snap["invoke"]["success_rate"] == 75.0
        # 平均时延 (10+10+10+20)/4 = 12.5
        assert snap["invoke"]["avg_latency_ms"] == 12.5

    def test_invoke_p95(self):
        """P95 时延计算正确"""
        m = MetricsCollector()
        # 20 次调用，时延 1~20 ms
        for i in range(1, 21):
            m.record_invoke("a", float(i), ok=True)
        snap = m.snapshot()
        # p95 index = int(20 * 0.95) = 19，对应 sorted[19] = 20
        assert snap["invoke"]["p95_latency_ms"] == 20.0

    def test_task_record(self):
        """task 记录统计"""
        m = MetricsCollector()
        m.record_task(100.0, ok=True, node_count=3)
        m.record_task(200.0, ok=True, node_count=5)
        m.record_task(50.0, ok=False, node_count=2)

        snap = m.snapshot()
        assert snap["task"]["total"] == 3
        assert snap["task"]["ok"] == 2
        assert snap["task"]["fail"] == 1
        # 平均节点数 (3+5+2)/3 ≈ 3.33
        assert snap["task"]["avg_node_count"] == pytest.approx(3.33, rel=0.01)

    def test_agents_aggregation(self):
        """按 agent_id 聚合"""
        m = MetricsCollector()
        m.record_invoke("a", 10.0, ok=True)
        m.record_invoke("a", 10.0, ok=False)
        m.record_invoke("b", 10.0, ok=True)

        snap = m.snapshot()
        assert snap["agents"]["a"] == {"total": 2, "ok": 1}
        assert snap["agents"]["b"] == {"total": 1, "ok": 1}


# ═══════════════════════════════════════════════════
# 2. ExecutionTrace 导出测试
# ═══════════════════════════════════════════════════

class TestTraceExport:
    """ExecutionTrace 的 Mermaid / HTML 导出"""

    def _build_trace(self) -> ExecutionTrace:
        """构造一条含多种事件的 trace"""
        t = ExecutionTrace()
        t.record_start("node-a")
        time.sleep(0.01)
        t.record_success("node-a", detail="ok")
        t.record_start("node-b")
        t.record_retry("node-b", attempt=1)
        time.sleep(0.01)
        t.record_fail("node-b", detail="timeout")
        t.record_start("node-c")
        t.record_skipped("node-c", reason="熔断")
        return t

    def test_export_mermaid_contains_flowchart(self):
        """Mermaid 导出包含 flowchart 关键字"""
        t = self._build_trace()
        mermaid = t.export_mermaid()
        assert "flowchart TD" in mermaid

    def test_export_mermaid_contains_node_ids(self):
        """Mermaid 导出包含所有节点 id"""
        t = self._build_trace()
        mermaid = t.export_mermaid()
        assert "node-a" in mermaid
        assert "node-b" in mermaid
        assert "node-c" in mermaid

    def test_export_mermaid_contains_style(self):
        """Mermaid 导出包含着色样式"""
        t = self._build_trace()
        mermaid = t.export_mermaid()
        # 成功绿 / 失败红 / 跳过灰
        assert "#d4edda" in mermaid or "成功" in mermaid
        assert "#f8d7da" in mermaid or "失败" in mermaid

    def test_export_html_contains_html_tag(self):
        """HTML 导出包含 <html> 标签"""
        t = self._build_trace()
        html = t.export_html()
        assert "<html" in html
        assert "</html>" in html

    def test_export_html_contains_event_rows(self):
        """HTML 导出包含事件表格行"""
        t = self._build_trace()
        html = t.export_html()
        # 至少包含 node-a / node-b / node-c
        assert "node-a" in html
        assert "node-b" in html
        assert "node-c" in html
        # 包含表格
        assert "<table>" in html or "<table" in html


# ═══════════════════════════════════════════════════
# 3. 端到端接口测试（/metrics /trace）
# ═══════════════════════════════════════════════════

class TestObservabilityEndpoints:
    """端到端：/metrics 鉴权、/task 后取 /trace"""

    def test_metrics_requires_auth(self, client: TestClient):
        """/metrics 无 token 返回 401"""
        resp = client.get("/metrics")
        assert resp.status_code == 401

    def test_metrics_with_auth(self, client: TestClient, auth_headers: dict):
        """/metrics 有 token 返回 200"""
        resp = client.get("/metrics", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "invoke" in data
        assert "task" in data
        assert "agents" in data

    def test_task_then_trace_mermaid(self, client: TestClient, auth_headers: dict):
        """提交 /task 后用 task_id 取 /trace/{id}/mermaid"""
        # 提交一个简单的 DAG 任务
        task_body = {
            "nodes": [
                {
                    "node_id": "lib",
                    "agent_id": "library",
                    "input_template": {"query": "Python"},
                    "depends_on": [],
                }
            ]
        }
        resp = client.post("/task", json=task_body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        task_id = data.get("task_id")
        assert task_id is not None and len(task_id) > 0

        # 取 Mermaid
        resp2 = client.get(f"/trace/{task_id}/mermaid", headers=auth_headers)
        assert resp2.status_code == 200
        assert "flowchart" in resp2.text
        assert len(resp2.text) > 0

    def test_task_then_trace_html(self, client: TestClient, auth_headers: dict):
        """提交 /task 后用 task_id 取 /trace/{id}/html"""
        task_body = {
            "nodes": [
                {
                    "node_id": "room",
                    "agent_id": "study-room",
                    "input_template": {"query": "查询"},
                    "depends_on": [],
                }
            ]
        }
        resp = client.post("/task", json=task_body, headers=auth_headers)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        resp2 = client.get(f"/trace/{task_id}/html", headers=auth_headers)
        assert resp2.status_code == 200
        assert "<html" in resp2.text
        assert len(resp2.text) > 0

    def test_trace_not_found(self, client: TestClient, auth_headers: dict):
        """不存在的 task_id 返回 404"""
        resp = client.get("/trace/nonexistent-id/mermaid", headers=auth_headers)
        assert resp.status_code == 404

        resp2 = client.get("/trace/nonexistent-id/html", headers=auth_headers)
        assert resp2.status_code == 404

    def test_invoke_records_metrics(self, client: TestClient, auth_headers: dict):
        """/invoke 调用后 /metrics 能看到统计"""
        # 调用一次
        resp = client.post(
            "/invoke",
            json={"from_id": "user", "to_id": "course-qa", "payload": {"query": "高数"}},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 查看指标
        resp2 = client.get("/metrics", headers=auth_headers)
        data = resp2.json()
        assert data["invoke"]["total"] >= 1
        assert "course-qa" in data["agents"]
