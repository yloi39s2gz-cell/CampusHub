# 系统架构文档

## 1. 模块关系图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        客户端 / 外部系统                              │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ HTTP / REST
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    gateway/app.py（FastAPI 统一入口）                  │
│                                                                     │
│  POST /register  │  GET /discover  │  POST /invoke  │  POST /task   │
│  POST /token     │  GET /audit     │  GET /health                   │
└──────┬──────────────┬──────────────────┬──────────────┬─────────────┘
       │              │                  │              │
       ▼              ▼                  ▼              ▼
┌──────────────┐ ┌──────────┐  ┌────────────────┐ ┌──────────────────┐
│ aip_adapter  │ │aip_adapter│  │ trust_guard    │ │  orchestrator    │
│              │ │          │  │                │ │                  │
│ InMemory     │ │ Agent    │  │ TokenAuth      │ │  DagScheduler    │
│ Registry     │ │ Discovery│  │ SensitiveFilter│ │  TaskDAG         │
│ MockTransport│ │          │  │ AuditLogger    │ │  CircuitBreaker  │
│              │ │          │  │                │ │  ExecutionTrace  │
└──────┬───────┘ └──────────┘  └────────────────┘ └────────┬─────────┘
       │                                                    │
       ▼                                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        agents/（演示智能体）                           │
│                                                                      │
│  CourseQAAgent    LibraryAgent    StudyRoomAgent    CareerAgent      │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                   hetero_gateway/（异构协议适配器）                     │
│                                                                      │
│  ┌─────────────┐  ┌───────────────┐  ┌─────────────────┐            │
│  │ MCPAdapter   │  │ OpenAPIAdapter│  │ CustomHTTPAdapter│           │
│  │              │  │               │  │                  │            │
│  │ tool → AIP   │  │ REST → AIP    │  │ HTTP func → AIP  │           │
│  └─────────────┘  └───────────────┘  └─────────────────┘            │
│           │                │                   │                      │
│           └────────────────┼───────────────────┘                      │
│                            ▼                                          │
│                   HeteroAdapter（抽象基类）                             │
│                   to_agent_card / translate_invoke / normalize_result  │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. 请求数据流

### 2.1 点对点调用流程

```
客户端 ──POST /invoke──▶ gateway
                          │
                          ├─① verify_token：HMAC-SHA256 校验 Bearer Token
                          │
                          ├─② SensitiveFilter.check：敏感词过滤输入
                          │
                          ├─③ MockTransport.send_message：
                          │     ├─ InMemoryRegistry.get(to_id) → AgentCard
                          │     ├─ card.metadata["instance"] → 智能体实例
                          │     └─ agent.handle_message(payload) → 响应
                          │
                          ├─④ AuditLogger.log：记录调用审计
                          │
                          └──▶ 返回 {ok, data, agent_id}
```

### 2.2 DAG 协同任务流程

```
客户端 ──POST /task──▶ gateway
                        │
                        ├─① 解析 nodes → TaskNode 列表
                        ├─② 构建 TaskDAG → topological_sort（Kahn 算法）
                        ├─③ detect_cycle：环检测
                        │
                        ├─④ DagScheduler.execute：
                        │     ├─ 按拓扑分层
                        │     ├─ 同层节点并行执行
                        │     ├─ _resolve_input：替换 {node_id.key} 占位符
                        │     ├─ CircuitBreaker.can_execute：熔断检查
                        │     ├─ async_retry：指数退避重试
                        │     ├─ asyncio.wait_for：超时控制
                        │     └─ ExecutionTrace：记录 start/success/fail
                        │
                        ├─⑤ AuditLogger.log：记录任务审计
                        │
                        └──▶ 返回 {status, results, trace}
```

### 2.3 异构协议翻译流程

```
AIP 标准请求 ──▶ HeteroAdapter.translate_invoke ──▶ 原生协议请求
                                                      │
                                                      ▼
                                                 外部服务执行
                                                      │
                                                      ▼
原生协议结果 ──▶ HeteroAdapter.normalize_result ──▶ AIP 标准响应
```

