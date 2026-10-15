"""智能体卡片数据模型"""

from pydantic import BaseModel, Field


class AgentCard(BaseModel):
    """智能体名片，描述智能体的身份、能力与接入点"""

    agent_id: str = Field(..., description="智能体唯一标识")
    name: str = Field(..., description="智能体名称")
    description: str = Field(default="", description="智能体功能描述")
    capabilities: list[str] = Field(default_factory=list, description="能力关键词列表")
    endpoint: str = Field(default="", description="服务端点地址")
    protocol_version: str = Field(default="1.0", description="协议版本")
    metadata: dict = Field(default_factory=dict, description="扩展元数据")

    def has_capability(self, keyword: str) -> bool:
        """检查是否包含某能力关键词（大小写不敏感）"""
        keyword_lower = keyword.lower()
        return any(keyword_lower in cap.lower() for cap in self.capabilities)
