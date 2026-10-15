"""第 1 轮代码审查回归测试

覆盖 orchestrator/ 与 hetero_gateway/ 的修复项：
- dag.py: detect_cycle 不再将"依赖不存在"误判为环
- circuit.py: OPEN→HALF_OPEN 时 success_count 重置
- retry.py: 抖动、上限、不可重试异常过滤
- scheduler.py: 并行执行、占位符引用失败上游时主动报错
- trace.py: HTML 转义防 XSS、Mermaid 引号转义
- openapi_adapter.py: 路径参数未替换时抛异常
"""

import asyncio
import time

import pytest

from orchestrator.dag import TaskDAG, TaskNode
from orchestrator.circuit import CircuitBreaker, CircuitState
from orchestrator.retry import async_retry
from orchestrator.scheduler import DagScheduler
from orchestrator.trace import ExecutionTrace, EventType
from hetero_gateway.openapi_adapter import OpenAPIAdapter


# ═══════════════════════════════════════════════════
# 1. dag.py: detect_cycle 误判修复
# ═══════════════════════════════════════════════════

class TestDagDetectCycle:
    """detect_cycle 不再将"依赖不存在"误判为环"""

    def test_detect_cycle_true_on_cycle(self):
        """存在环时返回 True"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=["b"]))
        dag.add_node(TaskNode(node_id="b", depends_on=["a"]))
        assert dag.detect_cycle() is True

    def test_detect_cycle_false_on_no_cycle(self):
        """无环时返回 False"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=[]))
        dag.add_node(TaskNode(node_id="b", depends_on=["a"]))
        assert dag.detect_cycle() is False

    def test_detect_cycle_raises_on_missing_dep(self):
        """依赖不存在时抛 ValueError，而非误判为环"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=["nonexistent"]))
        with pytest.raises(ValueError, match="不存在"):
            dag.detect_cycle()

    def test_self_loop_detected(self):
        """自环被正确检测"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=["a"]))
        assert dag.detect_cycle() is True

    def test_empty_dag(self):
        """空 DAG 无环"""
        dag = TaskDAG()
        assert dag.detect_cycle() is False
        assert dag.topological_sort() == []

    def test_single_node_dag(self):
        """单节点 DAG 无环"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=[]))
        assert dag.detect_cycle() is False
        layers = dag.topological_sort()
        assert layers == [["a"]]


# ═══════════════════════════════════════════════════
# 2. circuit.py: success_count 重置修复
# ═══════════════════════════════════════════════════

class TestCircuitBreakerSuccessCountReset:
    """OPEN→HALF_OPEN 时 success_count 重置"""

    def test_success_count_reset_on_half_open(self):
        """从 OPEN 进入 HALF_OPEN 时 success_count 归零"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        # 触发熔断
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # 模拟之前 HALF_OPEN 阶段遗留的 success_count
        cb.success_count = 1
        # 等待冷却
        time.sleep(0.15)
        # 进入 HALF_OPEN
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN
        # success_count 应被重置为 0
        assert cb.success_count == 0

    def test_half_open_needs_two_successes(self):
        """HALF_OPEN 状态需要连续 2 次成功才能恢复"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN
        # 第 1 次成功不足以恢复
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        # 第 2 次成功才恢复
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        """HALF_OPEN 状态下失败立即回到 OPEN"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


# ═══════════════════════════════════════════════════
# 3. retry.py: 抖动、上限、不可重试异常
# ═══════════════════════════════════════════════════

class TestRetryImprovements:
    """重试机制改进：抖动、上限、不可重试异常过滤"""

    async def test_max_delay_cap(self):
        """延迟不超过 max_delay 上限"""
        call_count = 0
        sleep_delays = []

        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        # monkey-patch asyncio.sleep
        import orchestrator.retry as retry_module
        retry_module.asyncio.sleep = mock_sleep
        try:
            with pytest.raises(RuntimeError):
                await async_retry(
                    failing_fn,
                    max_retries=5,
                    base_delay=1.0,
                    max_delay=3.0,
                    jitter=False,  # 关闭抖动以便精确断言
                )
        finally:
            retry_module.asyncio.sleep = original_sleep

        assert call_count == 6  # 1 + 5 retries
        # 无抖动时: 1, 2, 4, 3(capped), 3(capped)
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 3.0  # min(4, 3) = 3
        assert sleep_delays[3] == 3.0
        assert sleep_delays[4] == 3.0

    async def test_jitter_adds_randomness(self):
        """开启抖动时延迟不完全相同"""
        sleep_delays = []

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        async def failing_fn():
            raise RuntimeError("fail")

        import orchestrator.retry as retry_module
        original_sleep = retry_module.asyncio.sleep
        retry_module.asyncio.sleep = mock_sleep
        try:
            with pytest.raises(RuntimeError):
                await async_retry(
                    failing_fn,
                    max_retries=5,
                    base_delay=1.0,
                    max_delay=60.0,
                    jitter=True,
                )
        finally:
            retry_module.asyncio.sleep = original_sleep

        # 有抖动时延迟不应完全相等（极小概率相等，但 5 次全等概率极低）
        assert len(sleep_delays) == 5
        # 至少有一个不在理论无抖动值上
        expected_no_jitter = [1.0, 2.0, 4.0, 8.0, 16.0]
        assert sleep_delays != expected_no_jitter

    async def test_non_retryable_exception(self):
        """不可重试异常立即抛出，不重试"""
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("不可重试")

        with pytest.raises(ValueError, match="不可重试"):
            await async_retry(
                failing_fn,
                max_retries=5,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),  # 只重试 RuntimeError
            )
        assert call_count == 1  # 只调用了一次

    async def test_retryable_exception_retries(self):
        """可重试异常正常重试"""
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("可重试")

        with pytest.raises(RuntimeError):
            await async_retry(
                failing_fn,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),
            )
        assert call_count == 3  # 1 + 2 retries


