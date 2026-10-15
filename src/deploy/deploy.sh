#!/usr/bin/env bash
# 智枢 CampusHub 一键部署脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="campushub"
CONTAINER_NAME="campushub"
PORT=8000

echo "=========================================="
echo "  智枢 CampusHub 一键部署"
echo "=========================================="

# 1. 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "[错误] 未检测到 Docker，请先安装 Docker"
    exit 1
fi
echo "[√] Docker 已安装: $(docker --version)"

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "[错误] 未检测到 docker-compose / docker compose 插件"
    exit 1
fi
echo "[√] docker-compose 可用"

# 2. 构建镜像
echo ""
echo "[步骤 1/3] 构建镜像 ${IMAGE_NAME} ..."
cd "$PROJECT_DIR"
docker build -t "${IMAGE_NAME}" -f deploy/Dockerfile .
echo "[√] 镜像构建完成"

# 3. 启动容器
echo ""
echo "[步骤 2/3] 启动容器 ..."
# 停止旧容器（如果存在）
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${PORT}:8000" \
    -e ZHISHU_SECRET=campushub-demo-secret \
    "${IMAGE_NAME}"
echo "[√] 容器已启动"

# 4. 轮询健康检查
echo ""
echo "[步骤 3/3] 等待服务就绪 ..."
MAX_RETRIES=30
RETRY_INTERVAL=2
for i in $(seq 1 $MAX_RETRIES); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "[√] 服务已就绪 (HTTP ${HTTP_CODE})"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[错误] 服务启动超时，请检查日志: docker logs ${CONTAINER_NAME}"
        exit 1
    fi
    echo "  等待中... (${i}/${MAX_RETRIES})"
    sleep $RETRY_INTERVAL
done

# 5. 打印访问信息
echo ""
echo "=========================================="
echo "  部署成功！"
echo "=========================================="
echo ""
echo "  访问地址: http://localhost:${PORT}"
echo "  API 文档: http://localhost:${PORT}/docs"
echo "  健康检查: http://localhost:${PORT}/health"
echo ""
echo "  示例命令:"
echo "    # 获取 Token"
echo "    curl -X POST http://localhost:${PORT}/token \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"subject\": \"demo\"}'"
echo ""
echo "    # 发现智能体"
echo "    curl http://localhost:${PORT}/discover?capability=课程"
echo ""
echo "    # 调用智能体"
echo "    curl -X POST http://localhost:${PORT}/invoke \\"
echo "      -H 'Authorization: Bearer <TOKEN>' \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"from_id\": \"user\", \"to_id\": \"course-qa\", \"payload\": {\"query\": \"高等数学\"}}'"
echo ""
echo "  停止服务: docker rm -f ${CONTAINER_NAME}"
echo "  查看日志: docker logs -f ${CONTAINER_NAME}"
echo "=========================================="
