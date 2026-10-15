# 智枢 CampusHub

校园智能体协同平台 —— 基于 AIP 协议的异构智能体统一接入、DAG 协同调度与安全管控系统。

## 特性

- **异构协议翻译网关**：MCP / OpenAPI / 自定义 HTTP 三种适配器，将不同协议统一为 AIP 标准
- **AIP 协议适配层**：智能体名片、注册表、发现服务、Mock 传输，完整实现 AIP 核心规范
- **DAG 协同调度引擎**：拓扑排序 → 分层并行执行 → 指数退避重试 → 熔断保护 → 执行追踪
- **安全管控闭环**：HMAC-SHA256 Token 鉴权、敏感词过滤、线程安全审计日志
- **4 个校园演示智能体**：课程问答、图书馆检索、自习室预约、秋招资讯
- **FastAPI 统一入口**：RESTful API，含 Swagger 文档、一键部署

## 本地启动（三步走）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
uvicorn gateway.app:app --reload

# 3. 运行测试
python -m pytest tests/ -v
```

## 接口 curl 示例

### 获取 Token（仅演示用）

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/json" \
  -d '{"subject": "demo-user"}'
```

### 发现智能体

```bash
# 按能力关键词发现
curl "http://localhost:8000/discover?capability=图书"

# 列出全部
curl http://localhost:8000/discover
```

### 点对点调用

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "from_id": "user",
    "to_id": "course-qa",
    "payload": {"query": "高等数学"}
  }'
```

### 提交 DAG 协同任务

```bash
curl -X POST http://localhost:8000/task \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [
      {
        "node_id": "lib",
        "agent_id": "library",
        "input_template": {"query": "Python", "context": {}},
        "depends_on": []
      },
      {
        "node_id": "room",
        "agent_id": "study-room",
        "input_template": {"query": "查询", "context": {"room_id": "A101"}},
        "depends_on": ["lib"]
      }
    ]
  }'
```

## LLM 配置

课程问答智能体支持 LLM + 规则混合架构。通过环境变量配置 OpenAI-compatible 的 LLM 后端：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `LLM_BASE_URL` | LLM API 基础地址 | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API 密钥（必填以启用 LLM） | 无（空则降级到规则） |
| `LLM_MODEL` | 模型名称 | `gpt-4o-mini` |
| `LLM_TIMEOUT` | 请求超时时间（秒） | `30` |

**降级行为**：未配置 `LLM_API_KEY` 或 LLM 调用失败时，智能体自动降级到关键词匹配规则逻辑，保证服务可用性。

示例（启用 LLM）：

```bash
export LLM_API_KEY="sk-xxx"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
```

## 可观测性

为技术报告"量化成效分析"章节提供数据支撑：

### /metrics 指标接口

`GET /metrics`（需鉴权）返回 JSON 格式的指标快照：

- `invoke`：`/invoke` 调用总数、成功/失败数、成功率、平均时延、P95 时延
- `task`：`/task` 调用总数、成功/失败数、成功率、平均时延、P95 时延、平均节点数
- `agents`：按智能体 ID 聚合的调用总数与成功数

```bash
curl -H "Authorization: Bearer <TOKEN>" http://localhost:8000/metrics
```

### 结构化日志

- 日志位置：`logs/app.log`（JSON 行格式，每行一条）
- 滚动策略：单文件 5MB，保留 3 个备份（`RotatingFileHandler`）
- 每条日志含 `timestamp / level / event / duration_ms / agent_id / task_id` 等字段
- `/invoke` 与 `/task` 每次调用各记一条（含成功失败）

### Trace 导出

每次 `/task` 调用会返回 `task_id`，可用于导出执行追踪：

```bash
# 导出 Mermaid 流程图（text/plain）
curl -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8000/trace/<task_id>/mermaid

# 导出 HTML 报告（含事件时间线表格与耗时统计）
curl -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8000/trace/<task_id>/html -o trace.html
```

Mermaid 图按节点状态着色：成功绿 / 失败红 / 重试黄 / 跳过灰，边标注耗时。

## 目录结构

```
src/
├── aip_adapter/          # AIP 协议适配层
│   ├── models.py         # AgentCard 数据模型
│   ├── registry.py       # 注册表（抽象 + 内存实现）
│   ├── discovery.py      # 发现服务（按能力关键词检索）
│   ├── session.py        # 会话传输（抽象 + Mock 实现）
│   └── wutong.py         # 梧桐平台适配器占位
├── hetero_gateway/       # 异构协议适配网关
│   ├── base.py           # 适配器抽象基类
│   ├── mcp_adapter.py    # MCP 协议适配器
│   ├── openapi_adapter.py# OpenAPI 适配器
│   ├── http_adapter.py   # 自定义 HTTP 适配器
│   └── llm_backend.py    # LLM 后端（OpenAI-compatible）
├── orchestrator/         # DAG 协同调度引擎
│   ├── dag.py            # DAG 定义与拓扑排序
│   ├── scheduler.py      # 调度器（并行执行 + 重试 + 熔断）
│   ├── retry.py          # 指数退避重试
│   ├── circuit.py        # 熔断器
│   └── trace.py          # 执行追踪
├── trust_guard/          # 安全管控模块
│   ├── auth.py           # HMAC-SHA256 Token 认证
│   ├── audit.py          # 审计日志
│   └── sensitive.py      # 敏感词过滤
├── agents/               # 校园演示智能体
│   ├── base.py           # 智能体基类
│   ├── course_qa.py      # 课程问答
│   ├── library.py        # 图书馆检索
│   ├── study_room.py     # 自习室预约
│   └── career.py         # 秋招资讯
├── gateway/              # 统一入口（FastAPI）
│   ├── app.py            # 应用主文件
│   ├── metrics.py        # 指标收集器
│   └── json_logging.py   # JSON 结构化日志
├── deploy/               # 一键部署
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── deploy.sh
├── tests/                # 全链路测试
│   ├── conftest.py
│   ├── test_fullchain.py
│   ├── test_wutong.py
│   ├── test_llm.py
│   └── test_observability.py
├── docs/                 # 文档
│   └── architecture.md
├── requirements.txt
└── pytest.ini
```
