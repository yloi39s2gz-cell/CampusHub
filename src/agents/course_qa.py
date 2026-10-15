"""课程问答智能体 - LLM + 规则混合架构"""

from .base import BaseAgent
from aip_adapter.models import AgentCard


class CourseQAAgent(BaseAgent):
    """
    课程问答智能体

    采用 LLM + 规则混合架构：
    - 优先走 LLM：将课程表和 FAQ 作为上下文注入 system prompt
    - LLM 不可用时降级到关键词匹配规则逻辑
    """

    def __init__(self):
        super().__init__()

        # 内置课程表（已脱敏，不含教师姓名等个人信息）
        self.courses = {
            "高等数学": {
                "time": "周一 8:00-9:40, 周三 10:00-11:40",
                "location": "教学楼 A201",
                "credits": 4,
            },
            "大学英语": {
                "time": "周二 14:00-15:40, 周四 14:00-15:40",
                "location": "外语楼 B305",
                "credits": 3,
            },
            "数据结构": {
                "time": "周一 14:00-15:40, 周三 14:00-15:40",
                "location": "计算机楼 C102",
                "credits": 4,
            },
        }

        # 常见问题库
        self.faq = {
            "选课": "选课时间为每学期开学前两周，请登录教务系统进行操作。",
            "退课": "退课时间为开课后第一周，逾期不予办理。",
            "补考": "补考安排在下学期开学初，具体时间和地点请关注教务通知。",
            "绩点": "绩点计算公式：绩点 = (成绩 - 50) / 10，60分对应1.0绩点。",
        }

    @property
    def agent_card(self) -> AgentCard:
        return AgentCard(
            agent_id="course-qa",
            name="课程问答助手",
            description="提供课程查询、选课退课政策解答等服务（LLM+规则混合）",
            capabilities=["课程查询", "选课政策", "退课政策", "补考安排", "绩点计算"],
            endpoint="local://course-qa",
            protocol_version="1.0",
            metadata={"type": "qa", "llm_hybrid": True},
        )

    def handle_message(self, payload: dict) -> dict:
        """处理课程相关问答，优先走 LLM，失败降级到规则"""
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
            # 优先尝试 LLM 路径
            answer = self._try_llm(query)

            # LLM 不可用或返回空时降级到规则
            if not answer:
                answer = self._process_query(query)

            filtered_answer = self._filter_output(answer)

            return {
                "ok": True,
                "answer": filtered_answer,
                "agent_id": agent_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "answer": f"处理查询时发生错误: {str(e)}",
                "agent_id": agent_id,
            }

    def _try_llm(self, query: str) -> str | None:
        """
        尝试用 LLM 回答问题

        将课程表和 FAQ 拼入 system prompt 作为上下文，
        让 LLM 理解用户意图并生成答案。

        Returns:
            LLM 生成的答案文本，或 None（表示应降级）
        """
        # 构建 system prompt，包含课程表和 FAQ 上下文
        system = self._build_system_prompt()

        # 调用 LLM
        result = self._llm_complete(query, system=system)

        # 空字符串也视为降级
        if not result or not result.strip():
            return None

        return result.strip()

    def _build_system_prompt(self) -> str:
        """构建包含课程表和 FAQ 的 system prompt"""
        # 格式化课程表
        courses_text = "\n".join(
            f"- {name}: 时间={info['time']}, 地点={info['location']}, 学分={info['credits']}"
            for name, info in self.courses.items()
        )

        # 格式化 FAQ
        faq_text = "\n".join(f"- {k}: {v}" for k, v in self.faq.items())

        return (
            "你是一个课程问答助手，请基于以下课程表和常见问题库回答用户问题。\n\n"
            f"【课程表】\n{courses_text}\n\n"
            f"【常见问题库】\n{faq_text}\n\n"
            "回答要求：\n"
            "1. 优先使用课程表和 FAQ 中的信息\n"
            "2. 如果问题超出范围，诚实告知无法回答\n"
            "3. 回答简洁准确，不要编造信息"
        )

    def _process_query(self, query: str) -> str:
        """规则降级：处理查询，返回答案"""
        # 检查是否为课程查询
        for course_name, course_info in self.courses.items():
            if course_name in query:
                info_str = (
                    f"{course_name}：\n"
                    f"  上课时间：{course_info['time']}\n"
                    f"  上课地点：{course_info['location']}\n"
                    f"  学分：{course_info['credits']}"
                )
                return info_str

        # 检查是否为 FAQ
        for keyword, answer in self.faq.items():
            if keyword in query:
                return answer

        return "抱歉，我暂时无法回答您的问题。请尝试查询具体课程名称或选课、退课、补考、绩点等关键词。"
