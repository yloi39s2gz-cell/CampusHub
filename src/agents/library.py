"""图书馆检索智能体"""

from .base import BaseAgent
from aip_adapter.models import AgentCard


class LibraryAgent(BaseAgent):
    """图书馆检索智能体，支持按书名/作者模糊检索"""

    def __init__(self):
        super().__init__()

        # 模拟馆藏数据
        self.books = [
            {
                "title": "Python编程从入门到实践",
                "author": "Eric Matthes",
                "call_number": "TP311.561/M38",
                "status": "可借",
                "location": "三楼计算机借阅区",
            },
            {
                "title": "数据结构与算法分析",
                "author": "Mark Allen Weiss",
                "call_number": "TP312/W45",
                "status": "可借",
                "location": "三楼计算机借阅区",
            },
            {
                "title": "高等数学",
                "author": "同济大学数学系",
                "call_number": "O13/T42",
                "status": "借出",
                "location": "二楼自然科学借阅区",
            },
            {
                "title": "线性代数",
                "author": "同济大学数学系",
                "call_number": "O151.2/T42",
                "status": "可借",
                "location": "二楼自然科学借阅区",
            },
            {
                "title": "大学英语综合教程",
                "author": "何兆熊",
                "call_number": "H319.4/H28",
                "status": "可借",
                "location": "四楼语言借阅区",
            },
        ]

    @property
    def agent_card(self) -> AgentCard:
        return AgentCard(
            agent_id="library",
            name="图书馆助手",
            description="提供图书检索、馆藏查询、索书号查询等服务",
            capabilities=["图书检索", "馆藏查询", "索书号查询"],
            endpoint="local://library",
            protocol_version="1.0",
            metadata={"type": "search"},
        )

    def handle_message(self, payload: dict) -> dict:
        """处理图书馆相关问答"""
        query = payload.get("query", "")
        agent_id = self.agent_card.agent_id

        # 输入类型校验：query 必须为字符串
        if not isinstance(query, str):
            return {
                "ok": False,
                "answer": "query 参数必须为字符串",
                "agent_id": agent_id,
            }

        try:
            results = self._search_books(query)
            filtered_results = self._filter_output(results)

            return {
                "ok": True,
                "answer": filtered_results,
                "agent_id": agent_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "answer": f"检索时发生错误: {str(e)}",
                "agent_id": agent_id,
            }

    def _search_books(self, query: str) -> list[dict]:
        """按书名或作者模糊检索"""
        query_lower = query.lower()
        results = []

        for book in self.books:
            # 书名或作者包含查询关键词
            if (query_lower in book["title"].lower() or
                query_lower in book["author"].lower()):
                results.append(book)

        if not results:
            return [{"message": f"未找到与 '{query}' 相关的图书"}]

        return results
