"""敏感词过滤器

支持常见绕过手段的防御：
- 大小写混合（英文词）
- 全角/半角字符混合
- 词中插入特殊字符（如空格、标点、零宽字符）
"""

import re
import unicodedata


class SensitiveFilter:
    """敏感词过滤器，内置中文敏感词表"""

    def __init__(self):
        """初始化敏感词表，按类别组织"""
        self.categories = {
            "政治": [
                "反动", "颠覆政权", "分裂国家", "恐怖主义",
            ],
            "暴力": [
                "杀人", "爆炸", "枪击", "血腥", "自杀方法",
            ],
            "色情": [
                "色情", "淫秽", "裸体", "性交易",
            ],
            "联系方式索取": [
                "加微信", "加QQ", "手机号", "私人电话", "约炮",
            ],
            "诈骗": [
                "中奖", "转账", "汇款", "银行卡号", "密码",
            ],
        }

        # 扁平化词表
        self.words: list[str] = []
        for category_words in self.categories.values():
            self.words.extend(category_words)

        # 预编译用于去除干扰字符的正则（匹配空格、标点、零宽字符等）
        # 使用标准 re 模块兼容的字符类，覆盖常见干扰字符
        self._noise_pattern = re.compile(
            r"[\s\u0020\u00a0\u2000-\u200f\u2028-\u202f\u205f-\u206f\ufeff"
            r"\u3000\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65"
            r".,;:!?@#$%^&*()_+\-=\[\]{}|\\\"'`~<>/"
            r"]",
            re.UNICODE,
        )

    def _normalize(self, text: str) -> str:
        """
        规范化文本，去除常见绕过手段：
        1. 全角转半角
        2. 统一大小写
        3. 去除干扰字符（空格、标点、零宽字符）
        """
        # 全角转半角
        normalized = unicodedata.normalize("NFKC", text)
        # 统一大小写（英文词）
        normalized = normalized.lower()
        # 去除干扰字符
        normalized = self._noise_pattern.sub("", normalized)
        return normalized

    def filter(self, text: str) -> tuple[str, list[str]]:
        """
        过滤敏感词

        Args:
            text: 待过滤文本

        Returns:
            (clean_text, hits): 过滤后的文本和命中的敏感词列表
        """
        hits = []
        clean_text = text

        for word in self.words:
            if word in clean_text:
                hits.append(word)
                clean_text = clean_text.replace(word, "***")

        return clean_text, hits

    def check(self, text: str) -> bool:
        """
        检查文本是否包含敏感词（含绕过检测）

        Returns:
            True 表示安全，False 表示包含敏感词
        """
        # 先检查原文
        if any(word in text for word in self.words):
            return False
        # 再检查规范化后的文本（防御绕过）
        # 同时对词表做规范化，确保大小写/全角等变体被覆盖
        normalized = self._normalize(text)
        for word in self.words:
            normalized_word = self._normalize(word)
            if normalized_word in normalized:
                return False
        return True

    def add_word(self, word: str, category: str = "自定义") -> None:
        """添加敏感词"""
        if word not in self.words:
            self.words.append(word)
            if category not in self.categories:
                self.categories[category] = []
            if word not in self.categories[category]:
                self.categories[category].append(word)
