"""
Rate limiting system for TWS API calls.
Prevents overwhelming the API and handles rate limit errors gracefully.
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta
from functools import wraps

from src.core.exceptions import RateLimitError


logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    # TWS API limits (conservative defaults)
    max_requests_per_second: int = 50  # TWS can handle ~50 msgs/sec
    max_market_data_lines: int = 100   # Concurrent market data subscriptions
    max_orders_per_second: int = 5     # Order placement rate
    max_historical_data_requests: int = 60  # Per 10 minutes
    
    # Burst handling
    burst_size: int = 10               # Allow short bursts
    burst_window_seconds: int = 1      # Burst window duration
    
    # Backoff configuration
    initial_backoff_ms: int = 100      # Initial backoff delay
    max_backoff_ms: int = 30000        # Maximum backoff delay
    backoff_multiplier: float = 2.0    # Exponential backoff multiplier


@dataclass
class RateLimitStats:
    """Statistics for rate limiting."""
    total_requests: int = 0
    accepted_requests: int = 0
    rejected_requests: int = 0
    delayed_requests: int = 0
    total_delay_ms: float = 0
    last_reset: datetime = field(default_factory=datetime.now)
    
    def reset(self):
        """Reset statistics."""
        self.total_requests = 0
        self.accepted_requests = 0
        self.rejected_requests = 0
        self.delayed_requests = 0
        self.total_delay_ms = 0
        self.last_reset = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_requests": self.total_requests,
            "accepted_requests": self.accepted_requests,
            "rejected_requests": self.rejected_requests,
            "delayed_requests": self.delayed_requests,
            "avg_delay_ms": self.total_delay_ms / max(self.delayed_requests, 1),
            "acceptance_rate": self.accepted_requests / max(self.total_requests, 1),
            "period_seconds": (datetime.now() - self.last_reset).total_seconds()
        }


class TokenBucket:
    """
    Token bucket algorithm for rate limiting.
    Allows burst traffic while maintaining average rate.
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Initialize token bucket.
        
        Args:
            rate: Tokens added per second
            capacity: Maximum bucket capacity
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens from bucket.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            float: Wait time in seconds (0 if tokens available immediately)
        """
        async with self._lock:
            now = time.monotonic()
            
            # Add tokens based on time elapsed
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                # Tokens available
                self.tokens -= tokens
                return 0
            else:
                # Calculate wait time
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate
                
                # Reserve tokens (will go negative)
                self.tokens -= tokens
                
                return wait_time
    
    async def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            bool: True if tokens acquired, False otherwise
        """
        async with self._lock:
            now = time.monotonic()
            
            # Add tokens based on time elapsed
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False


class SlidingWindowCounter:
    """
    Sliding window counter for tracking request rates.
    """
    
    def __init__(self, window_size_seconds: int):
        """
        Initialize sliding window counter.
        
        Args:
            window_size_seconds: Size of the sliding window in seconds
        """
        self.window_size = timedelta(seconds=window_size_seconds)
        self.requests = deque()
        self._lock = asyncio.Lock()
    
    async def add_request(self) -> int:
        """
        Add a request to the counter.
        
        Returns:
            int: Current request count in window
        """
        async with self._lock:
            now = datetime.now()
            
            # Remove old requests outside window
            cutoff = now - self.window_size
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()
            
            # Add new request
            self.requests.append(now)
            
            return len(self.requests)
    
    async def get_count(self) -> int:
        """
        Get current request count in window.
        
        Returns:
            int: Request count
        """
        async with self._lock:
            now = datetime.now()
            cutoff = now - self.window_size
            
            # Remove old requests
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()
            
            return len(self.requests)


