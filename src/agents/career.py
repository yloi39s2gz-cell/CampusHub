"""秋招资讯智能体"""

from .base import BaseAgent
from aip_adapter.models import AgentCard


class CareerAgent(BaseAgent):
    """秋招资讯智能体，提供招聘信息检索"""

    def __init__(self):
        super().__init__()

        # 模拟招聘信息
        self.jobs = [
            {
                "company": "华为技术有限公司",
                "position": "软件工程师",
                "location": "深圳",
                "salary": "20k-35k",
                "requirements": "计算机相关专业，熟悉 Python/Java",
                "apply_link": "https://example.com/huawei/apply",
            },
            {
                "company": "腾讯科技",
                "position": "后端开发工程师",
                "location": "深圳",
                "salary": "25k-40k",
                "requirements": "本科及以上学历，熟悉分布式系统",
                "apply_link": "https://example.com/tencent/apply",
            },
            {
                "company": "阿里巴巴集团",
                "position": "数据分析师",
                "location": "杭州",
                "salary": "22k-38k",
                "requirements": "统计学或计算机专业，熟悉 SQL 和 Python",
                "apply_link": "https://example.com/alibaba/apply",
            },
            {
                "company": "字节跳动",
                "position": "算法工程师",
                "location": "北京",
                "salary": "30k-50k",
                "requirements": "硕士及以上学历，机器学习方向",
                "apply_link": "https://example.com/bytedance/apply",
            },
            {
                "company": "美团",
                "position": "产品经理",
                "location": "北京",
                "salary": "18k-30k",
                "requirements": "本科及以上学历，逻辑思维能力强",
                "apply_link": "https://example.com/meituan/apply",
            },
        ]

    @property
    def agent_card(self) -> AgentCard:
        return AgentCard(
            agent_id="career",
            name="秋招资讯助手",
            description="提供秋招招聘信息检索、岗位推荐等服务",
            capabilities=["职位检索", "公司查询", "岗位推荐"],
            endpoint="local://career",
            protocol_version="1.0",
            metadata={"type": "info"},
        )

    def handle_message(self, payload: dict) -> dict:
        """处理秋招相关问答"""
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
            results = self._search_jobs(query)
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

    def _search_jobs(self, query: str) -> list[dict]:
        """按公司或岗位关键词检索"""
        query_lower = query.lower()
        results = []

        for job in self.jobs:
            # 公司名或岗位名包含查询关键词
            if (query_lower in job["company"].lower() or
                query_lower in job["position"].lower() or
                query_lower in job["requirements"].lower()):
                results.append(job)

        if not results:
            return [{"message": f"未找到与 '{query}' 相关的招聘信息"}]

        return results
