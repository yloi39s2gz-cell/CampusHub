"""结构化 JSON 行日志 - 落盘到 logs/app.log，便于技术报告量化分析"""

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


# 日志目录（相对于项目 src/）
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")


class JsonFormatter(logging.Formatter):
    """
    JSON 行格式器

    每条日志输出为一行 JSON，包含：
    - timestamp: ISO 8601 时间戳
    - level: 日志级别
    - event: 日志消息（即 logger.info 的 msg 参数）
    - 以及 extra 中传入的任意字段（duration_ms / agent_id / task_id 等）
    """

    def format(self, record: logging.LogRecord) -> str:
        """将日志记录格式化为单行 JSON"""
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # 把 extra 字段中的业务字段合并进去
        # 标准 LogRecord 属性排除，只保留业务自定义字段
        standard_keys = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
        for key, value in record.__dict__.items():
            if key not in standard_keys and key not in ("msg", "args"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def setup_json_logging() -> logging.Logger:
    """
    配置 JSON 行日志，落盘到 logs/app.log

    - 单文件上限 5MB，保留 3 个备份（RotatingFileHandler）
    - 返回根 logger "aic"，业务代码通过 logging.getLogger("aic") 使用

    Returns:
        配置好的根 logger
    """
    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("aic")
    # 避免重复添加 handler（测试场景下可能多次调用）
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # 滚动文件 handler：单文件 5MB，保留 3 个
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    return logger
