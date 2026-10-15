"""智枢 CampusHub 统一入口 - FastAPI 应用"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from aip_adapter import (
    AgentCard,
    InMemoryRegistry,
    AgentDiscovery,
    MockTransport,
)
from orchestrator import TaskNode, TaskDAG, DagScheduler
from orchestrator.circuit import CircuitBreaker
from orchestrator.trace import ExecutionTrace
from trust_guard import TokenAuth, AuditLogger, SensitiveFilter
from agents import CourseQAAgent, LibraryAgent, StudyRoomAgent, CareerAgent
from gateway.metrics import MetricsCollector
from gateway.json_logging import setup_json_logging

# 内存容量上限，防止无界增长导致 OOM
_MAX_TRACE_STORE = 1000
_MAX_AUDIT_ENTRIES = 2000
_MAX_MESSAGE_LOG = 2000

logger = logging.getLogger(__name__)

# 业务日志器，用于 /invoke 与 /task 的结构化记录
obs_logger = logging.getLogger("aic")


# ────────────────── 组件容器 ──────────────────

class AppComponents:
    """应用组件容器，便于测试注入"""

    def __init__(self):
        self.registry = InMemoryRegistry()
        self.transport = MockTransport(self.registry)
        self.discovery = AgentDiscovery(self.registry)
        self.auth = TokenAuth()
        self.audit = AuditLogger()
        self.sensitive = SensitiveFilter()
        # 可观测性组件
        self.metrics = MetricsCollector()
        # task_id -> ExecutionTrace 的映射，用于 trace 导出
        self.trace_store: dict[str, ExecutionTrace] = {}
        # 跨请求持久化的熔断器：agent_id -> CircuitBreaker
        # 避免每次 /task 新建 DagScheduler 导致熔断器状态丢失
        self.circuit_breakers: dict[str, CircuitBreaker] = {}


def create_components() -> AppComponents:
    """创建并初始化所有组件，注册演示智能体"""
    comps = AppComponents()

    # 创建演示智能体实例
    agents = [CourseQAAgent(), LibraryAgent(), StudyRoomAgent(), CareerAgent()]

    for agent in agents:
        card = agent.agent_card
        # 将智能体实例存入 metadata，供 MockTransport 调用
        card_with_instance = card.model_copy(
            update={"metadata": {**card.metadata, "instance": agent}}
        )
        comps.registry.register(card_with_instance)

    return comps


# ────────────────── 请求/响应模型 ──────────────────

class RegisterRequest(BaseModel):
    """注册请求体"""
    agent_id: str
    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    endpoint: str = ""
    protocol_version: str = "1.0"
    metadata: dict = Field(default_factory=dict)


class InvokeRequest(BaseModel):
    """点对点调用请求体"""
    from_id: str
    to_id: str
    payload: dict


class TaskRequest(BaseModel):
    """DAG 任务请求体"""
    nodes: list[dict]


class TokenRequest(BaseModel):
    """Token 签发请求体"""
    subject: str = "demo-user"


# ────────────────── FastAPI 应用 ──────────────────

security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """应用生命周期：启动时初始化组件"""
    # 初始化结构化日志（落盘到 logs/app.log）
    setup_json_logging()
    application.state.components = create_components()
    logger.info("智枢 CampusHub 网关启动完成，已注册 %d 个演示智能体",
                len(application.state.components.registry.list_all()))
    yield


app = FastAPI(
    title="智枢 CampusHub",
    description="校园智能体协同平台统一入口",
    version="1.0.0",
    lifespan=lifespan,
)


def get_components(request: Request | None = None) -> AppComponents:
    """获取应用组件"""
    if request is not None and hasattr(request.app.state, "components"):
        return request.app.state.components
    if hasattr(app.state, "components"):
        return app.state.components
    raise RuntimeError("应用未初始化")


def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """校验 Bearer Token，返回 subject"""
    comps = get_components(request)
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    token = credentials.credentials
    subject = comps.auth.verify(token)
    if subject is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return subject


# ────────────────── 接口路由 ──────────────────

# 设计意图：/health 与 /discover 无需鉴权
# - /health 供负载均衡器、容器编排（K8s liveness/readiness probe）探测，必须无鉴权
# - /discover 仅返回智能体名片（公开元数据），不含敏感业务数据，便于客户端自行发现可用服务
@app.get("/health", tags=["系统"])
async def health(request: Request):
    """健康检查（无需鉴权，供 K8s/lb 探测）"""
    comps = get_components(request)
    agent_count = len(comps.registry.list_all())
    return {
        "status": "ok",
        "service": "智枢 CampusHub",
        "agent_count": agent_count,
    }


@app.post("/token", tags=["认证"])
async def issue_token(body: TokenRequest, request: Request):
    """
    签发演示 Token（仅演示用，生产环境请替换为正式认证方案）

    Args:
        body: 包含 subject 的请求体
    """
    comps = get_components(request)
    token = comps.auth.issue(subject=body.subject)
    return {
        "token": token,
        "subject": body.subject,
        "note": "仅演示用，请勿在生产环境使用",
    }


@app.post("/register", tags=["智能体管理"])
async def register_agent(
    body: RegisterRequest,
    request: Request,
    subject: str = Depends(verify_token),
):
    """
    注册智能体（需鉴权）

    重复注册返回 409
    """
    comps = get_components(request)

    card = AgentCard(
        agent_id=body.agent_id,
        name=body.name,
        description=body.description,
        capabilities=body.capabilities,
        endpoint=body.endpoint,
        protocol_version=body.protocol_version,
        metadata=body.metadata,
    )

    try:
        comps.registry.register(card)
    except ValueError as e:
        comps.audit.log(
            caller=subject,
            action="register",
            target=body.agent_id,
            ok=False,
            detail=str(e),
        )
        raise HTTPException(status_code=409, detail=str(e))

    comps.audit.log(
        caller=subject,
        action="register",
        target=body.agent_id,
        ok=True,
    )
    return {"ok": True, "agent_id": body.agent_id, "message": "注册成功"}


@app.get("/discover", tags=["智能体发现"])
async def discover_agents(request: Request, capability: str = ""):
    """
    按能力关键词发现智能体（无需鉴权，仅返回公开名片信息）

    Args:
        capability: 能力关键词，为空则返回全部
    """
    comps = get_components(request)

    if not capability:
        cards = comps.registry.list_all()
    else:
        cards = comps.discovery.find_by_capability(capability)

    # 过滤掉 metadata 中的 instance 字段（不可序列化）
    result = []
    for card in cards:
        card_dict = card.model_dump()
        card_dict.get("metadata", {}).pop("instance", None)
        result.append(card_dict)

    return {"agents": result, "count": len(result)}


@app.post("/invoke", tags=["点对点调用"])
async def invoke_agent(
    body: InvokeRequest,
    request: Request,
    subject: str = Depends(verify_token),
):
    """
    点对点调用智能体（需鉴权）

    流程：鉴权 → 敏感词过滤 → 调用 → 审计记录 → 指标记录
    """
    comps = get_components(request)

    # 敏感词过滤输入
    query = body.payload.get("query", "")
    if query:
        is_safe = comps.sensitive.check(query)
        if not is_safe:
            comps.audit.log(
                caller=subject,
                action="invoke",
                target=body.to_id,
                ok=False,
                detail="输入包含敏感词",
            )
            raise HTTPException(status_code=400, detail="输入包含敏感词，已拒绝")

    # 计时开始
    t0 = time.perf_counter()
    ok = False
    result = {}
    try:
        # 调用目标智能体
        result = await comps.transport.send_message(
            from_id=body.from_id,
            to_id=body.to_id,
            payload=body.payload,
        )
        ok = result.get("ok", False)
    except Exception as exc:
        # transport 层异常也要记录审计，避免审计空白
        ok = False
        result = {"ok": False, "error": str(exc), "agent_id": body.to_id}
        raise
    finally:
        # 计时结束，无论成功失败都记录指标与审计
        duration_ms = (time.perf_counter() - t0) * 1000
        comps.metrics.record_invoke(agent_id=body.to_id, duration_ms=duration_ms, ok=ok)
        # 审计记录：放在 finally 中确保异常路径也有审计
        comps.audit.log(
            caller=subject,
            action="invoke",
            target=body.to_id,
            ok=ok,
            detail=f"from={body.from_id}",
        )
        # 结构化日志
        obs_logger.info(
            "invoke",
            extra={
                "event": "invoke",
                "agent_id": body.to_id,
                "duration_ms": round(duration_ms, 2),
                "ok": ok,
                "caller": subject,
            },
        )

    if not ok:
        return {
            "ok": False,
            "error": result.get("error", "调用失败"),
            "agent_id": result.get("agent_id"),
        }

    return result


@app.post("/task", tags=["DAG 协同"])
async def submit_task(
    body: TaskRequest,
    request: Request,
    subject: str = Depends(verify_token),
):
    """
    提交 DAG 协同任务

    接收节点列表，构建 DAG 并调度执行
    """
    comps = get_components(request)

    # 构建 DAG
    dag = TaskDAG()
    try:
        for node_data in body.nodes:
            try:
                node = TaskNode(**node_data)
            except Exception as ve:
                # 将 pydantic 校验错误转为对调用方友好的中文提示
                raise ValueError(f"节点参数校验失败（{node_data.get('node_id', '?')}）: {ve}")
            dag.add_node(node)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"DAG 构建失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DAG 构建失败: {str(e)}")

    # 检测环
    if dag.detect_cycle():
        comps.audit.log(
            caller=subject,
            action="task",
            target="dag",
            ok=False,
            detail="DAG 存在环",
        )
        raise HTTPException(status_code=400, detail="DAG 中存在环，无法执行")

    # 创建调度器，invoke_fn 走 MockTransport
    async def invoke_fn(agent_id: str, payload: dict) -> dict:
        result = await comps.transport.send_message(
            from_id="dag-scheduler",
            to_id=agent_id,
            payload=payload,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "调用失败"))
        return result.get("data", {})

    scheduler = DagScheduler(invoke_fn=invoke_fn)
    # 复用跨请求持久化的熔断器，确保熔断状态不会因新请求而丢失
    scheduler.circuit_breakers = comps.circuit_breakers

    # 计时开始
    t0 = time.perf_counter()
    # 执行 DAG
    exec_result = await scheduler.execute(dag)
    duration_ms = (time.perf_counter() - t0) * 1000

    status = exec_result["status"]
    ok = status == "success"
    node_count = len(dag.nodes)

    # 记录指标
    comps.metrics.record_task(duration_ms=duration_ms, ok=ok, node_count=node_count)

    # 生成 task_id 并保存 trace（带容量上限，防止无界增长）
    task_id = uuid.uuid4().hex
    if len(comps.trace_store) >= _MAX_TRACE_STORE:
        # 淘汰最早的 entry（按 dict 插入顺序）
        oldest_key = next(iter(comps.trace_store))
        del comps.trace_store[oldest_key]
    comps.trace_store[task_id] = scheduler.trace

    # 结构化日志
    obs_logger.info(
        "task",
        extra={
            "event": "task",
            "task_id": task_id,
            "duration_ms": round(duration_ms, 2),
            "ok": ok,
            "node_count": node_count,
            "status": status,
            "caller": subject,
        },
    )

    # 审计记录
    comps.audit.log(
        caller=subject,
        action="task",
        target="dag",
        ok=ok,
        detail=f"status={status}",
    )

    return {
        "task_id": task_id,
        "status": status,
        "results": exec_result["results"],
        "trace": exec_result["trace"],
    }


@app.get("/metrics", tags=["可观测性"])
async def get_metrics(
    request: Request,
    subject: str = Depends(verify_token),
):
    """查询指标快照（需鉴权）"""
    comps = get_components(request)
    return comps.metrics.snapshot()


@app.get("/trace/{task_id}/mermaid", tags=["可观测性"])
async def get_trace_mermaid(
    task_id: str,
    request: Request,
    subject: str = Depends(verify_token),
):
    """获取任务执行追踪的 Mermaid 图（需鉴权）"""
    comps = get_components(request)
    trace = comps.trace_store.get(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return PlainTextResponse(trace.export_mermaid(), media_type="text/plain")


@app.get("/trace/{task_id}/html", tags=["可观测性"])
async def get_trace_html(
    task_id: str,
    request: Request,
    subject: str = Depends(verify_token),
):
    """获取任务执行追踪的 HTML 报告（需鉴权）"""
    comps = get_components(request)
    trace = comps.trace_store.get(task_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return HTMLResponse(trace.export_html())


@app.get("/audit", tags=["审计"])
async def get_audit_log(
    request: Request,
    subject: str = Depends(verify_token),
):
    """查询审计日志（需鉴权）"""
    comps = get_components(request)
    entries = comps.audit.export()
    return {"entries": entries, "count": len(entries)}
