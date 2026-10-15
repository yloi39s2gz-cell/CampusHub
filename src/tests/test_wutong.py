"""梧桐平台对接模块测试 - ACS 构建 / 发现 / ATR 指引"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from aip_adapter import AgentCard, WutongConfig, WutongError, build_acs, atr_guide


# ═══════════════════════════════════════════════════
# 1. build_acs 字段完整性
# ═══════════════════════════════════════════════════

class TestBuildAcs:
    """build_acs 字段完整性测试"""

    def _make_card(self, **overrides):
        """构造测试用 AgentCard"""
        defaults = dict(
            agent_id="test-agent",
            name="测试智能体",
            description="用于测试的智能体",
            capabilities=["课程查询", "图书检索"],
            endpoint="https://localhost:9024/rpc",
            protocol_version="02.02",
            metadata={"version": "1.0.0"},
        )
        defaults.update(overrides)
        return AgentCard(**defaults)

    def test_acs_has_required_top_level_fields(self):
        """ACS 包含所有必需的顶层字段"""
        card = self._make_card()
        acs = build_acs(card)

        required_keys = {
            "aic", "active", "protocolVersion", "name", "description",
            "version", "provider", "securitySchemes", "endPoints",
            "certificate", "capabilities", "defaultInputModes",
            "defaultOutputModes", "skills",
        }
        for key in required_keys:
            assert key in acs, f"ACS 缺少必需字段: {key}"

    def test_acs_aic_matches_agent_id(self):
        """ACS 的 aic 字段与 AgentCard 的 agent_id 一致"""
        card = self._make_card(agent_id="my-unique-id")
        acs = build_acs(card)
        assert acs["aic"] == "my-unique-id"

    def test_acs_active_is_true(self):
        """ACS 的 active 字段为 True"""
        card = self._make_card()
        acs = build_acs(card)
        assert acs["active"] is True

    def test_acs_protocol_version(self):
        """ACS 的 protocolVersion 来自 AgentCard"""
        card = self._make_card(protocol_version="03.00")
        acs = build_acs(card)
        assert acs["protocolVersion"] == "03.00"

    def test_acs_provider_structure(self):
        """ACS 的 provider 包含 organization 和 url"""
        card = self._make_card()
        acs = build_acs(card)
        assert "organization" in acs["provider"]
        assert "url" in acs["provider"]

    def test_acs_security_schemes_mtls(self):
        """ACS 的 securitySchemes 包含 mtls 配置"""
        card = self._make_card()
        acs = build_acs(card)
        assert "mtls" in acs["securitySchemes"]
        assert acs["securitySchemes"]["mtls"]["type"] == "mutualTLS"

    def test_acs_endpoints_from_agent_card(self):
        """ACS 的 endPoints 从 AgentCard.endpoint 生成"""
        card = self._make_card(endpoint="https://example.com:9024/rpc")
        acs = build_acs(card)
        assert len(acs["endPoints"]) == 1
        ep = acs["endPoints"][0]
        assert ep["url"] == "https://example.com:9024/rpc"
        assert ep["transport"] == "JSONRPC"
        assert ep["security"] == [{"mtls": []}]

    def test_acs_endpoints_empty_when_no_endpoint(self):
        """AgentCard 无 endpoint 时 endPoints 为空列表"""
        card = self._make_card(endpoint="")
        acs = build_acs(card)
        assert acs["endPoints"] == []

    def test_acs_skills_from_capabilities(self):
        """ACS 的 skills 从 capabilities 生成"""
        card = self._make_card(capabilities=["课程查询", "图书检索"])
        acs = build_acs(card)
        assert len(acs["skills"]) == 2

        skill_names = {s["name"] for s in acs["skills"]}
        assert "课程查询" in skill_names
        assert "图书检索" in skill_names

    def test_acs_skill_structure(self):
        """每个 skill 包含完整的字段结构"""
        card = self._make_card(capabilities=["测试能力"])
        acs = build_acs(card)
        skill = acs["skills"][0]

        required_skill_keys = {
            "id", "name", "description", "version",
            "tags", "examples", "inputModes", "outputModes",
        }
        for key in required_skill_keys:
            assert key in skill, f"skill 缺少字段: {key}"

    def test_acs_capabilities_structure(self):
        """ACS 的 capabilities 包含 streaming/notification/messageQueue"""
        card = self._make_card()
        acs = build_acs(card)
        caps = acs["capabilities"]
        assert "streaming" in caps
        assert "notification" in caps
        assert "messageQueue" in caps

    def test_acs_default_io_modes(self):
        """ACS 的默认输入输出模式"""
        card = self._make_card()
        acs = build_acs(card)
        assert acs["defaultInputModes"] == ["text/plain"]
        assert "text/plain" in acs["defaultOutputModes"]
        assert "application/json" in acs["defaultOutputModes"]

    def test_acs_is_json_serializable(self):
        """ACS 可序列化为 JSON"""
        card = self._make_card()
        acs = build_acs(card)
        json_str = json.dumps(acs, ensure_ascii=False)
        assert len(json_str) > 0
        parsed = json.loads(json_str)
        assert parsed["aic"] == card.agent_id


# ═══════════════════════════════════════════════════
# 2. discover_agents 使用 mock httpx
# ═══════════════════════════════════════════════════

class TestDiscoverAgents:
    """discover_agents 发现功能测试（mock httpx）"""

    @pytest.mark.asyncio
    async def test_discover_returns_agent_list(self):
        """发现接口返回智能体列表"""
        # 模拟 httpx 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "agents": [
                {"aic": "agent-1", "name": "智能体1"},
                {"aic": "agent-2", "name": "智能体2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # 模拟 DiscoveryRequest
        mock_request = MagicMock()
        mock_request.to_json.return_value = '{"type":"explicit","query":"酒店","limit":5}'

        # 模拟 acps_sdk 模块（不需要真实安装）
        mock_acps_sdk = MagicMock()
        mock_acps_sdk.adp.DiscoveryRequest = MagicMock(return_value=mock_request)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict("sys.modules", {"acps_sdk": mock_acps_sdk, "acps_sdk.adp": mock_acps_sdk.adp}):
                from aip_adapter.wutong import discover_agents, WutongConfig
                config = WutongConfig(discovery_url="http://mock:9005")
                results = await discover_agents("酒店", limit=5, config=config)

        assert len(results) == 2
        assert results[0]["aic"] == "agent-1"

    @pytest.mark.asyncio
    async def test_discover_handles_list_response(self):
        """发现接口直接返回列表格式"""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"aic": "agent-x", "name": "X"},
        ]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_request = MagicMock()
        mock_request.to_json.return_value = '{"type":"explicit","query":"test","limit":3}'

        mock_acps_sdk = MagicMock()
        mock_acps_sdk.adp.DiscoveryRequest = MagicMock(return_value=mock_request)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict("sys.modules", {"acps_sdk": mock_acps_sdk, "acps_sdk.adp": mock_acps_sdk.adp}):
                from aip_adapter.wutong import discover_agents, WutongConfig
                config = WutongConfig(discovery_url="http://mock:9005")
                results = await discover_agents("test", limit=3, config=config)

        assert len(results) == 1
        assert results[0]["aic"] == "agent-x"

    @pytest.mark.asyncio
    async def test_discover_raises_wutong_error_on_network_failure(self):
        """网络异常时抛 WutongError"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("连接被拒绝"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_request = MagicMock()
        mock_request.to_json.return_value = '{"type":"explicit","query":"test","limit":5}'

        mock_acps_sdk = MagicMock()
        mock_acps_sdk.adp.DiscoveryRequest = MagicMock(return_value=mock_request)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict("sys.modules", {"acps_sdk": mock_acps_sdk, "acps_sdk.adp": mock_acps_sdk.adp}):
                from aip_adapter.wutong import discover_agents, WutongConfig
                config = WutongConfig(discovery_url="http://mock:9005")

                with pytest.raises(WutongError, match="发现服务请求失败"):
                    await discover_agents("test", config=config)


