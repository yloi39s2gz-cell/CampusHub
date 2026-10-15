"""会话传输层 - 消息发送抽象与本地 Mock 实现"""

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Protocol
from .registry import AgentRegistry


# 消息日志最大保留条数，防止无界增长
_MAX_MESSAGE_LOG = 2000


class MessageHandler(Protocol):
    """消息处理协议，智能体需实现此接口"""

    def handle_message(self, payload: dict) -> dict:
        """处理消息并返回响应"""
        ...


class SessionTransport(ABC):
    """会话传输抽象基类"""

    @abstractmethod
    async def send_message(
        self, from_id: str, to_id: str, payload: dict
    ) -> dict:
        """发送消息并返回响应"""
        pass


class MockTransport(SessionTransport):
    """本地 Mock 传输实现，直接调用智能体的 handle_message"""

    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        # 使用 deque 限制容量，防止无界增长
        self.message_log: deque[dict] = deque(maxlen=_MAX_MESSAGE_LOG)

    async def send_message(
        self, from_id: str, to_id: str, payload: dict
    ) -> dict:
        """
        发送消息：通过 registry 找到目标 agent 并调用其 handle_message

        使用 asyncio.to_thread 将同步的 handle_message 放到线程池执行，
        避免阻塞事件循环（部分智能体可能调用 LLM 等阻塞 IO）。

        返回规范体：
        - 成功: {ok: True, data: ..., agent_id: ...}
        - 失败: {ok: False, error: "...", agent_id: None}
        """
        # 记录消息
        self.message_log.append({
            "from": from_id,
            "to": to_id,
            "payload": payload,
        })

        # 查找目标智能体
        target_card = self.registry.get(to_id)
        if not target_card:
            return {
                "ok": False,
                "error": f"目标智能体 {to_id} 不存在",
                "agent_id": None,
            }

        # 获取智能体实例（从 metadata 中）
        agent_instance = target_card.metadata.get("instance")
        if not agent_instance:
            return {
                "ok": False,
                "error": f"智能体 {to_id} 未提供处理实例",
                "agent_id": to_id,
            }

        try:
            # 在线程池中调用同步的 handle_message，避免阻塞事件循环
            result = await asyncio.to_thread(agent_instance.handle_message, payload)
            return {
                "ok": True,
                "data": result,
                "agent_id": to_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"智能体处理消息时发生错误: {str(e)}",
                "agent_id": to_id,
            }
