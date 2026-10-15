"""任务 DAG 定义与拓扑排序"""

from pydantic import BaseModel, Field


class TaskNode(BaseModel):
    """任务节点"""

    node_id: str = Field(..., description="节点唯一标识")
    agent_id: str | None = Field(default=None, description="执行该节点的智能体 ID")
    capability: str | None = Field(default=None, description="所需能力")
    input_template: dict = Field(default_factory=dict, description="输入模板，支持 {node_id.key} 占位符")
    depends_on: list[str] = Field(default_factory=list, description="依赖的上游节点 ID 列表")
    timeout: float = Field(default=30.0, description="超时时间（秒）")
    max_retries: int = Field(default=0, description="最大重试次数")


class TaskDAG:
    """任务有向无环图"""

    def __init__(self):
        self.nodes: dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        """添加节点"""
        if node.node_id in self.nodes:
            raise ValueError(f"节点 {node.node_id} 已存在")
        self.nodes[node.node_id] = node

    def topological_sort(self) -> list[list[str]]:
        """
        拓扑排序，返回分层结果（每层可并行执行）

        Returns:
            分层列表，如 [["a"], ["b", "c"], ["d"]]

        Raises:
            ValueError: 存在环时抛出异常
        """
        # 计算入度
        in_degree = {node_id: 0 for node_id in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"节点 {node.node_id} 依赖不存在的节点 {dep}")

        # 构建邻接表
        adj: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                adj[dep].append(node.node_id)
                in_degree[node.node_id] += 1

        # Kahn 算法进行拓扑排序
        layers: list[list[str]] = []
        queue = [nid for nid, deg in in_degree.items() if deg == 0]

        while queue:
            layers.append(queue[:])
            next_queue = []
            for node_id in queue:
                for neighbor in adj[node_id]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        # 检查是否有环
        sorted_count = sum(len(layer) for layer in layers)
        if sorted_count != len(self.nodes):
            raise ValueError("任务 DAG 中存在环，无法执行拓扑排序")

        return layers

    def detect_cycle(self) -> bool:
        """检测是否存在环

        Returns:
            True 表示存在环，False 表示无环

        Note:
            如果依赖的节点不存在，会抛出 ValueError，不会被误判为环
        """
        try:
            self.topological_sort()
            return False
        except ValueError as e:
            # 只有环相关的错误才返回 True，其他错误（如依赖不存在）继续抛出
            if "环" in str(e):
                return True
            raise
