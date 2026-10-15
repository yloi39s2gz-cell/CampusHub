"""全链路测试 - 注册/发现/调用/DAG/异常/异构网关"""

import pytest
from fastapi.testclient import TestClient

from aip_adapter import InMemoryRegistry, MockTransport, AgentDiscovery, AgentCard
from hetero_gateway import MCPAdapter, OpenAPIAdapter, CustomHTTPAdapter
from orchestrator import TaskDAG, TaskNode, DagScheduler
from trust_guard import TokenAuth


# ═══════════════════════════════════════════════════
# 1. 注册→发现→调用 全链路
# ═══════════════════════════════════════════════════

class TestRegisterDiscoverInvoke:
    """注册、发现、点对点调用全链路测试"""

    def test_health_check(self, client: TestClient):
        """健康检查接口"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent_count"] == 4

    def test_discover_all_agents(self, client: TestClient):
        """发现所有预注册智能体"""
        resp = client.get("/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 4
        agent_ids = {a["agent_id"] for a in data["agents"]}
        assert agent_ids == {"course-qa", "library", "study-room", "career"}

    def test_discover_by_capability(self, client: TestClient):
        """按能力关键词发现智能体"""
        resp = client.get("/discover?capability=图书")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        agent_ids = {a["agent_id"] for a in data["agents"]}
        assert "library" in agent_ids

    def test_discover_by_capability_course(self, client: TestClient):
        """按课程相关能力发现"""
        resp = client.get("/discover?capability=课程")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        agent_ids = {a["agent_id"] for a in data["agents"]}
        assert "course-qa" in agent_ids

    def test_register_new_agent(self, client: TestClient, auth_headers: dict):
        """注册新智能体"""
        new_agent = {
            "agent_id": "test-agent",
            "name": "测试智能体",
            "description": "用于测试的智能体",
            "capabilities": ["测试能力"],
            "endpoint": "local://test",
        }
        resp = client.post("/register", json=new_agent, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 验证可以发现新注册智能体
        resp2 = client.get("/discover?capability=测试")
        assert resp2.status_code == 200
        agent_ids = {a["agent_id"] for a in resp2.json()["agents"]}
        assert "test-agent" in agent_ids

    def test_invoke_course_qa(self, client: TestClient, auth_headers: dict):
        """调用课程问答智能体"""
        resp = client.post(
            "/invoke",
            json={
                "from_id": "test-user",
                "to_id": "course-qa",
                "payload": {"query": "高等数学"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_invoke_library(self, client: TestClient, auth_headers: dict):
        """调用图书馆智能体"""
        resp = client.post(
            "/invoke",
            json={
                "from_id": "test-user",
                "to_id": "library",
                "payload": {"query": "Python"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_full_chain(self, client: TestClient, auth_headers: dict):
        """注册→发现→调用 完整链路"""
        # 1. 注册新智能体
        resp = client.post(
            "/register",
            json={
                "agent_id": "chain-test",
                "name": "链路测试",
                "capabilities": ["链路测试能力"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 2. 发现
        resp = client.get("/discover?capability=链路")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

        # 3. 审计日志应有记录
        resp = client.get("/audit", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1


# ═══════════════════════════════════════════════════
# 2. DAG 协同任务
# ═══════════════════════════════════════════════════

class TestDagTask:
    """DAG 协同任务测试"""

    def test_dag_library_then_study_room(self, client: TestClient, auth_headers: dict):
        """图书馆检索→自习室预约 两节点依赖链"""
        task_body = {
            "nodes": [
                {
                    "node_id": "lib",
                    "agent_id": "library",
                    "input_template": {"query": "Python", "context": {}},
                    "depends_on": [],
                },
                {
                    "node_id": "room",
                    "agent_id": "study-room",
                    "input_template": {
                        "query": "来自{lib.agent_id}的查询",
                        "context": {"room_id": "A101"},
                    },
                    "depends_on": ["lib"],
                },
            ]
        }

        resp = client.post("/task", json=task_body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # 断言状态成功
        assert data["status"] == "success"

        # 断言结果完整
        assert "lib" in data["results"]
        assert "room" in data["results"]

        # 断言 trace 完整
        trace_events = data["trace"]["events"]
        assert len(trace_events) >= 4  # 每节点至少 start + success
        node_ids_in_trace = {e["node_id"] for e in trace_events}
        assert "lib" in node_ids_in_trace
        assert "room" in node_ids_in_trace

    def test_dag_parallel_nodes(self, client: TestClient, auth_headers: dict):
        """并行节点 DAG"""
        task_body = {
            "nodes": [
                {
                    "node_id": "n1",
                    "agent_id": "library",
                    "input_template": {"query": "Python"},
                    "depends_on": [],
                },
                {
                    "node_id": "n2",
                    "agent_id": "course-qa",
                    "input_template": {"query": "选课"},
                    "depends_on": [],
                },
            ]
        }

        resp = client.post("/task", json=task_body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "n1" in data["results"]
        assert "n2" in data["results"]


# ═══════════════════════════════════════════════════
# 3. 异常分支
# ═══════════════════════════════════════════════════

class TestErrorCases:
    """异常分支测试"""

    def test_duplicate_register_409(self, client: TestClient, auth_headers: dict):
        """重复注册返回 409"""
        agent_data = {
            "agent_id": "course-qa",
            "name": "重复的课程问答",
            "capabilities": ["课程查询"],
        }
        resp = client.post("/register", json=agent_data, headers=auth_headers)
        assert resp.status_code == 409

    def test_invoke_unknown_agent(self, client: TestClient, auth_headers: dict):
        """调用未知智能体返回规范错误"""
        resp = client.post(
            "/invoke",
            json={
                "from_id": "user",
                "to_id": "nonexistent-agent",
                "payload": {"query": "test"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "不存在" in data["error"] or "error" in data

    def test_dag_cycle_detection(self, client: TestClient, auth_headers: dict):
        """DAG 环检测抛异常"""
        task_body = {
            "nodes": [
                {
                    "node_id": "a",
                    "agent_id": "library",
                    "input_template": {"query": "test"},
                    "depends_on": ["b"],
                },
                {
                    "node_id": "b",
                    "agent_id": "course-qa",
                    "input_template": {"query": "test"},
                    "depends_on": ["a"],
                },
            ]
        }

        resp = client.post("/task", json=task_body, headers=auth_headers)
        assert resp.status_code == 400
        assert "环" in resp.json()["detail"]

    def test_tampered_token_auth_failure(self, client: TestClient):
        """Token 篡改鉴权失败"""
        # 先获取合法 token
        resp = client.post("/token", json={"subject": "test"})
        valid_token = resp.json()["token"]

        # 篡改 token（修改中间几个字符）
        tampered = valid_token[:5] + "XXXX" + valid_token[9:]

        resp = client.post(
            "/invoke",
            json={
                "from_id": "user",
                "to_id": "library",
                "payload": {"query": "test"},
            },
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    def test_missing_auth(self, client: TestClient):
        """缺少认证信息"""
        resp = client.post(
            "/invoke",
            json={
                "from_id": "user",
                "to_id": "library",
                "payload": {"query": "test"},
            },
        )
        assert resp.status_code == 401

    def test_register_without_auth(self, client: TestClient):
        """无鉴权注册被拒"""
        resp = client.post(
            "/register",
            json={"agent_id": "no-auth", "name": "无鉴权"},
        )
        assert resp.status_code == 401

    def test_sensitive_input_rejected(self, client: TestClient, auth_headers: dict):
        """敏感词输入被拒绝"""
        resp = client.post(
            "/invoke",
            json={
                "from_id": "user",
                "to_id": "course-qa",
                "payload": {"query": "这个内容涉及反动信息"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════
# 4. 异构网关适配器全链路
# ═══════════════════════════════════════════════════

class TestHeteroGateway:
    """异构协议适配网关测试"""

    def test_mcp_adapter_full_chain(self):
        """MCP 适配器: to_agent_card → translate_invoke → normalize_result"""
        tools = [
            {
                "name": "search_books",
                "description": "搜索图书",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["keyword"],
                },
            },
            {
                "name": "get_book_detail",
                "description": "获取图书详情",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "book_id": {"type": "string"},
                    },
                    "required": ["book_id"],
                },
            },
        ]

        adapter = MCPAdapter("library-server", tools)

        # 1. to_agent_card
        card = adapter.to_agent_card()
        assert card.agent_id == "mcp-library-server"
        assert "search_books" in card.capabilities
        assert "get_book_detail" in card.capabilities
        assert card.metadata["type"] == "mcp"

        # 2. translate_invoke
        native_req = adapter.translate_invoke({
            "capability": "search_books",
            "params": {"keyword": "Python", "limit": 10},
        })
        assert native_req["tool"] == "search_books"
        assert native_req["arguments"]["keyword"] == "Python"

        # 3. normalize_result
        result = adapter.normalize_result({"books": [{"title": "Python入门"}]})
        assert result["ok"] is True
        assert result["protocol"] == "mcp"
        assert "books" in result["data"]

    def test_mcp_adapter_missing_required_param(self):
        """MCP 适配器缺少必填参数"""
        tools = [
            {
                "name": "search",
                "description": "搜索",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            },
        ]
        adapter = MCPAdapter("test", tools)

        with pytest.raises(ValueError, match="缺少必填参数"):
            adapter.translate_invoke({
                "capability": "search",
                "params": {},
            })

    def test_openapi_adapter_full_chain(self):
        """OpenAPI 适配器: to_agent_card → translate_invoke → normalize_result"""
        spec = {
            "info": {
                "title": "图书 API",
                "description": "图书管理接口",
                "version": "1.0",
            },
            "paths": {
                "/books/search": {
                    "get": {
                        "operationId": "searchBooks",
                        "parameters": [
                            {
                                "name": "q",
                                "in": "query",
                                "required": True,
                            },
                        ],
                    },
                },
                "/books/{book_id}": {
                    "get": {
                        "operationId": "getBook",
                        "parameters": [
                            {
                                "name": "book_id",
                                "in": "path",
                                "required": True,
                            },
                        ],
                    },
                },
            },
        }

        adapter = OpenAPIAdapter(spec)

        # 1. to_agent_card
        card = adapter.to_agent_card()
        assert "openapi" in card.agent_id
        assert len(card.capabilities) == 2

        # 2. translate_invoke - 查询参数
        native_req = adapter.translate_invoke({
            "capability": "get /books/search",
            "params": {"q": "Python"},
        })
        assert native_req["method"] == "GET"
        assert native_req["query_params"]["q"] == "Python"

        # 3. translate_invoke - 路径参数
        native_req = adapter.translate_invoke({
            "capability": "get /books/{book_id}",
            "params": {"book_id": "123"},
        })
        assert native_req["path"] == "/books/123"

        # 4. normalize_result
        result = adapter.normalize_result({"books": []})
        assert result["ok"] is True
        assert result["protocol"] == "openapi"

    def test_http_adapter_full_chain(self):
        """HTTP 适配器: to_agent_card → translate_invoke → normalize_result"""
        functions = [
            {
                "name": "query_score",
                "description": "查询成绩",
                "params": [
                    {"name": "student_id", "type": "string", "required": True},
                    {"name": "course", "type": "string", "required": False},
                ],
            },
        ]

        adapter = CustomHTTPAdapter("https://api.example.com", functions)

        # 1. to_agent_card
        card = adapter.to_agent_card()
        assert "query_score" in card.capabilities
        assert card.metadata["type"] == "http"

        # 2. translate_invoke
        native_req = adapter.translate_invoke({
            "capability": "query_score",
            "params": {"student_id": "S001", "course": "数学"},
        })
        assert native_req["method"] == "POST"
        assert "query_score" in native_req["url"]
        assert native_req["body"]["student_id"] == "S001"

        # 3. normalize_result
        result = adapter.normalize_result({"score": 95})
        assert result["ok"] is True
        assert result["protocol"] == "http"

    def test_http_adapter_missing_required_param(self):
        """HTTP 适配器缺少必填参数"""
        functions = [
            {
                "name": "query",
                "description": "查询",
                "params": [
                    {"name": "id", "type": "string", "required": True},
                ],
            },
        ]
        adapter = CustomHTTPAdapter("https://api.example.com", functions)

        with pytest.raises(ValueError, match="缺少必填参数"):
            adapter.translate_invoke({
                "capability": "query",
                "params": {},
            })


# ═══════════════════════════════════════════════════
# 5. 补充：底层组件单元测试
# ═══════════════════════════════════════════════════

class TestCoreComponents:
    """核心组件单元测试"""

    def test_registry_register_and_get(self):
        """注册表注册与查询"""
        registry = InMemoryRegistry()
        card = AgentCard(
            agent_id="test",
            name="测试",
            capabilities=["测试能力"],
        )
        registry.register(card)
        got = registry.get("test")
        assert got is not None
        assert got.agent_id == "test"

    def test_registry_duplicate_raises(self):
        """注册表重复注册抛异常"""
        registry = InMemoryRegistry()
        card = AgentCard(agent_id="dup", name="重复")
        registry.register(card)
        with pytest.raises(ValueError, match="已注册"):
            registry.register(card)

    def test_discovery_find_by_capability(self):
        """发现服务按能力检索"""
        registry = InMemoryRegistry()
        registry.register(AgentCard(
            agent_id="a1",
            name="助手1",
            capabilities=["图书检索", "借阅"],
        ))
        registry.register(AgentCard(
            agent_id="a2",
            name="助手2",
            capabilities=["课程查询"],
        ))

        discovery = AgentDiscovery(registry)
        results = discovery.find_by_capability("图书")
        assert len(results) == 1
        assert results[0].agent_id == "a1"

    def test_token_auth_issue_and_verify(self):
        """Token 签发与校验"""
        auth = TokenAuth(secret="test-secret")
        token = auth.issue("user-1")
        subject = auth.verify(token)
        assert subject == "user-1"

    def test_token_auth_tampered_returns_none(self):
        """篡改 Token 校验失败"""
        auth = TokenAuth(secret="test-secret")
        token = auth.issue("user-1")
        tampered = token[:3] + "X" + token[4:]
        assert auth.verify(tampered) is None

    def test_token_auth_wrong_secret(self):
        """错误密钥校验失败"""
        auth1 = TokenAuth(secret="secret-1")
        auth2 = TokenAuth(secret="secret-2")
        token = auth1.issue("user-1")
        assert auth2.verify(token) is None

    async def test_mock_transport_send_message(self):
        """MockTransport 消息发送"""

        class FakeAgent:
            def handle_message(self, payload):
                return {"ok": True, "answer": "hello", "agent_id": "fake"}

        registry = InMemoryRegistry()
        card = AgentCard(
            agent_id="fake",
            name="Fake",
            metadata={"instance": FakeAgent()},
        )
        registry.register(card)

        transport = MockTransport(registry)
        result = await transport.send_message("from", "fake", {"query": "hi"})
        assert result["ok"] is True

    async def test_mock_transport_unknown_agent(self):
        """MockTransport 调用未知智能体"""
        registry = InMemoryRegistry()
        transport = MockTransport(registry)
        result = await transport.send_message("from", "unknown", {})
        assert result["ok"] is False

    def test_dag_cycle_detection(self):
        """DAG 环检测"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=["b"]))
        dag.add_node(TaskNode(node_id="b", depends_on=["a"]))
        assert dag.detect_cycle() is True

    def test_dag_topological_sort(self):
        """DAG 拓扑排序"""
        dag = TaskDAG()
        dag.add_node(TaskNode(node_id="a", depends_on=[]))
        dag.add_node(TaskNode(node_id="b", depends_on=["a"]))
        dag.add_node(TaskNode(node_id="c", depends_on=["a"]))
        layers = dag.topological_sort()
        assert layers[0] == ["a"]
        assert set(layers[1]) == {"b", "c"}
