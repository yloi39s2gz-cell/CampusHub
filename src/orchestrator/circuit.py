"""熔断器实现"""

import threading
import time
from enum import Enum


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 熔断状态
    HALF_OPEN = "half_open"  # 半开状态


class CircuitBreaker:
    """熔断器，连续失败 N 次后熔断，冷却时间后半开试探

    线程安全说明：
    - 使用 threading.Lock 保护状态转换，确保多线程/多协程并发调用安全
    - 虽然在单线程 async 事件循环中 sync 方法不会被抢占，
      但为了保护 time.time() 读取和状态写入的原子性，以及兼容
      可能的多线程调用场景（如测试、线程池执行），统一加锁
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        """
        初始化熔断器

        Args:
            failure_threshold: 触发熔断的连续失败次数
            recovery_timeout: 熔断后冷却时间（秒）
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.success_count = 0
        # 并发保护锁
        self._lock = threading.Lock()

    def can_execute(self) -> bool:
        """检查是否可以执行请求"""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                # 检查是否超过冷却时间
                if self.last_failure_time and (time.time() - self.last_failure_time) >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    # 重置成功计数器，确保需要连续成功 N 次才能恢复
                    self.success_count = 0
                    return True
                return False

            # HALF_OPEN 状态允许执行
            return True

    def record_success(self) -> None:
        """记录成功"""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                # 半开状态下连续成功几次后恢复为关闭状态
                if self.success_count >= 2:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            else:
                self.failure_count = 0

    def record_failure(self) -> None:
        """记录失败"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态下失败，立即回到熔断状态
                self.state = CircuitState.OPEN
                self.success_count = 0
            elif self.failure_count >= self.failure_threshold:
                # 连续失败达到阈值，进入熔断状态
                self.state = CircuitState.OPEN

    def reset(self) -> None:
        """重置熔断器"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