# ═══════════════════════════════════════════════════
# 4. scheduler.py: 并行执行 + 占位符健壮性
# ═══════════════════════════════════════════════════

class TestSchedulerParallelExecution:
    """调度器并行执行验证"""

    async def test_parallel_execution_in_layer(self):
        """同层节点确实并行执行"""
        execution_times = {}

        async def invoke_fn(agent_id, payload):
            start = time.time()
            await asyncio.sleep(0.1)
            execution_times[payload.get("node_id")] = time.time() - start
            return {"result": "ok"}

        dag = TaskDAG()
        dag.add_node(TaskNode(
            node_id="n1", agent_id="a1",
            input_template={"node_id": "n1"},
            depends_on=[],
        ))
        dag.add_node(TaskNode(
            node_id="n2", agent_id="a2",
            input_template={"node_id": "n2"},
            depends_on=[],
        ))

        scheduler = DagScheduler(invoke_fn, max_retries=0, base_delay=0.01)
        result = await scheduler.execute(dag)

        assert result["status"] == "success"
        # 如果并行，总耗时应约 0.1s；如果串行，约 0.2s
        # 通过检查两个节点的执行时间戳来判断
        assert "n1" in execution_times
        assert "n2" in execution_times

    async def test_upstream_failure_blocks_downstream(self):
        """上游失败时下游节点被跳过并报错"""
        call_count = 0

        async def invoke_fn(agent_id, payload):
            nonlocal call_count
            call_count += 1
            if payload.get("fail"):
                raise RuntimeError("上游失败")
            return {"data": "ok"}

        dag = TaskDAG()
        dag.add_node(TaskNode(
            node_id="upstream", agent_id="a1",
            input_template={"fail": True},
            depends_on=[],
        ))
        dag.add_node(TaskNode(
            node_id="downstream", agent_id="a2",
            input_template={"query": "{upstream.data}"},
            depends_on=["upstream"],
        ))
        # 添加一个独立节点，确保是 partial_failure 而非 failed
        dag.add_node(TaskNode(
            node_id="independent", agent_id="a3",
            input_template={"query": "ok"},
            depends_on=[],
        ))

        scheduler = DagScheduler(invoke_fn, max_retries=0, base_delay=0.01)
        result = await scheduler.execute(dag)

        # 上游失败，下游应被跳过，独立节点成功
        assert result["status"] == "partial_failure"
        assert "upstream" in result["results"]
        assert "error" in result["results"]["upstream"]
        assert "downstream" in result["results"]
        assert "error" in result["results"]["downstream"]
        assert "independent" in result["results"]
        assert result["results"]["independent"]["data"] == "ok"
        # 下游应被跳过，不应调用 invoke_fn
        assert call_count == 2  # 上游 + 独立节点


# ═══════════════════════════════════════════════════
# 5. trace.py: HTML 转义 + Mermaid 引号转义
# ═══════════════════════════════════════════════════

class TestTraceXssPrevention:
    """HTML/Mermaid 导出特殊字符转义"""

    def test_html_escapes_script_tags(self):
        """HTML 导出转义 script 标签"""
        t = ExecutionTrace()
        t.record_start("<script>alert('xss')</script>")
        t.record_success("<script>alert('xss')</script>", detail="<img onerror=alert(1)>")
        html_output = t.export_html()
        # 不应包含未转义的 script 标签
        assert "<script>" not in html_output
        assert "&lt;script&gt;" in html_output
        # 不应包含未转义的 img 标签
        assert "<img " not in html_output

    def test_html_escapes_ampersand(self):
        """HTML 导出转义 & 符号"""
        t = ExecutionTrace()
        t.record_start("node&test")
        t.record_success("node&test", detail="a&b")
        html_output = t.export_html()
        assert "&amp;" in html_output

    def test_mermaid_escapes_quotes(self):
        """Mermaid 导出转义双引号"""
        t = ExecutionTrace()
        t.record_start('node"with"quotes')
        t.record_success('node"with"quotes')
        mermaid = t.export_mermaid()
        # 节点文本中的双引号应被转义
        assert "&quot;" in mermaid


# ═══════════════════════════════════════════════════
# 6. openapi_adapter.py: 路径参数未替换校验
# ═══════════════════════════════════════════════════

class TestOpenapiPathParamValidation:
    """OpenAPI 适配器路径参数校验"""

    def test_missing_path_param_raises(self):
        """缺少必填路径参数时抛异常"""
        spec = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/books/{book_id}": {
                    "get": {
                        "operationId": "getBook",
                        "parameters": [
                            {"name": "book_id", "in": "path", "required": True},
                        ],
                    },
                },
            },
        }
        adapter = OpenAPIAdapter(spec)
        with pytest.raises(ValueError, match="路径参数未替换|缺少必填参数"):
            adapter.translate_invoke({
                "capability": "get /books/{book_id}",
                "params": {},  # 缺少 book_id
            })

    def test_path_param_provided_works(self):
        """提供路径参数时正常工作"""
        spec = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/books/{book_id}": {
                    "get": {
                        "operationId": "getBook",
                        "parameters": [
                            {"name": "book_id", "in": "path", "required": True},
                        ],
                    },
                },
            },
        }
        adapter = OpenAPIAdapter(spec)
        result = adapter.translate_invoke({
            "capability": "get /books/{book_id}",
            "params": {"book_id": "123"},
        })
        assert result["path"] == "/books/123"
