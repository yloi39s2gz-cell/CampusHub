# 智枢 CampusHub

基于 AIP 国标的校园多智能体协同服务中枢。

第八届全球校园人工智能算法精英大赛 · 算法主题赛 · **智能体互联赛道** 参赛作品。

## 项目简介

CampusHub 是一个多智能体协同服务中枢，基于 AIP（Agent Interconnection Protocol）国标实现校园场景下多个智能体的注册、发现、互联与协同调度。内置 4 个校园智能体（课程问答、图书馆检索、自习室预约、秋招资讯），通过异构协议网关兼容 MCP / OpenAPI / 自定义 HTTP 等多种协议，并以 DAG 调度引擎实现任务编排，TrustGuard 提供 HMAC 鉴权、审计与敏感词过滤。

## 目录结构

```
├── src/                    # 核心代码
│   ├── agents/             # 4 个校园智能体
│   ├── aip_adapter/        # AIP 协议适配（含梧桐平台对接）
│   ├── hetero_gateway/     # 异构协议网关（MCP/OpenAPI/HTTP）
│   ├── orchestrator/       # DAG 调度引擎
│   ├── trust_guard/        # HMAC 鉴权、审计、敏感词过滤
│   ├── gateway/            # FastAPI 网关（10 个 RESTful API）
│   ├── deploy/             # Docker 部署
│   └── tests/              # 143 项测试
├── report/                 # 技术报告（PDF/DOCX/Markdown）
└── ppt/                    # 答辩 PPT（PDF/HTML）
```

## 快速开始

```bash
cd src
pip install -r requirements.txt
uvicorn gateway.app:app --host 0.0.0.0 --port 8000
```

Docker 一键部署：

```bash
cd src
./deploy/deploy.sh
```

## 测试

```bash
cd src
python -m pytest tests/ -q
```

143 项测试全绿，端到端冒烟 17/17 通过。

## 文档

- 技术报告：`report/report.pdf`
- 答辩 PPT：`ppt/deck.pdf`
- 构建日志：`src/docs/BUILD_LOG.md`
