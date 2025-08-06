"""
Comprehensive test suite for core infrastructure components.
Tests exception handling, connection monitoring, rate limiting, and settings.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import os

# Test core exceptions
from src.core.exceptions import (
    SumpPumpError,
    ErrorSeverity,
    TWSConnectionError,
    ConnectionLostError,
    MarketDataLimitError,
    OrderValidationError,
    RateLimitError,
    get_recovery_strategy
)

# Test connection monitoring
from src.core.connection_monitor import (
    ConnectionMonitor,
    ConnectionState,
    ConnectionHealth
)

# Test rate limiting
from src.core.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    TokenBucket,
    SlidingWindowCounter
)

# Test settings
from src.core.settings import (
    Settings,
    TradingMode,
    AccountLevel
)


class TestExceptions:
    """Test exception hierarchy and error handling."""
    
    def test_base_exception(self):
        """Test base SumpPumpError."""
        error = SumpPumpError(
            "Test error",
            severity=ErrorSeverity.HIGH,
            details={"key": "value"},
            recovery_action="Retry operation"
        )
        
        assert str(error) == "Test error"
        assert error.severity == ErrorSeverity.HIGH
        assert error.details == {"key": "value"}
        assert error.recovery_action == "Retry operation"
        
        # Test to_dict
        error_dict = error.to_dict()
        assert error_dict["error"] == "SumpPumpError"
        assert error_dict["message"] == "Test error"
        assert error_dict["severity"] == "high"
    
    def test_connection_errors(self):
        """Test connection-related errors."""
        # Connection lost
        error = ConnectionLostError()
        assert error.severity == ErrorSeverity.CRITICAL
        assert "reconnection" in error.recovery_action.lower()
        
        # Connection timeout
        error = ConnectionTimeoutError(timeout=30)
        assert error.severity == ErrorSeverity.HIGH
        assert "30" in str(error)
        assert "7497" in error.recovery_action
    
    def test_market_data_errors(self):
        """Test market data errors."""
        # No market data
        error = NoMarketDataError("SPY", "Market closed")
        assert error.severity == ErrorSeverity.MEDIUM
        assert "SPY" in str(error)
        assert error.details["symbol"] == "SPY"
        
        # Market data limit
        error = MarketDataLimitError(current=100, limit=100)
        assert error.severity == ErrorSeverity.HIGH
        assert "100/100" in str(error)
    
    def test_trading_errors(self):
        """Test trading-related errors."""
        # Order validation
        error = OrderValidationError("Invalid quantity", field="quantity", value=-1)
        assert error.severity == ErrorSeverity.HIGH
        assert error.details["field"] == "quantity"
        assert error.details["value"] == -1
    
    def test_recovery_strategy(self):
        """Test recovery strategy determination."""
        # Connection lost - should retry
        error = ConnectionLostError()
        strategy = get_recovery_strategy(error)
        assert strategy["should_retry"] is True
        assert strategy["action"] == "reconnect"
        assert strategy["max_retries"] == 3
        
        # Rate limit - should wait
        error = RateLimitError(retry_after=60)
        strategy = get_recovery_strategy(error)
        assert strategy["should_retry"] is True
        assert strategy["retry_delay"] == 60
        assert strategy["action"] == "wait"
        
        # Critical error - should abort
        error = SumpPumpError("Critical failure", severity=ErrorSeverity.CRITICAL)
        strategy = get_recovery_strategy(error)
        assert strategy["should_retry"] is False
        assert strategy["action"] == "abort"


class TestConnectionMonitor:
    """Test connection monitoring and recovery."""
    
    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        conn.isConnected = Mock(return_value=True)
        conn.ping = AsyncMock()
        return conn
    
    @pytest.fixture
    def connection_factory(self, mock_connection):
        """Create connection factory."""
        return Mock(return_value=mock_connection)
    
    @pytest.mark.asyncio
    async def test_monitor_initialization(self, connection_factory):
        """Test monitor initialization."""
        monitor = ConnectionMonitor(
            connection_factory=connection_factory,
            heartbeat_interval=1,
            max_reconnect_attempts=3
        )
        
        assert monitor.health.state == ConnectionState.DISCONNECTED
        assert monitor.heartbeat_interval == 1
        assert monitor.max_reconnect_attempts == 3
    
    @pytest.mark.asyncio
    async def test_monitor_start_stop(self, connection_factory):
        """Test starting and stopping monitor."""
        monitor = ConnectionMonitor(connection_factory=connection_factory)
        
        # Start monitor
        await monitor.start()
        assert monitor.health.state == ConnectionState.CONNECTED
        assert monitor.is_connected
        assert connection_factory.called
        
        # Stop monitor
        await monitor.stop()
        assert monitor.health.state == ConnectionState.SHUTDOWN
        assert not monitor.is_connected
    
    @pytest.mark.asyncio
    async def test_connection_health(self):
        """Test connection health tracking."""
        health = ConnectionHealth()
        
        # Initial state
        assert not health.is_healthy
        assert health.uptime is None
        
        # Connected state
        health.state = ConnectionState.CONNECTED
        health.connection_time = datetime.now()
        health.last_heartbeat = datetime.now()
        assert health.is_healthy
        assert health.uptime is not None
        
        # Unhealthy - old heartbeat
        health.last_heartbeat = datetime.now() - timedelta(minutes=1)
        assert not health.is_healthy
        
        # Test to_dict
        health_dict = health.to_dict()
        assert health_dict["state"] == "connected"
        assert "uptime" in health_dict
    
    @pytest.mark.asyncio
    async def test_reconnection(self, connection_factory):
        """Test automatic reconnection."""
        # Create failing then succeeding connection
        attempt_count = 0
        
        def factory():
            nonlocal attempt_count
            attempt_count += 1
            conn = Mock()
            if attempt_count == 1:
                # First attempt fails
                raise ConnectionTimeoutError()
            else:
                # Second attempt succeeds
                conn.isConnected = Mock(return_value=True)
                return conn
        
        monitor = ConnectionMonitor(
            connection_factory=factory,
            max_reconnect_attempts=3,
            reconnect_delay=0.1
        )
        
        # Should reconnect successfully
        success = await monitor._reconnect()
        assert success
        assert monitor.health.reconnect_count == 1
    
    @pytest.mark.asyncio
    async def test_callbacks(self, connection_factory):
        """Test connection callbacks."""
        connected_called = False
        disconnected_called = False
        error_called = False
        
        async def on_connected():
            nonlocal connected_called
            connected_called = True
        
        async def on_disconnected():
            nonlocal disconnected_called
            disconnected_called = True
        
        async def on_error(error):
            nonlocal error_called
            error_called = True
        
        monitor = ConnectionMonitor(connection_factory=connection_factory)
        monitor.on_connected(on_connected)
        monitor.on_disconnected(on_disconnected)
        monitor.on_error(on_error)
        
        # Test connected callback
        await monitor._connect()
        assert connected_called
        
        # Test disconnected callback
        await monitor._disconnect()
        assert disconnected_called


class TestRateLimiter:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_token_bucket(self):
        """Test token bucket algorithm."""
        # Create bucket with 10 tokens/sec, capacity 20
        bucket = TokenBucket(rate=10, capacity=20)
        
        # Initial capacity
        assert await bucket.try_acquire(10) is True  # Should succeed
        assert await bucket.try_acquire(15) is False  # Should fail (only 10 left)
        
        # Wait time calculation
        wait_time = await bucket.acquire(25)  # Need 25, have 10
        assert wait_time > 0  # Should need to wait
    
    @pytest.mark.asyncio
    async def test_sliding_window(self):
        """Test sliding window counter."""
        window = SlidingWindowCounter(window_size_seconds=1)
        
        # Add requests
        count1 = await window.add_request()
        assert count1 == 1
        
        count2 = await window.add_request()
        assert count2 == 2
        
        # Check count
        current_count = await window.get_count()
        assert current_count == 2
        
        # Wait for window to expire
        await asyncio.sleep(1.1)
        expired_count = await window.get_count()
        assert expired_count == 0
    
    @pytest.mark.asyncio
    async def test_rate_limiter_general(self):
        """Test general rate limiting."""
        config = RateLimitConfig(
            max_requests_per_second=10,
            burst_size=5
        )
        limiter = RateLimiter(config)
        
        # Should allow initial burst
        for _ in range(5):
            await limiter.acquire("general")
        
        assert limiter.stats.accepted_requests == 5
        assert limiter.stats.rejected_requests == 0
    
    @pytest.mark.asyncio
    async def test_rate_limiter_orders(self):
        """Test order-specific rate limiting."""
        config = RateLimitConfig(max_orders_per_second=2)
        limiter = RateLimiter(config)
        
        # Should allow 2 orders quickly
        await limiter.acquire("order")
        await limiter.acquire("order")
        
        # Third should be delayed
        start = asyncio.get_event_loop().time()
        await limiter.acquire("order")
        elapsed = asyncio.get_event_loop().time() - start
        
        assert elapsed > 0  # Should have waited
        assert limiter.stats.delayed_requests > 0
    
    @pytest.mark.asyncio
    async def test_market_data_subscriptions(self):
        """Test market data subscription tracking."""
        config = RateLimitConfig(max_market_data_lines=3)
        limiter = RateLimiter(config)
        
        # Add subscriptions
        await limiter.add_market_data_subscription("SPY")
        await limiter.add_market_data_subscription("AAPL")
        await limiter.add_market_data_subscription("MSFT")
        
        # Should be at limit
        with pytest.raises(RateLimitError):
            await limiter.add_market_data_subscription("GOOGL")
        
        # Remove one
        await limiter.remove_market_data_subscription("SPY")
        
        # Should now work
        await limiter.add_market_data_subscription("GOOGL")
    
    def test_rate_limiter_stats(self):
        """Test rate limiter statistics."""
        limiter = RateLimiter()
        
        # Initial stats
        stats = limiter.get_stats()
        assert stats["total_requests"] == 0
        assert stats["acceptance_rate"] == 0
        
        # Reset stats
        limiter.stats.total_requests = 10
        limiter.stats.accepted_requests = 8
        limiter.reset_stats()
        
        stats = limiter.get_stats()
        assert stats["total_requests"] == 0


class TestSettings:
    """Test settings validation and configuration."""
    
    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        
        assert settings.tws_host == "127.0.0.1"
        assert settings.tws_port == 7497
        assert settings.tws_client_id == 5
        assert settings.trading_mode == TradingMode.LIVE
        assert settings.account_level == AccountLevel.LEVEL_2
        assert settings.require_confirmation is True
    
    def test_settings_validation(self):
        """Test settings validation."""
        # Valid settings
        settings = Settings(
            tws_port=7497,
            trading_mode=TradingMode.LIVE,
            max_position_size=5000,
            max_daily_loss=1000
        )
        assert settings.tws_port == 7497
        
        # Invalid port for trading mode
        with pytest.raises(ValueError, match="Paper trading should use port 7496"):
            Settings(
                tws_port=7497,
                trading_mode=TradingMode.PAPER
            )
        
        # Invalid risk settings
        with pytest.raises(ValueError, match="Max position size"):
            Settings(
                max_position_size=10000,
                max_daily_loss=1000
            )
    
    def test_settings_from_env(self, monkeypatch):
        """Test loading settings from environment."""
        monkeypatch.setenv("TWS_HOST", "192.168.1.100")
        monkeypatch.setenv("TWS_PORT", "7496")
        monkeypatch.setenv("TRADING_MODE", "paper")
        
        settings = Settings()
        assert settings.tws_host == "192.168.1.100"
        assert settings.tws_port == 7496
        assert settings.trading_mode == TradingMode.PAPER
    
    def test_settings_methods(self):
        """Test settings utility methods."""
        settings = Settings()
        
        # Get connection params
        params = settings.get_tws_connection_params()
        assert params["host"] == "127.0.0.1"
        assert params["port"] == 7497
        assert params["client_id"] == 5
        
        # Get rate limit config
        rate_config = settings.get_rate_limit_config()
        assert rate_config["enabled"] is True
        assert rate_config["max_requests_per_second"] == 50
        
        # Validate for trading
        warnings = settings.validate_for_trading()
        assert isinstance(warnings, list)
    
    def test_settings_to_dict(self):
        """Test settings serialization."""
        settings = Settings(tws_account="U1234567")
        
        # With sensitive data masked
        data = settings.to_dict(exclude_sensitive=True)
        assert data["tws_account"] == "***MASKED***"
        
        # Without masking
        data = settings.to_dict(exclude_sensitive=False)
        assert data["tws_account"] == "U1234567"


class TestIntegration:
    """Integration tests for components working together."""
    
    @pytest.mark.asyncio
    async def test_monitor_with_rate_limiter(self):
        """Test connection monitor with rate limiting."""
        # Create mock connection that respects rate limits
        call_count = 0
        
        def factory():
            nonlocal call_count
            call_count += 1
            conn = Mock()
            conn.isConnected = Mock(return_value=True)
            conn.ping = AsyncMock()
            return conn
        
        # Setup components
        monitor = ConnectionMonitor(
            connection_factory=factory,
            heartbeat_interval=0.5
        )
        limiter = RateLimiter(
            RateLimitConfig(max_requests_per_second=2)
        )
        
        # Start monitor
        await monitor.start()
        
        # Simulate rate-limited operations
        for _ in range(3):
            await limiter.acquire("general")
            if monitor.is_connected:
                # Simulate API call
                pass
        
        # Verify rate limiting worked
        assert limiter.stats.accepted_requests >= 3
        
        await monitor.stop()
    
    @pytest.mark.asyncio
    async def test_error_recovery_flow(self):
        """Test complete error recovery flow."""
        # Simulate connection error
        error = ConnectionLostError()
        strategy = get_recovery_strategy(error)
        
        assert strategy["should_retry"] is True
        assert strategy["action"] == "reconnect"
        
        # Create monitor with recovery
        attempts = 0
        
        def factory():
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise ConnectionTimeoutError()
            conn = Mock()
            conn.isConnected = Mock(return_value=True)
            return conn
        
        monitor = ConnectionMonitor(
            connection_factory=factory,
            max_reconnect_attempts=3
        )
        
        # Should recover after initial failure
        success = await monitor._reconnect()
        assert success
        assert attempts == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])