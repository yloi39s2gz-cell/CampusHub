"""LLM 后端适配器 - 对接 OpenAI-compatible 的 chat completions 接口"""

import os
import httpx


class LLMError(Exception):
    """LLM 调用异常基类（网络/HTTP/解析等错误）"""
    pass


class LLMNotConfiguredError(LLMError):
    """未配置 LLM_API_KEY 时抛出的异常"""
    pass


class LLMBackend:
    """
    OpenAI-compatible chat completions 客户端

    通过 httpx 调用 POST {base_url}/chat/completions，
    不依赖 openai 官方 SDK，降低安装成本。
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        """
        初始化 LLM 后端

        配置优先级：显式参数 > 环境变量 > 默认值
        """
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        # 容错处理：环境变量 LLM_TIMEOUT 可能为非法值，回退到默认 30 秒
        if timeout is not None:
            self.timeout = timeout
        else:
            try:
                self.timeout = float(os.environ.get("LLM_TIMEOUT", "30"))
            except (ValueError, TypeError):
                self.timeout = 30.0

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        """
        调用 chat completions 接口

        Args:
            messages: 对话历史，格式 [{"role": "user"|"assistant"|"system", "content": "..."}]
            system: 可选的系统提示词，若提供则插入到消息列表最前面

        Returns:
            模型回复的文本内容

        Raises:
            LLMNotConfiguredError: 未配置 LLM_API_KEY
            LLMError: 网络/HTTP/解析错误
        """
        # 未配置 API KEY 时立即抛出友好异常
        if not self.api_key:
            raise LLMNotConfiguredError(
                "未配置 LLM_API_KEY 环境变量。请设置有效的 API KEY 后重试，"
                "或留空以使用规则降级逻辑。"
            )

        # 组装完整消息列表（system 在最前）
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": full_messages,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            # 网络层错误（连接超时、DNS 解析失败等）
            raise LLMError(f"LLM 请求失败: {e}") from e

        # HTTP 状态码非 2xx 时抛异常
        if resp.status_code >= 400:
            raise LLMError(
                f"LLM 返回错误状态 {resp.status_code}: {resp.text[:200]}"
            )

        # 解析响应
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"LLM 响应解析失败: {e}") from e

        # 返回文本（部分接口可能返回 None）
        return content if isinstance(content, str) else str(content)
