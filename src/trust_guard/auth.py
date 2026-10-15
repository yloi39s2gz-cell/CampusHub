"""基于 HMAC-SHA256 的 Token 认证"""

import hashlib
import hmac
import json
import os
import time
import base64


class TokenAuth:
    """Token 认证器，基于 HMAC-SHA256 签发与校验"""

    def __init__(self, secret: str | None = None):
        """
        初始化认证器

        Args:
            secret: HMAC 密钥，优先从参数读取，否则从环境变量 ZHISHU_SECRET 读取
        """
        self.secret = secret or os.environ.get("ZHISHU_SECRET", "zhishu-default-secret")

    def issue(self, subject: str, ttl_seconds: int = 3600) -> str:
        """
        签发 Token

        Args:
            subject: 主体标识（如用户 ID、智能体 ID）
            ttl_seconds: 有效期（秒），默认 1 小时

        Returns:
            Base64 编码的 Token 字符串
        """
        payload = {
            "sub": subject,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl_seconds,
        }

        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        payload_bytes = payload_json.encode("utf-8")

        # 计算 HMAC-SHA256 签名
        signature = hmac.new(
            self.secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).digest()

        # 组合 payload + signature 并 Base64 编码
        token_data = payload_bytes + b"." + signature
        return base64.urlsafe_b64encode(token_data).decode("utf-8")

    def verify(self, token: str) -> str | None:
        """
        校验 Token

        Args:
            token: Base64 编码的 Token 字符串

        Returns:
            校验通过返回 subject，失败返回 None
        """
        try:
            # Base64 解码
            token_data = base64.urlsafe_b64decode(token.encode("utf-8"))

            # 分离 payload 和 signature
            # HMAC-SHA256 签名固定 32 字节，用长度切分避免签名中含 "." 字节导致 rsplit 误切
            if len(token_data) <= 33:  # 至少 1 字节 payload + 1 字节分隔符 + 32 字节签名
                return None
            separator_pos = len(token_data) - 33  # 32 字节签名 + 1 字节分隔符
            if token_data[separator_pos:separator_pos + 1] != b".":
                return None
            payload_bytes = token_data[:separator_pos]
            signature = token_data[separator_pos + 1:]

            # 验证签名
            expected_signature = hmac.new(
                self.secret.encode("utf-8"),
                payload_bytes,
                hashlib.sha256,
            ).digest()

            if not hmac.compare_digest(signature, expected_signature):
                return None

            # 解析 payload
            payload = json.loads(payload_bytes.decode("utf-8"))

            # 检查过期时间
            exp = payload.get("exp")
            if exp and time.time() > exp:
                return None

            return payload.get("sub")

        except Exception:
            return None
