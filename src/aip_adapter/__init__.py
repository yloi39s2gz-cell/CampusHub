"""AIP 协议适配层 - 智能体卡片、注册表、发现服务、会话传输、梧桐平台对接"""

from .models import AgentCard
from .registry import AgentRegistry, InMemoryRegistry
from .discovery import AgentDiscovery
from .session import SessionTransport, MockTransport
from .wutong import (
    WutongAdapter,
    WutongConfig,
    WutongError,
    build_acs,
    atr_guide,
    discover_agents,
    invoke_remote,
)

__all__ = [
    "AgentCard",
    "AgentRegistry",
    "InMemoryRegistry",
    "AgentDiscovery",
    "SessionTransport",
    "MockTransport",
    "WutongAdapter",
    "WutongConfig",
    "WutongError",
    "build_acs",
    "atr_guide",
    "discover_agents",
    "invoke_remote",
]