# ═══════════════════════════════════════════════════
# 3. atr_guide 命令序列
# ═══════════════════════════════════════════════════

class TestAtrGuide:
    """atr_guide 命令序列测试"""

    def test_guide_is_non_empty(self):
        """ATR 指引命令序列非空"""
        card = AgentCard(
            agent_id="test-guide",
            name="测试",
            capabilities=["查询"],
        )
        guide = atr_guide(card)
        assert len(guide) > 0

    def test_guide_contains_auth_login(self):
        """指引包含 auth login 命令"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "acps-cli auth login" in guide_text

    def test_guide_contains_agent_save(self):
        """指引包含 agent save 命令"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "acps-cli agent save" in guide_text

    def test_guide_contains_agent_submit(self):
        """指引包含提交审核命令"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "acps-cli agent submit" in guide_text

    def test_guide_contains_eab_fetch(self):
        """指引包含 eab fetch 命令"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "cert eab fetch" in guide_text

    def test_guide_contains_cert_request(self):
        """指引包含证书申请命令"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "cert request" in guide_text

    def test_guide_contains_agent_id(self):
        """指引中包含智能体的 agent_id"""
        card = AgentCard(agent_id="my-special-agent", name="T", capabilities=[])
        guide = atr_guide(card)
        guide_text = "\n".join(guide)
        assert "my-special-agent" in guide_text

    def test_guide_all_strings(self):
        """指引中每条都是字符串"""
        card = AgentCard(agent_id="t", name="T", capabilities=[])
        guide = atr_guide(card)
        for item in guide:
            assert isinstance(item, str)


# ═══════════════════════════════════════════════════
# 4. WutongConfig 配置
# ═══════════════════════════════════════════════════

class TestWutongConfig:
    """WutongConfig 配置测试"""

    def test_default_values(self):
        """默认配置值存在"""
        config = WutongConfig()
        assert config.registry_url != ""
        assert config.discovery_url != ""
        assert config.ca_url != ""

    def test_validate_raises_without_leader_aic(self):
        """未配置 leader_aic 时 validate 抛异常"""
        config = WutongConfig(leader_aic="")
        with pytest.raises(WutongError, match="WUTONG_LEADER_AIC"):
            config.validate()

    def test_validate_passes_with_leader_aic(self):
        """配置了 leader_aic 后 validate 通过"""
        config = WutongConfig(leader_aic="some-aic")
        config.validate()  # 不应抛异常


# ═══════════════════════════════════════════════════
# 5. invoke_remote ImportError 友好提示
# ═══════════════════════════════════════════════════

class TestInvokeRemoteImportError:
    """invoke_remote 在 acps-sdk 未安装时的友好错误"""

    @pytest.mark.asyncio
    async def test_invoke_remote_missing_sdk(self):
        """acps-sdk 未安装时抛出友好提示"""
        with patch.dict("sys.modules", {"acps_sdk": None, "acps_sdk.aip": None}):
            from aip_adapter.wutong import invoke_remote
            with pytest.raises(WutongError, match="pip install acps-sdk"):
                await invoke_remote(
                    partner_url="https://example.com/rpc",
                    leader_aic="test-leader",
                    user_input="你好",
                )
