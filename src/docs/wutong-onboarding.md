# 梧桐平台接入操作指南

本文档为智枢 CampusHub 对接梧桐平台（ACPs）的完整操作清单。
所有步骤均基于官方 acps-sdk / acps-cli 工具链。

---

## 前置条件

| 序号 | 事项 | 说明 | 需用户出面 |
|------|------|------|:-----------:|
| 0 | 加入官方 QQ 群 | 群号 **1102086449**，获取最新接入文档与 AIC 分配 | **是** |

---

## 操作步骤

### 1. 安装依赖

```bash
pip install acps-sdk acps-cli
```

> 本项目 requirements.txt 已包含 `acps-sdk>=2.1.0` 和 `httpx`。
> `acps-cli` 为命令行工具，需单独安装。

### 2. 配置 acps-cli.toml

在项目根目录创建 `acps-cli.toml`，参考模板：

```toml
[registry]
# ⚠️ 以下地址待 QQ 群文档确认，当前为本地开发占位值
base_url = "http://localhost:9001"
mtls_base_url = "http://localhost:9002"

[auth]
user_token_file = "./.acps-cli/tokens/registry-user.json"
admin_token_file = "./.acps-cli/tokens/registry-admin.json"

[ca]
# ⚠️ 待群文档确认
base_url = "http://localhost:9003"

[discovery]
# ⚠️ 待群文档确认
base_url = "http://localhost:9005"
```

> **等待点**：所有 endpoint 地址需从 QQ 群文档获取真实值后替换。

### 3. ATR 注册流程

| 步骤 | 命令 | 说明 | 等待点 | 需用户出面 |
|------|------|------|:------:|:-----------:|
| 3.1 | `acps-cli auth login` | 登录注册服务 | 否 | **是**（输入凭据） |
| 3.2 | `acps-cli agent save --file <acs.json>` | 提交 ACS 草稿 | 否 | 否 |
| 3.3 | `acps-cli agent submit --aic <AIC>` | 提交审核 | **等待管理员审批** | **是**（跟进审批进度） |
| 3.4 | `acps-cli agent status --aic <AIC>` | 查询审核状态 | 反复查询直到通过 | 否 |
| 3.5 | `acps-cli cert eab fetch --aic <AIC>` | 获取 EAB 凭据 | 否 | 否 |
| 3.6 | `acps-cli cert request --aic <AIC>` | 向 CA 申请 mTLS 证书 | **等待 CA 签发** | **是**（确认证书下载） |

> **关键等待点**：
> - 步骤 3.3 管理员审批：外部依赖，可能需要数小时到数天，**建议尽早提交**
> - 步骤 3.6 CA 签发证书：取决于 CA 服务响应速度

### 4. ACS 文件生成

可使用项目内置函数生成 ACS 文件：

```python
from aip_adapter import AgentCard, build_acs
import json

card = AgentCard(
    agent_id="your-agent-id",
    name="你的智能体名称",
    description="智能体功能描述",
    capabilities=["能力1", "能力2"],
    endpoint="https://your-server.com/rpc",
)

acs = build_acs(card)
with open("partners/online/your-agent-id/acs.json", "w") as f:
    json.dump(acs, f, ensure_ascii=False, indent=2)
```

也可查看命令行指引：

```python
from aip_adapter import AgentCard, atr_guide

card = AgentCard(agent_id="demo", name="演示", capabilities=["查询"])
for line in atr_guide(card):
    print(line)
```

### 5. 配置环境变量

```bash
export WUTONG_REGISTRY_URL="http://待确认:9001"
export WUTONG_DISCOVERY_URL="http://待确认:9005"
export WUTONG_CA_URL="http://待确认:9003"
export WUTONG_LEADER_AIC="待分配"
```

> 所有地址均待 QQ 群文档确认后填入真实值。

### 6. 运行验证

```bash
# 运行全量测试
python3 -m pytest tests/ -q

# 验证梧桐模块导入
python3 -c "from aip_adapter import WutongConfig, build_acs, discover_agents; print('OK')"
```

---

## 等待点汇总

| 等待项 | 所在步骤 | 预估时间 | 应对策略 |
|--------|---------|---------|---------|
| QQ 群文档确认 endpoint | 步骤 2、5 | 加入群后即可获取 | 尽早加群 |
| 管理员审批 ATR 注册 | 步骤 3.3 | 数小时~数天 | 尽早提交，定期检查状态 |
| CA 签发证书 | 步骤 3.6 | 分钟级 | 确保 CA 服务在线 |
| Leader AIC 分配 | 步骤 5 | 与审批同步 | 审批通过后即获得 |

---

## 需用户出面事项汇总

| 事项 | 说明 |
|------|------|
| 加入 QQ 群 1102086449 | 获取官方接入文档和真实 endpoint |
| 登录 acps-cli | 输入用户名密码（`auth login` 交互式输入） |
| 跟进管理员审批 | 提交审核后定期查询状态 |
| 确认 CA 证书下载 | 证书申请完成后确认文件到位 |
| 填入真实环境变量 | 将群文档中的地址替换占位值 |

---

## 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|---------|---------|
| `ModuleNotFoundError: acps_sdk` | 未安装 acps-sdk | `pip install acps-sdk` |
| `WutongError: 发现服务请求失败` | 网络不通或地址错误 | 检查 WUTONG_DISCOVERY_URL 是否正确 |
| `acps-cli: command not found` | 未安装 acps-cli | `pip install acps-cli` |
| 审核长时间未通过 | 管理员未处理 | QQ 群内 @管理员 催审 |
