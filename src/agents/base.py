"""智能体基类"""

from abc import ABC, abstractmethod
from aip_adapter.models import AgentCard
from trust_guard.sensitive import SensitiveFilter


class BaseAgent(ABC):
    """智能体基类，提供统一的接口、敏感词过滤与 LLM 辅助能力"""

    def __init__(self):
        self._sensitive_filter = SensitiveFilter()
        # LLM 后端延迟初始化，避免未配置时影响所有智能体启动
        self._llm_backend = None

    @property
    @abstractmethod
    def agent_card(self) -> AgentCard:
        """返回智能体名片"""
        pass

    @abstractmethod
    def handle_message(self, payload: dict) -> dict:
        """
        处理消息

        Args:
            payload: 消息体，规范格式 {query: str, context: dict}

        Returns:
            规范响应体 {ok: bool, answer: str|dict, agent_id: str}
        """
        pass

    def _filter_output(self, answer: str | dict) -> str | dict:
        """对输出进行敏感词过滤"""
        if isinstance(answer, str):
            clean_text, _ = self._sensitive_filter.filter(answer)
            return clean_text
        elif isinstance(answer, dict):
            # 对字典中的字符串值进行过滤
            filtered = {}
            for key, value in answer.items():
                if isinstance(value, str):
                    clean_text, _ = self._sensitive_filter.filter(value)
                    filtered[key] = clean_text
                else:
                    filtered[key] = value
            return filtered
        return answer

    def _llm_complete(self, prompt: str, system: str | None = None) -> str | None:
        """
        调用 LLM 生成文本，失败时返回 None 由调用方降级

        设计原则：
        - 有 API KEY 且调用成功：返回模型生成的文本
        - 无 API KEY（LLMNotConfiguredError）：返回 None
        - 任何其他异常（网络/HTTP/解析）：返回 None
        - 绝不把异常抛到 handle_message 之外

        Args:
            prompt: 用户提示词
            system: 可选系统提示词

        Returns:
            模型回复文本，或 None（表示应降级到规则逻辑）
        """
        # 延迟初始化 LLM 后端
        if self._llm_backend is None:
            from hetero_gateway.llm_backend import LLMBackend
            self._llm_backend = LLMBackend()

        try:
            messages = [{"role": "user", "content": prompt}]
            return self._llm_backend.chat(messages, system=system)
        except Exception:
            # 任何异常（含 LLMNotConfiguredError、LLMError、网络错误等）
            # 都静默返回 None，由调用方决定降级策略
            return None
