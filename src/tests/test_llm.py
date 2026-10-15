"""LLM 后端与课程问答智能体 LLM 混合架构测试"""

import pytest
from unittest.mock import patch, MagicMock

from hetero_gateway.llm_backend import LLMBackend, LLMError, LLMNotConfiguredError
from agents.course_qa import CourseQAAgent


# ═══════════════════════════════════════════════════
# 1. LLMBackend 单元测试
# ═══════════════════════════════════════════════════

class TestLLMBackend:
    """LLMBackend 类测试"""

    def test_chat_success(self):
        """chat 成功路径：mock httpx 返回正常响应"""
        backend = LLMBackend(api_key="test-key", base_url="https://api.test.com/v1")

        # 构造 mock 响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": "这是模型回复"}}
            ]
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = backend.chat([{"role": "user", "content": "你好"}])

        assert result == "这是模型回复"
        mock_client.post.assert_called_once()

        # 验证请求参数
        call_kwargs = mock_client.post.call_args
        assert "chat/completions" in call_kwargs.args[0]
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-key"

    def test_chat_with_system_prompt(self):
        """chat 带 system prompt"""
        backend = LLMBackend(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "回复"}}]
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            backend.chat(
                [{"role": "user", "content": "问题"}],
                system="你是助手"
            )

        # 验证 messages 中包含 system 消息
        call_kwargs = mock_client.post.call_args
        messages = call_kwargs.kwargs["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "你是助手"
        assert messages[1]["role"] == "user"

    def test_chat_http_error(self):
        """chat HTTP 错误路径：非 2xx 状态码抛 LLMError"""
        backend = LLMBackend(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError, match="500"):
                backend.chat([{"role": "user", "content": "你好"}])

    def test_chat_network_error(self):
        """chat 网络错误路径：httpx 异常转 LLMError"""
        import httpx
        backend = LLMBackend(api_key="test-key")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("连接失败")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError, match="请求失败"):
                backend.chat([{"role": "user", "content": "你好"}])

    def test_chat_no_api_key_raises_not_configured(self):
        """无 API KEY 时 chat 抛 LLMNotConfiguredError"""
        backend = LLMBackend(api_key="")

        with pytest.raises(LLMNotConfiguredError, match="LLM_API_KEY"):
            backend.chat([{"role": "user", "content": "你好"}])

    def test_chat_no_api_key_from_env(self):
        """环境变量无 LLM_API_KEY 时也抛 LLMNotConfiguredError"""
        with patch.dict("os.environ", {"LLM_API_KEY": ""}, clear=False):
            backend = LLMBackend()
            with pytest.raises(LLMNotConfiguredError):
                backend.chat([{"role": "user", "content": "你好"}])

    def test_config_from_env(self):
        """从环境变量读取配置"""
        env = {
            "LLM_BASE_URL": "https://custom.api.com/v1",
            "LLM_API_KEY": "env-key",
            "LLM_MODEL": "custom-model",
            "LLM_TIMEOUT": "60",
        }
        with patch.dict("os.environ", env, clear=False):
            backend = LLMBackend()
            assert backend.base_url == "https://custom.api.com/v1"
            assert backend.api_key == "env-key"
            assert backend.model == "custom-model"
            assert backend.timeout == 60.0

    def test_config_defaults(self):
        """默认配置值"""
        with patch.dict("os.environ", {}, clear=False):
            # 清除可能存在的环境变量
            import os
            os.environ.pop("LLM_BASE_URL", None)
            os.environ.pop("LLM_API_KEY", None)
            os.environ.pop("LLM_MODEL", None)
            os.environ.pop("LLM_TIMEOUT", None)

            backend = LLMBackend()
            assert backend.base_url == "https://api.openai.com/v1"
            assert backend.model == "gpt-4o-mini"
            assert backend.timeout == 30.0


# ═══════════════════════════════════════════════════
# 2. CourseQAAgent LLM 混合架构测试
# ═══════════════════════════════════════════════════

class TestCourseQAHybrid:
    """课程问答智能体 LLM+规则混合架构测试"""

    def test_llm_unavailable_fallback_to_rules(self):
        """LLM 不可用时降级到规则逻辑"""
        agent = CourseQAAgent()

        # mock _llm_complete 返回 None（模拟无 API KEY 或网络错误）
        with patch.object(agent, "_llm_complete", return_value=None):
            result = agent.handle_message({"query": "高等数学"})

        assert result["ok"] is True
        assert result["agent_id"] == "course-qa"
        # 断言答案来自规则库（包含课程信息）
        assert "高等数学" in result["answer"]
        assert "教学楼 A201" in result["answer"]

    def test_llm_unavailable_faq_rules(self):
        """LLM 不可用时 FAQ 降级到规则"""
        agent = CourseQAAgent()

        with patch.object(agent, "_llm_complete", return_value=None):
            result = agent.handle_message({"query": "怎么选课"})

        assert result["ok"] is True
        assert "开学前两周" in result["answer"]

    def test_llm_success_path(self):
        """LLM 可用时走 LLM 路径"""
        agent = CourseQAAgent()

        # mock _llm_complete 返回文本
        llm_answer = "根据课程表，高等数学安排在教学楼 A201，学分 4 分。"
        with patch.object(agent, "_llm_complete", return_value=llm_answer):
            result = agent.handle_message({"query": "高等数学在哪里上课"})

        assert result["ok"] is True
        assert result["answer"] == llm_answer

    def test_llm_empty_string_fallback(self):
        """LLM 返回空字符串时降级到规则"""
        agent = CourseQAAgent()

        with patch.object(agent, "_llm_complete", return_value=""):
            result = agent.handle_message({"query": "绩点怎么算"})

        assert result["ok"] is True
        # 降级到规则库
        assert "绩点" in result["answer"]

    def test_llm_whitespace_only_fallback(self):
        """LLM 返回纯空白时降级到规则"""
        agent = CourseQAAgent()

        with patch.object(agent, "_llm_complete", return_value="   \n  "):
            result = agent.handle_message({"query": "补考安排"})

        assert result["ok"] is True
        assert "补考" in result["answer"]

    def test_agent_card_has_llm_hybrid_metadata(self):
        """agent_card 的 metadata 包含 llm_hybrid 标注"""
        agent = CourseQAAgent()
        card = agent.agent_card

        assert card.metadata.get("llm_hybrid") is True

    def test_output_still_filtered(self):
        """LLM 输出仍经过敏感词过滤"""
        agent = CourseQAAgent()

        # 假设 LLM 返回含敏感词的内容
        sensitive_text = "这个内容涉及反动信息"
        with patch.object(agent, "_llm_complete", return_value=sensitive_text):
            result = agent.handle_message({"query": "测试"})

        assert result["ok"] is True
        # 敏感词应被过滤掉
        assert "反动" not in result["answer"]

    def test_rule_fallback_unknown_query(self):
        """规则降级：未知问题返回兜底回复"""
        agent = CourseQAAgent()

        with patch.object(agent, "_llm_complete", return_value=None):
            result = agent.handle_message({"query": "今天天气怎么样"})

        assert result["ok"] is True
        assert "暂时无法回答" in result["answer"]
