"""测试夹具 - 复用 gateway.app 组件"""

import pytest
from fastapi.testclient import TestClient

from gateway.app import app, create_components, AppComponents


@pytest.fixture(autouse=True)
def clear_app_state():
    """清除应用状态，确保测试隔离"""
    # 测试前清除
    if hasattr(app.state, "components"):
        delattr(app.state, "components")
    yield
    # 测试后清除
    if hasattr(app.state, "components"):
        delattr(app.state, "components")


@pytest.fixture
def components() -> AppComponents:
    """创建全新的组件实例（每次测试独立）"""
    return create_components()


@pytest.fixture
def client(clear_app_state):
    """FastAPI 测试客户端（使用上下文管理器确保 lifespan 触发）
    
    依赖 clear_app_state 确保在清除状态后再创建新的组件
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client) -> dict:
    """获取鉴权请求头（直接依赖 client，避免中间 fixture 缓存问题）"""
    resp = client.post("/token", json={"subject": "test-user"})
    assert resp.status_code == 200, f"获取 token 失败: {resp.text}"
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
