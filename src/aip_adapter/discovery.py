"""智能体发现服务 - 按能力关键词检索"""

from .models import AgentCard
from .registry import AgentRegistry


class AgentDiscovery:
    """智能体发现服务，支持模糊检索"""

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def find_by_capability(self, keyword: str) -> list[AgentCard]:
        """
        按能力关键词模糊检索，返回按匹配度排序的列表

        匹配度计算：
        - 完全匹配 capability: 10 分
        - capability 包含 keyword: 5 分
        - description 包含 keyword: 2 分
        - name 包含 keyword: 1 分
        """
        if not keyword:
            return []

        keyword_lower = keyword.lower()
        scored_agents: list[tuple[int, AgentCard]] = []

        for card in self.registry.list_all():
            score = 0

            # 检查 capabilities
            for cap in card.capabilities:
                cap_lower = cap.lower()
                if cap_lower == keyword_lower:
                    score += 10
                elif keyword_lower in cap_lower:
                    score += 5

            # 检查 description
            if keyword_lower in card.description.lower():
                score += 2

            # 检查 name
            if keyword_lower in card.name.lower():
                score += 1

            if score > 0:
                scored_agents.append((score, card))

        # 按分数降序排序
        scored_agents.sort(key=lambda x: x[0], reverse=True)
        return [card for _, card in scored_agents]
