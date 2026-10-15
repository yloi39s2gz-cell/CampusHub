# 智枢 CampusHub 镜像
FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制源码（构建上下文即为 src/ 目录本身）
COPY . ./src/

# 设置 Python 路径
ENV PYTHONPATH=/app/src

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
