"""DAG 调度器 - 按拓扑分层并行执行"""

import asyncio
from typing import Any, Awaitable, Callable
from .dag import TaskDAG
from .retry import async_retry
from .circuit import CircuitBreaker
from .trace import ExecutionTrace


class DagScheduler:
    """DAG 调度器，支持并行执行、重试、熔断、超时控制"""

    def __init__(
        self,
        invoke_fn: Callable[[str, dict], Awaitable[dict]],
        max_retries: int = 3,
        base_delay: float = 1.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ):
        """
        初始化调度器

        Args:
            invoke_fn: 节点执行回调函数，签名 async invoke_fn(agent_id, payload) -> dict
            max_retries: 默认最大重试次数
            base_delay: 重试基础延迟（秒）
            circuit_failure_threshold: 熔断器失败阈值
            circuit_recovery_timeout: 熔断器恢复时间（秒）
        """
        self.invoke_fn = invoke_fn
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_recovery_timeout = circuit_recovery_timeout
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.trace = ExecutionTrace()

    def _get_circuit_breaker(self, agent_id: str) -> CircuitBreaker:
        """获取或创建智能体的熔断器"""
        if agent_id not in self.circuit_breakers:
            self.circuit_breakers[agent_id] = CircuitBreaker(
                failure_threshold=self.circuit_failure_threshold,
                recovery_timeout=self.circuit_recovery_timeout,
            )
        return self.circuit_breakers[agent_id]

    def _resolve_input(self, template: dict, results: dict[str, dict], failed_nodes: set[str]) -> dict:
        """
        解析输入模板，替换 {node_id.key} 占位符

        Args:
            template: 输入模板
            results: 上游节点的执行结果
            failed_nodes: 已失败的上游节点 ID 集合

        Returns:
            解析后的输入

        Raises:
            ValueError: 占位符引用的上游节点失败或不存在时
        """
        import re
        resolved = {}
        for key, value in template.items():
            if isinstance(value, str) and "{" in value and "}" in value:
                resolved_value = value
                # 找出所有 {node_id.key} 形式的占位符
                placeholders = re.findall(r"\{([^}.]+)\.([^}]+)\}", value)
                for node_id, result_key in placeholders:
                    placeholder = f"{{{node_id}.{result_key}}}"
                    # 检查上游节点是否失败
                    if node_id in failed_nodes:
                        raise ValueError(
                            f"上游节点 {node_id} 执行失败，无法解析占位符 {placeholder}"
                        )
                    # 检查上游节点是否存在结果
                    if node_id not in results:
                        raise ValueError(
                            f"上游节点 {node_id} 不存在结果，无法解析占位符 {placeholder}"
                        )
                    node_result = results[node_id]
                    if result_key in node_result:
                        resolved_value = resolved_value.replace(
                            placeholder, str(node_result[result_key])
                        )
                resolved[key] = resolved_value
            else:
                resolved[key] = value
        return resolved

    async def _execute_node(
        self,
        node_id: str,
        agent_id: str,
        payload: dict,
        timeout: float,
        max_retries: int,
    ) -> dict:
        """执行单个节点，包含重试、熔断、超时控制"""
        circuit_breaker = self._get_circuit_breaker(agent_id)

        # 检查熔断器
        if not circuit_breaker.can_execute():
            self.trace.record_skipped(node_id, "熔断器处于 open 状态")
            raise RuntimeError(f"智能体 {agent_id} 熔断器已打开")

        async def _invoke():
            """实际调用"""
            return await self.invoke_fn(agent_id, payload)

        try:
            self.trace.record_start(node_id)

            # 带超时的重试执行
            result = await asyncio.wait_for(
                async_retry(_invoke, max_retries, self.base_delay),
                timeout=timeout,
            )

            self.trace.record_success(node_id)
            circuit_breaker.record_success()
            return result

        except asyncio.TimeoutError:
            self.trace.record_fail(node_id, "执行超时")
            circuit_breaker.record_failure()
            raise
        except Exception as e:
            self.trace.record_fail(node_id, str(e))
            circuit_breaker.record_failure()
            raise

    async def execute(self, dag: TaskDAG) -> dict:
        """
        执行 DAG

        Args:
            dag: 任务 DAG

        Returns:
            {status, results, trace}
        """
        # 拓扑排序
        try:
            layers = dag.topological_sort()
        except ValueError as e:
            return {
                "status": "error",
                "error": str(e),
                "results": {},
                "trace": self.trace.to_dict(),
            }

        results: dict[str, dict] = {}
        failed_nodes: set[str] = set()

        # 按层执行
        for layer in layers:
            # 并行执行同层节点
            tasks = []
            layer_node_ids = []
            for node_id in layer:
                node = dag.nodes[node_id]

                # 解析输入（检查上游是否失败）
                try:
                    payload = self._resolve_input(node.input_template, results, failed_nodes)
                except ValueError as e:
                    # 上游失败导致无法解析占位符，直接标记该节点失败
                    self.trace.record_skipped(node_id, str(e))
                    failed_nodes.add(node_id)
                    results[node_id] = {"error": str(e)}
                    continue

                # 确定 agent_id
                agent_id = node.agent_id or node.capability
                if not agent_id:
                    self.trace.record_skipped(node_id, "未指定 agent_id 或 capability")
                    continue

                # 创建任务
                task = self._execute_node(
                    node_id=node_id,
                    agent_id=agent_id,
                    payload=payload,
                    timeout=node.timeout,
                    max_retries=node.max_retries or self.max_retries,
                )
                tasks.append(task)
                layer_node_ids.append(node_id)

            # 使用 asyncio.gather 并行执行同层所有任务
            if tasks:
                gather_results = await asyncio.gather(*tasks, return_exceptions=True)
                for node_id, result in zip(layer_node_ids, gather_results):
                    if isinstance(result, Exception):
                        failed_nodes.add(node_id)
                        results[node_id] = {"error": str(result)}
                    else:
                        results[node_id] = result

        # 判断整体状态
        status = "success" if not failed_nodes else "partial_failure"
        if len(failed_nodes) == len(dag.nodes):
            status = "failed"

        return {
            "status": status,
            "results": results,
            "trace": self.trace.to_dict(),
        }
