"""智能体注册表 - 抽象基类与内存实现"""

from abc import ABC, abstractmethod
from .models import AgentCard


class AgentRegistry(ABC):
    """智能体注册表抽象基类"""

    @abstractmethod
    def register(self, card: AgentCard) -> None:
        """注册智能体"""
        pass

    @abstractmethod
    def unregister(self, agent_id: str) -> None:
        """注销智能体"""
        pass

    @abstractmethod
    def get(self, agent_id: str) -> AgentCard | None:
        """获取智能体卡片"""
        pass

    @abstractmethod
    def list_all(self) -> list[AgentCard]:
        """列出所有已注册智能体"""
        pass


class InMemoryRegistry(AgentRegistry):
    """基于内存字典的注册表实现"""

    def __init__(self):
        self._agents: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """注册智能体，重复注册抛出异常"""
        if card.agent_id in self._agents:
            raise ValueError(f"智能体 {card.agent_id} 已注册，不可重复注册")
        self._agents[card.agent_id] = card

    def unregister(self, agent_id: str) -> None:
        """注销智能体，注销不存在的智能体抛出异常"""
        if agent_id not in self._agents:
            raise ValueError(f"智能体 {agent_id} 未注册，无法注销")
        del self._agents[agent_id]

    def get(self, agent_id: str) -> AgentCard | None:
        """获取智能体卡片，不存在返回 None"""
        return self._agents.get(agent_id)

    def list_all(self) -> list[AgentCard]:
        """列出所有已注册智能体"""
        return list(self._agents.values())
