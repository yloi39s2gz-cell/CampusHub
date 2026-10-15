"""OpenAPI 适配器"""

import re
from .base import HeteroAdapter
from aip_adapter.models import AgentCard


class OpenAPIAdapter(HeteroAdapter):
    """OpenAPI 规范适配器，将 REST API 翻译为 AIP 能力"""

    def __init__(self, spec: dict):
        """
        初始化 OpenAPI 适配器

        Args:
            spec: OpenAPI 规范 dict，包含 info, paths 等
                  paths 格式: {"/path": {"method": {"operationId": "...", "parameters": [...], "requestBody": {...}}}}
        """
        self.spec = spec
        self.info = spec.get("info", {})
        self.paths = spec.get("paths", {})

        # 构建 operation 索引: operation_id -> {path, method, spec}
        self.operations: dict[str, dict] = {}
        self._build_operation_index()

    def _build_operation_index(self):
        """构建 operation 索引，将每个 operationId/path+method 映射到一条能力"""
        for path, methods in self.paths.items():
            for method, operation_spec in methods.items():
                if method in ("get", "post", "put", "delete", "patch"):
                    operation_id = operation_spec.get("operationId")
                    if not operation_id:
                        # 如果没有 operationId，使用 method + path 生成
                        operation_id = f"{method}_{path.replace('/', '_').strip('_')}"

                    # 能力格式: "get /books/search"
                    capability = f"{method} {path}"

                    self.operations[operation_id] = {
                        "path": path,
                        "method": method,
                        "capability": capability,
                        "spec": operation_spec,
                    }

    def to_agent_card(self) -> AgentCard:
        """将 OpenAPI 操作列表转换为 AgentCard"""
        capabilities = [op["capability"] for op in self.operations.values()]

        return AgentCard(
            agent_id=f"openapi-{self.info.get('title', 'unknown')}",
            name=self.info.get("title", "OpenAPI Service"),
            description=self.info.get("description", "OpenAPI 服务"),
            capabilities=capabilities,
            endpoint=self.info.get("endpoint", "http://localhost"),
            protocol_version="openapi-3.0",
            metadata={
                "type": "openapi",
                "version": self.info.get("version", "1.0"),
            },
        )

    def translate_invoke(self, aip_request: dict) -> dict:
        """
        将 AIP 请求翻译为 OpenAPI HTTP 请求

        AIP 请求格式: {capability: "get /books/search", params: {...}}
        HTTP 请求格式: {method, path, path_params, query_params, body}

        处理路径参数、查询参数、请求体的组装
        """
        capability = aip_request.get("capability")
        params = aip_request.get("params", {})

        if not capability:
            raise ValueError("AIP 请求缺少 capability 字段")

        # 查找对应的 operation
        operation = None
        for op in self.operations.values():
            if op["capability"] == capability:
                operation = op
                break

        if not operation:
            raise ValueError(f"不存在操作: {capability}")

        method = operation["method"]
        path_template = operation["path"]
        operation_spec = operation["spec"]

        # 提取路径参数
        path_params = {}
        query_params = {}
        body = {}

        # 解析 parameters
        parameters = operation_spec.get("parameters", [])
        for param_def in parameters:
            param_name = param_def.get("name")
            param_in = param_def.get("in")  # path, query, header
            required = param_def.get("required", False)

            if param_name in params:
                if param_in == "path":
                    path_params[param_name] = params[param_name]
                elif param_in == "query":
                    query_params[param_name] = params[param_name]

            elif required:
                raise ValueError(f"缺少必填参数: {param_name} (位于 {param_in})")

        # 处理请求体
        request_body = operation_spec.get("requestBody", {})
        if request_body:
            # 将所有非路径、非查询参数放入 body
            param_names = {p.get("name") for p in parameters}
            for key, value in params.items():
                if key not in param_names:
                    body[key] = value

        # 替换路径参数
        path = path_template
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))

        # 校验路径参数是否全部替换完成
        # 如果路径中仍存在 {xxx} 形式的占位符，说明有必填路径参数未提供
        remaining_placeholders = re.findall(r"\{([^}]+)\}", path)
        if remaining_placeholders:
            raise ValueError(
                f"路径参数未替换: {remaining_placeholders}，"
                f"请检查是否提供了所有必填路径参数"
            )

        return {
            "method": method.upper(),
            "path": path,
            "query_params": query_params,
            "body": body if body else None,
        }

    def normalize_result(self, native_result) -> dict:
        """将 HTTP 响应归一化为 AIP 格式"""
        # Mock 实现：假设 native_result 是响应体
        return {
            "ok": True,
            "data": native_result,
            "protocol": "openapi",
        }