class RateLimiter:
    """
    Comprehensive rate limiter for TWS API calls.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiter.
        
        Args:
            config: Rate limit configuration
        """
        self.config = config or RateLimitConfig()
        self.stats = RateLimitStats()
        
        # Different buckets for different operation types
        self.general_bucket = TokenBucket(
            rate=self.config.max_requests_per_second,
            capacity=self.config.burst_size
        )
        
        self.order_bucket = TokenBucket(
            rate=self.config.max_orders_per_second,
            capacity=self.config.max_orders_per_second * 2
        )
        
        # Sliding windows for longer-term limits
        self.historical_data_window = SlidingWindowCounter(600)  # 10 minutes
        
        # Track active market data subscriptions
        self.active_market_data = set()
        self._market_data_lock = asyncio.Lock()
        
        # Backoff state
        self.backoff_until: Optional[datetime] = None
        self.consecutive_errors = 0
    
    async def acquire(self, operation_type: str = "general", weight: int = 1) -> None:
        """
        Acquire permission for an operation.
        
        Args:
            operation_type: Type of operation (general, order, historical_data, market_data)
            weight: Weight of the operation (for weighted rate limiting)
            
        Raises:
            RateLimitError: If rate limit exceeded and cannot wait
        """
        self.stats.total_requests += 1
        
        # Check if in backoff period
        if self.backoff_until and datetime.now() < self.backoff_until:
            wait_seconds = (self.backoff_until - datetime.now()).total_seconds()
            self.stats.rejected_requests += 1
            raise RateLimitError(
                limit_type=operation_type,
                retry_after=int(wait_seconds)
            )
        
        # Handle different operation types
        if operation_type == "general":
            wait_time = await self.general_bucket.acquire(weight)
            
        elif operation_type == "order":
            # Orders need both general and order-specific tokens
            general_wait = await self.general_bucket.acquire(weight)
            order_wait = await self.order_bucket.acquire(1)
            wait_time = max(general_wait, order_wait)
            
        elif operation_type == "historical_data":
            # Check sliding window limit
            count = await self.historical_data_window.add_request()
            if count > self.config.max_historical_data_requests:
                self.stats.rejected_requests += 1
                raise RateLimitError(
                    limit_type="historical_data",
                    retry_after=60  # Wait at least a minute
                )
            wait_time = await self.general_bucket.acquire(weight)
            
        elif operation_type == "market_data":
            # Check subscription limit
            async with self._market_data_lock:
                if len(self.active_market_data) >= self.config.max_market_data_lines:
                    self.stats.rejected_requests += 1
                    raise RateLimitError(
                        limit_type="market_data_subscriptions",
                        retry_after=0  # No automatic retry for this
                    )
            wait_time = await self.general_bucket.acquire(weight)
            
        else:
            wait_time = await self.general_bucket.acquire(weight)
        
        # Apply wait if necessary
        if wait_time > 0:
            self.stats.delayed_requests += 1
            self.stats.total_delay_ms += wait_time * 1000
            logger.debug(f"Rate limit delay: {wait_time:.3f}s for {operation_type}")
            await asyncio.sleep(wait_time)
        
        self.stats.accepted_requests += 1
        self.consecutive_errors = 0
    
    async def try_acquire(self, operation_type: str = "general") -> bool:
        """
        Try to acquire permission without waiting.
        
        Args:
            operation_type: Type of operation
            
        Returns:
            bool: True if acquired, False if would need to wait
        """
        if operation_type == "general":
            return await self.general_bucket.try_acquire()
        elif operation_type == "order":
            return (await self.general_bucket.try_acquire() and 
                   await self.order_bucket.try_acquire())
        else:
            return await self.general_bucket.try_acquire()
    
    async def add_market_data_subscription(self, symbol: str) -> None:
        """
        Add a market data subscription.
        
        Args:
            symbol: Symbol being subscribed
            
        Raises:
            RateLimitError: If at subscription limit
        """
        async with self._market_data_lock:
            if len(self.active_market_data) >= self.config.max_market_data_lines:
                raise RateLimitError(
                    limit_type="market_data_subscriptions",
                    retry_after=0
                )
            self.active_market_data.add(symbol)
            logger.debug(f"Added market data subscription for {symbol} "
                        f"({len(self.active_market_data)}/{self.config.max_market_data_lines})")
    
    async def remove_market_data_subscription(self, symbol: str) -> None:
        """
        Remove a market data subscription.
        
        Args:
            symbol: Symbol being unsubscribed
        """
        async with self._market_data_lock:
            self.active_market_data.discard(symbol)
            logger.debug(f"Removed market data subscription for {symbol} "
                        f"({len(self.active_market_data)}/{self.config.max_market_data_lines})")
    
    async def clear_market_data_subscriptions(self) -> None:
        """Clear all market data subscriptions."""
        async with self._market_data_lock:
            count = len(self.active_market_data)
            self.active_market_data.clear()
            logger.info(f"Cleared {count} market data subscriptions")
    
    def handle_rate_limit_error(self, error_message: str) -> None:
        """
        Handle rate limit error from TWS.
        
        Args:
            error_message: Error message from TWS
        """
        self.consecutive_errors += 1
        
        # Calculate backoff
        backoff_ms = min(
            self.config.initial_backoff_ms * (self.config.backoff_multiplier ** self.consecutive_errors),
            self.config.max_backoff_ms
        )
        
        self.backoff_until = datetime.now() + timedelta(milliseconds=backoff_ms)
        logger.warning(f"Rate limit error, backing off for {backoff_ms}ms")
    
    def reset_backoff(self) -> None:
        """Reset backoff state."""
        self.backoff_until = None
        self.consecutive_errors = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        stats = self.stats.to_dict()
        stats["active_market_data"] = len(self.active_market_data)
        stats["in_backoff"] = self.backoff_until is not None
        return stats
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self.stats.reset()


# Decorator for rate-limited methods
def rate_limited(operation_type: str = "general", weight: int = 1):
    """
    Decorator for rate-limited methods.
    
    Usage:
        @rate_limited(operation_type="order")
        async def place_order(self, order):
            # Method that places order
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Check if self has rate limiter
            if hasattr(self, 'rate_limiter') and self.rate_limiter:
                await self.rate_limiter.acquire(operation_type, weight)
            
            try:
                return await func(self, *args, **kwargs)
            except Exception as e:
                # Check if it's a rate limit error from TWS
                error_msg = str(e).lower()
                if 'rate' in error_msg and 'limit' in error_msg:
                    if hasattr(self, 'rate_limiter') and self.rate_limiter:
                        self.rate_limiter.handle_rate_limit_error(str(e))
                raise
        
        return wrapper
    return decorator


# Global rate limiter instance (can be shared across modules)
_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    return _global_rate_limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    """Set global rate limiter instance."""
    global _global_rate_limiter
    _global_rate_limiter = limiter