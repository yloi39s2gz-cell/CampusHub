"""异构适配器抽象基类"""

from abc import ABC, abstractmethod
from aip_adapter.models import AgentCard


class HeteroAdapter(ABC):
    """异构协议适配器抽象基类，将不同协议翻译为 AIP 标准"""

    @abstractmethod
    def to_agent_card(self) -> AgentCard:
        """将原生服务描述转换为 AIP AgentCard"""
        pass

    @abstractmethod
    def translate_invoke(self, aip_request: dict) -> dict:
        """
        将 AIP 调用请求翻译为原生协议请求

        Args:
            aip_request: AIP 标准格式的请求，包含 capability, params 等

        Returns:
            原生协议格式的请求
        """
        pass

    @abstractmethod
    def normalize_result(self, native_result) -> dict:
        """
        将原生协议的结果归一化为 AIP 消息格式

        Args:
            native_result: 原生协议的返回结果

        Returns:
            AIP 标准格式的响应 {ok, data, protocol}
        """
        pass
