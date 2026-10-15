"""自习室预约智能体"""

from .base import BaseAgent
from aip_adapter.models import AgentCard


class StudyRoomAgent(BaseAgent):
    """自习室预约智能体，支持查询空位与预约/取消"""

    def __init__(self):
        super().__init__()

        # 自习室座位表：{room_id: {seat_id: status}}
        # status: "available" | "occupied"
        self.rooms = {
            "A101": {f"seat-{i:02d}": "available" for i in range(1, 21)},
            "A102": {f"seat-{i:02d}": "available" for i in range(1, 31)},
            "B201": {f"seat-{i:02d}": "available" for i in range(1, 26)},
        }

        # 预约记录：{ticket_id: {room, seat, user}}
        self.reservations: dict[str, dict] = {}
        self._ticket_counter = 0

    @property
    def agent_card(self) -> AgentCard:
        return AgentCard(
            agent_id="study-room",
            name="自习室预约助手",
            description="提供自习室空位查询、座位预约、预约取消等服务",
            capabilities=["空位查询", "座位预约", "预约取消"],
            endpoint="local://study-room",
            protocol_version="1.0",
            metadata={"type": "reservation"},
        )

    def handle_message(self, payload: dict) -> dict:
        """处理自习室相关问答"""
        query = payload.get("query", "")
        context = payload.get("context", {})
        agent_id = self.agent_card.agent_id

        # 输入类型校验：query 必须为字符串
        if not isinstance(query, str):
            return {
                "ok": False,
                "answer": "query 参数必须为字符串",
                "agent_id": agent_id,
            }

        try:
            answer = self._process_request(query, context)
            filtered_answer = self._filter_output(answer)

            return {
                "ok": True,
                "answer": filtered_answer,
                "agent_id": agent_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "answer": f"处理请求时发生错误: {str(e)}",
                "agent_id": agent_id,
            }

    def _process_request(self, query: str, context: dict) -> str | dict:
        """处理请求"""
        # 查询空位
        if "查询" in query or "空位" in query:
            room_id = context.get("room_id")
            return self._query_availability(room_id)

        # 预约座位
        if "预约" in query:
            room_id = context.get("room_id")
            seat_id = context.get("seat_id")
            user_id = context.get("user_id", "anonymous")
            return self._reserve_seat(room_id, seat_id, user_id)

        # 取消预约
        if "取消" in query:
            ticket_id = context.get("ticket_id")
            return self._cancel_reservation(ticket_id)

        return "请明确您的操作：查询空位、预约座位或取消预约。"

    def _query_availability(self, room_id: str | None) -> dict:
        """查询空位"""
        if room_id:
            if room_id not in self.rooms:
                return {"error": f"自习室 {room_id} 不存在"}

            available = [
                seat_id
                for seat_id, status in self.rooms[room_id].items()
                if status == "available"
            ]
            return {
                "room_id": room_id,
                "available_seats": available,
                "count": len(available),
            }
        else:
            # 查询所有自习室
            summary = {}
            for rid, seats in self.rooms.items():
                available = sum(1 for s in seats.values() if s == "available")
                total = len(seats)
                summary[rid] = {"available": available, "total": total}
            return {"rooms": summary}

    def _reserve_seat(self, room_id: str, seat_id: str, user_id: str) -> dict:
        """预约座位"""
        if not room_id or not seat_id:
            return {"error": "请提供自习室 ID 和座位 ID"}

        if room_id not in self.rooms:
            return {"error": f"自习室 {room_id} 不存在"}

        if seat_id not in self.rooms[room_id]:
            return {"error": f"座位 {seat_id} 不存在"}

        if self.rooms[room_id][seat_id] != "available":
            return {"error": f"座位 {seat_id} 已被占用"}

        # 预约成功
        self.rooms[room_id][seat_id] = "occupied"
        self._ticket_counter += 1
        ticket_id = f"T{self._ticket_counter:06d}"

        self.reservations[ticket_id] = {
            "room_id": room_id,
            "seat_id": seat_id,
            "user_id": user_id,
        }

        return {
            "message": "预约成功",
            "ticket_id": ticket_id,
            "room_id": room_id,
            "seat_id": seat_id,
        }

    def _cancel_reservation(self, ticket_id: str) -> dict:
        """取消预约"""
        if not ticket_id:
            return {"error": "请提供预约券 ID"}

        if ticket_id not in self.reservations:
            return {"error": f"预约券 {ticket_id} 不存在"}

        reservation = self.reservations[ticket_id]
        room_id = reservation["room_id"]
        seat_id = reservation["seat_id"]

        # 释放座位
        self.rooms[room_id][seat_id] = "available"
        del self.reservations[ticket_id]

        return {
            "message": "预约已取消",
            "ticket_id": ticket_id,
        }
