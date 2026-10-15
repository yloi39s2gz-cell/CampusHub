"""梧桐平台适配器 - 基于 acps-sdk 的真实平台对接

实现 ATR 注册辅助、ACS 构建、智能体发现、远程 RPC 调用等核心功能。
所有外部地址如未经官方文档确认，均标注为占位值。
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


# ═══════════════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════════════

class WutongError(Exception):
    """梧桐平台对接过程中的统一异常类型"""
    pass


# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════

@dataclass
class WutongConfig:
    """梧桐平台配置，从环境变量读取

    环境变量：
        WUTONG_REGISTRY_URL  - ATR 注册服务地址
        WUTONG_DISCOVERY_URL - ADP 发现服务地址
        WUTONG_CA_URL        - CA 证书服务地址
        WUTONG_LEADER_AIC    - 上游 Leader 智能体的 AIC 标识
    """

    # 待用户从 QQ 群文档确认，当前为占位值
    registry_url: str = field(
        default_factory=lambda: os.environ.get(
            "WUTONG_REGISTRY_URL",
            "http://localhost:9001"  # 占位值，待群文档确认
        )
    )

    # 待用户从 QQ 群文档确认，当前为占位值
    discovery_url: str = field(
        default_factory=lambda: os.environ.get(
            "WUTONG_DISCOVERY_URL",
            "http://localhost:9005"  # 占位值，待群文档确认
        )
    )

    # 待用户从 QQ 群文档确认，当前为占位值
    ca_url: str = field(
        default_factory=lambda: os.environ.get(
            "WUTONG_CA_URL",
            "http://localhost:9003"  # 占位值，待群文档确认
        )
    )

    leader_aic: str = field(
        default_factory=lambda: os.environ.get("WUTONG_LEADER_AIC", "")
    )

    def validate(self) -> None:
        """校验必填项是否已配置"""
        if not self.leader_aic:
            raise WutongError(
                "未配置 WUTONG_LEADER_AIC 环境变量，"
                "请从 QQ 群 1102086449 获取官方接入文档后设置"
            )


# ═══════════════════════════════════════════════════
# ACS 构建
# ═══════════════════════════════════════════════════

def build_acs(agent_card) -> dict:
    """将项目内 AgentCard 转换为标准 ACS JSON 格式

    参照官方示例 partners/online/china_hotel/acs.json 的字段结构。
    skills 从智能体的 capabilities 列表生成，每个能力对应一个 skill。

    Args:
        agent_card: AgentCard 实例（见 aip_adapter/models.py）

    Returns:
        符合 ACS 规范的字典
    """
    # 从 capabilities 生成 skills 列表
    skills = []
    for cap in agent_card.capabilities:
        skill_id = f"{agent_card.agent_id}.{_slugify(cap)}"
        skills.append({
            "id": skill_id,
            "name": cap,
            "description": f"{agent_card.name}提供的{cap}能力。{agent_card.description}",
            "version": "1.0.0",
            "tags": [cap],
            "examples": [],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain", "application/json"],
        })

    # 构造端点列表
    end_points = []
    if agent_card.endpoint:
        end_points.append({
            "url": agent_card.endpoint,
            "transport": "JSONRPC",
            "security": [{"mtls": []}],
        })

    # 组装完整 ACS
    acs = {
        "aic": agent_card.agent_id,
        "active": True,
        "protocolVersion": agent_card.protocol_version,
        "name": agent_card.name,
        "description": agent_card.description,
        "version": agent_card.metadata.get("version", "1.0.0"),
        "provider": {
            "organization": agent_card.metadata.get(
                "provider_org", "待确认"  # 待用户在 acps-cli 注册时填写真实组织名
            ),
            "url": agent_card.metadata.get(
                "provider_url", "待确认"  # 待用户在 acps-cli 注册时填写真实 URL
            ),
        },
        "securitySchemes": {
            "mtls": {
                "type": "mutualTLS",
                "description": "智能体间mTLS双向认证",
            }
        },
        "endPoints": end_points,
        "certificate": {
            "altNames": {
                "dns": agent_card.metadata.get("dns_names", ["localhost"]),
            }
        },
        "capabilities": {
            "streaming": agent_card.metadata.get("streaming", False),
            "notification": agent_card.metadata.get("notification", False),
            "messageQueue": agent_card.metadata.get("message_queue", []),
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": skills,
    }

    return acs


def _slugify(text: str) -> str:
    """将中文能力名转为 URL 安全的短标识"""
    # 简单处理：保留字母数字和连字符
    result = []
    for ch in text:
        if ch.isalnum():
            result.append(ch.lower())
        elif ch in "-_ ":
            result.append("-")
    return "".join(result) or "skill"


# ═══════════════════════════════════════════════════
# ATR 注册指引
# ═══════════════════════════════════════════════════

def atr_guide(agent_card) -> list[str]:
    """生成 ATR 注册流程的 acps-cli 命令序列

    每条命令附带中文注释，覆盖完整流程：
    agent save → 提交审核 → 状态查询 → eab fetch → 证书申请

    Args:
        agent_card: AgentCard 实例

    Returns:
        命令字符串列表，每条含中文注释
    """
    acs_json = json.dumps(build_acs(agent_card), ensure_ascii=False, indent=2)
    acs_path = f"partners/online/{agent_card.agent_id}/acs.json"

    commands = [
        "# ═══ 第一步：登录 ATR 注册服务 ═══",
        "# 使用 acps-cli 登录到注册服务（会提示输入用户名和密码）",
        "acps-cli auth login",
        "",
        "# ═══ 第二步：准备 ACS 文件 ═══",
        f"# 将以下 ACS 内容保存到 {acs_path}",
        f"# （可通过 build_acs() 函数生成）",
        f"# 文件路径: {acs_path}",
        "",
        "# ═══ 第三步：提交 ACS 草稿到注册服务 ═══",
        "# agent save 将本地 ACS 文件上传到注册服务，生成待审核草稿",
        f"acps-cli agent save --file {acs_path}",
        "",
        "# ═══ 第四步：提交审核 ═══",
        "# 提交后等待管理员审批，此步骤为外部依赖，建议尽早提交",
        f"acps-cli agent submit --aic {agent_card.agent_id}",
        "",
        "# ═══ 第五步：查询审核状态 ═══",
        "# 反复查询直到管理员批准，获得正式 AIC 编号",
        f"acps-cli agent status --aic {agent_card.agent_id}",
        "",
        "# ═══ 第六步：获取 EAB 凭据 ═══",
        "# 审核通过后，获取 ACME External Account Binding 凭据",
        f"acps-cli cert eab fetch --aic {agent_card.agent_id}",
        "",
        "# ═══ 第七步：向 CA 申请证书（CAI）═══",
        "# 使用 EAB 凭据向 CA 服务申请 mTLS 客户端证书",
        f"acps-cli cert request --aic {agent_card.agent_id}",
        "",
        "# ═══ 注意事项 ═══",
        "# - 审核等待时间为外部依赖，可能需要数小时到数天",
        "# - 证书申请需要 CA 服务在线（见 WutongConfig.ca_url）",
        "# - 完成后将证书路径配置到 acps-cli.toml 的 [mq] 段",
    ]

    return commands


# ═══════════════════════════════════════════════════
# 智能体发现（ADP）
# ═══════════════════════════════════════════════════

async def discover_agents(
    query: str,
    limit: int = 5,
    config: WutongConfig | None = None,
) -> list[dict]:
    """通过 ADP 发现接口搜索远程智能体

    使用 httpx 向 {discovery_base_url}/acps-adp-v2/discover 发送 POST 请求，
    请求体通过 acps_sdk.adp.DiscoveryRequest 构造。

    Args:
        query: 搜索关键词
        limit: 返回结果数量上限
        config: 梧桐平台配置，为 None 时使用默认配置

    Returns:
        候选智能体列表，每个元素为 dict

    Raises:
        WutongError: 网络异常或 acps-sdk 未安装
    """
    try:
        from acps_sdk.adp import DiscoveryRequest
    except ImportError:
        raise WutongError(
            "缺少 acps-sdk 依赖，请运行: pip install acps-sdk"
        )

    cfg = config or WutongConfig()
    url = f"{cfg.discovery_url.rstrip('/')}/acps-adp-v2/discover"

    # 使用官方 SDK 的 DiscoveryRequest 构造请求体
    request = DiscoveryRequest(type="explicit", query=query, limit=limit)
    body = request.to_json()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            # 健壮解析：处理非 JSON、空响应等异常情况
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" not in content_type and resp.text.strip():
                # 服务端返回非 JSON 格式，尝试强制解析
                pass
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                # 非 JSON 响应，返回空列表而非崩溃
                return []
    except httpx.HTTPError as e:
        raise WutongError(f"发现服务请求失败: {e}") from e

    # 解析响应，提取候选智能体列表
    # 响应格式取决于服务端实现，这里兼容常见结构
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 检查是否有错误码
        if "error" in data or "code" in data:
            error_msg = data.get("error", data.get("message", "未知错误"))
            raise WutongError(f"发现服务返回错误: {error_msg}")
        # 尝试常见的列表字段名
        for key in ("agents", "results", "items", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # 如果整个 dict 就是单个结果，包装为列表
        return [data]
    return []


# ═══════════════════════════════════════════════════
# 远程 RPC 调用（Direct RPC）
# ═══════════════════════════════════════════════════

async def invoke_remote(
    partner_url: str,
    leader_aic: str,
    user_input: str,
    ssl_context: Any = None,
) -> dict:
    """通过 AipRpcClient 发起 Direct RPC 调用

    使用 acps-sdk 的 AipRpcClient 与远端智能体建立任务会话，
    提交用户输入并等待任务完成，返回任务结果摘要。

    Args:
        partner_url: 远端智能体的 RPC 端点地址
        leader_aic: 上游 Leader 智能体的 AIC 标识
        user_input: 用户输入文本
        ssl_context: 可选的 SSL 上下文（用于 mTLS）

    Returns:
        任务结果摘要 dict，包含 task_id / state / output

    Raises:
        WutongError: acps-sdk 未安装或调用失败
    """
    try:
        from acps_sdk.aip import AipRpcClient
    except ImportError:
        raise WutongError(
            "缺少 acps-sdk 依赖，无法发起 RPC 调用。"
            "请运行: pip install acps-sdk"
        )

    client = AipRpcClient(
        partner_url=partner_url,
        leader_id=leader_aic,
        ssl_context=ssl_context,
    )

    try:
        # 启动新任务
        task_id = await client.start_task(
            session_id="default",
            user_input=user_input,
        )

        # 轮询任务状态直到完成
        import asyncio
        max_polls = 60  # 最多轮询 60 次
        poll_interval = 1.0  # 每次间隔 1 秒
        # 单次 get_task 调用的超时，防止服务端 hang 导致无限等待
        single_call_timeout = 5.0

        for _ in range(max_polls):
            try:
                task_info = await asyncio.wait_for(
                    client.get_task(
                        task_id=task_id,
                        session_id="default",
                    ),
                    timeout=single_call_timeout,
                )
            except asyncio.TimeoutError:
                # 单次轮询超时，继续下一次轮询
                continue

            state = _extract_state(task_info)
            if state in ("completed", "failed", "cancelled"):
                return {
                    "task_id": task_id,
                    "state": state,
                    "output": _extract_output(task_info),
                }

            await asyncio.sleep(poll_interval)

        # 超时后取消任务
        await client.cancel_task(task_id=task_id, session_id="default")
        return {
            "task_id": task_id,
            "state": "timeout",
            "output": "任务执行超时，已自动取消",
        }

    except Exception as e:
        raise WutongError(f"RPC 调用失败: {e}") from e
    finally:
        await client.close()


def _extract_state(task_info: Any) -> str:
    """从任务信息中提取状态字段"""
    if isinstance(task_info, dict):
        return task_info.get("state", task_info.get("status", "unknown"))
    # Pydantic 模型
    if hasattr(task_info, "state"):
        return str(task_info.state)
    if hasattr(task_info, "status"):
        return str(task_info.status)
    return "unknown"


def _extract_output(task_info: Any) -> str:
    """从任务信息中提取输出内容"""
    if isinstance(task_info, dict):
        return task_info.get("output", task_info.get("result", ""))
    if hasattr(task_info, "output"):
        return str(task_info.output)
    if hasattr(task_info, "result"):
        return str(task_info.result)
    return ""


# ═══════════════════════════════════════════════════
# 兼容旧接口（保留 WutongAdapter 类）
# ═══════════════════════════════════════════════════

class WutongAdapter:
    """梧桐平台适配器接口

    封装 build_acs / atr_guide / discover_agents / invoke_remote，
    提供面向对象的调用方式。
    """

    def __init__(self, config: dict | None = None):
        """初始化梧桐适配器

        Args:
            config: 梧桐平台配置字典，支持以下键：
                - registry_url / discovery_url / ca_url / leader_aic
                - 也可通过环境变量设置（优先使用传入的 config）
        """
        # 先创建一个默认配置实例，获取环境变量默认值
        default_config = WutongConfig()
        cfg = config or {}
        # 使用传入的 config 覆盖默认值，避免多次实例化 WutongConfig
        self.config = WutongConfig(
            registry_url=cfg.get("registry_url", default_config.registry_url),
            discovery_url=cfg.get("discovery_url", default_config.discovery_url),
            ca_url=cfg.get("ca_url", default_config.ca_url),
            leader_aic=cfg.get("leader_aic", default_config.leader_aic),
        )

    async def register(self, agent_card) -> dict:
        """生成 ACS 并返回 ATR 注册指引

        实际注册需要通过 acps-cli 命令行完成（外部流程），
        此方法返回 ACS 内容和操作指引供用户执行。
        """
        acs = build_acs(agent_card)
        guide = atr_guide(agent_card)
        return {
            "acs": acs,
            "guide": guide,
            "message": "请按 guide 中的命令序列完成 ATR 注册",
        }

    async def discover(self, keyword: str) -> list:
        """从梧桐平台发现智能体"""
        return await discover_agents(keyword, config=self.config)

    async def send(self, from_id: str, to_id: str, payload: dict) -> dict:
        """通过梧桐平台发送消息（Direct RPC）"""
        partner_url = payload.get("endpoint", "")
        user_input = payload.get("query", payload.get("user_input", ""))

        if not partner_url:
            raise WutongError("缺少远端智能体端点地址 (endpoint)")

        leader = self.config.leader_aic or from_id
        return await invoke_remote(
            partner_url=partner_url,
            leader_aic=leader,
            user_input=user_input,
        )