## 3. AIP 适配思路

AIP（Agent Interoperability Protocol）旨在解决异构智能体之间的互操作问题。本系统的适配思路分为三层：

### 3.1 名片层（AgentCard）

每个智能体对外暴露统一的名片格式，包含：
- `agent_id`：唯一标识
- `capabilities`：能力关键词列表（用于发现）
- `endpoint`：服务端点
- `protocol_version`：协议版本

异构服务通过适配器的 `to_agent_card()` 方法将自身描述翻译为 AIP 名片。

### 3.2 传输层（SessionTransport）

抽象消息发送接口，`MockTransport` 提供本地实现。真实场景可替换为 HTTP/gRPC 传输。传输层通过注册表查找目标智能体，屏蔽底层通信差异。

### 3.3 发现层（AgentDiscovery）

基于能力关键词的模糊检索，支持评分排序。完全匹配 capability 得 10 分，部分匹配得 5 分，描述匹配得 2 分，名称匹配得 1 分。

## 4. 三个创新点说明

### 4.1 创新点一：异构协议翻译网关

**问题**：校园场景中存在多种协议的服务（MCP 工具服务器、OpenAPI REST 接口、自定义 HTTP 服务），智能体之间难以直接互通。

**方案**：设计 `HeteroAdapter` 抽象基类，定义三步翻译流程：
1. `to_agent_card()`：将原生服务描述翻译为 AIP 名片
2. `translate_invoke()`：将 AIP 调用请求翻译为原生协议请求
3. `normalize_result()`：将原生协议结果归一化为 AIP 响应

**实现**：
- **MCP 适配器**：将 MCP tool 调用翻译为 AIP 能力，支持 input_schema 参数校验与类型粗校验
- **OpenAPI 适配器**：解析 OpenAPI spec，构建 operation 索引，处理路径参数/查询参数/请求体组装
- **HTTP 适配器**：将函数调用翻译为 HTTP POST 请求，构造 httpx.Request 对象

**价值**：一次接入，统一调用。新增协议只需实现 HeteroAdapter 接口，无需修改核心调度逻辑。

### 4.2 创新点二：DAG 协同调度

**问题**：复杂任务需要多个智能体协同完成，且存在依赖关系（如先检索图书再预约自习室）。

**方案**：
1. **TaskDAG**：定义任务节点（TaskNode）和有向无环图，支持 `depends_on` 依赖声明
2. **拓扑排序**：Kahn 算法分层，同层节点可并行执行
3. **占位符引用**：`{node_id.key}` 语法引用上游节点输出，实现数据传递
4. **容错机制**：指数退避重试（`async_retry`）+ 熔断器（`CircuitBreaker`）+ 超时控制
5. **执行追踪**：`ExecutionTrace` 记录每个节点的 start/success/fail/retry/skipped 事件

**价值**：声明式 DAG 描述，自动并行调度，完整执行追踪，满足复杂协同场景需求。

### 4.3 创新点三：安全管控闭环

**问题**：智能体系统面临未授权访问、敏感信息泄露、操作不可追溯等安全风险。

**方案**：三位一体的安全管控：
1. **TokenAuth**：基于 HMAC-SHA256 的 Token 认证，签发时嵌入 subject/iat/exp，校验时验证签名完整性和过期时间
2. **SensitiveFilter**：分类敏感词表（政治/暴力/色情/联系方式索取/诈骗），输入输出双向过滤
3. **AuditLogger**：线程安全的追加式审计日志，记录 caller/action/target/ok/detail，支持按调用者查询

**数据流闭环**：
```
请求进入 → TokenAuth 鉴权 → SensitiveFilter 输入过滤 → 业务处理
    → SensitiveFilter 输出过滤 → AuditLogger 记录 → 响应返回
```

**价值**：鉴权防伪造、过滤防泄露、审计可追溯，形成完整安全闭环。
