"""指数退避重试机制"""

import asyncio
import random
from typing import Awaitable, Callable


async def async_retry(
    coro_fn: Callable[..., Awaitable],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
    *args,
    **kwargs,
):
    """
    指数退避重试函数

    延迟计算: delay = min(base_delay * 2^attempt, max_delay)
    可选抖动: delay *= random.uniform(0.5, 1.5)

    Args:
        coro_fn: 异步可调用对象
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限（秒），防止指数增长过大
        jitter: 是否添加随机抖动（默认 True），避免惊群效应
        retryable_exceptions: 可重试的异常类型元组，None 表示重试所有异常
        *args, **kwargs: 传递给 coro_fn 的参数

    Returns:
        coro_fn 的返回值

    Raises:
        最后一次尝试的异常
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as e:
            last_exception = e
            # 如果指定了可重试异常类型，检查当前异常是否在其中
            if retryable_exceptions is not None and not isinstance(e, retryable_exceptions):
                raise
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                # 应用最大延迟上限
                delay = min(delay, max_delay)
                # 添加随机抖动避免惊群效应
                if jitter:
                    delay *= random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)

    raise last_exception
