"""
Core infrastructure modules for SumpPump trading system.
Provides error handling, connection monitoring, rate limiting, and configuration.
"""

# Exception hierarchy
from src.core.exceptions import (
    # Base
    SumpPumpError,
    ErrorSeverity,
    
    # Connection
    TWSConnectionError,
    ConnectionLostError,
    ConnectionTimeoutError,
    
    # Market Data
    MarketDataError,
    NoMarketDataError,
    MarketDataLimitError,
    
    # Trading
    TradingError,
    OrderValidationError,
    InsufficientFundsError,
    PositionLimitError,
    
    # Risk
    RiskError,
    MaxLossExceededError,
    MarginRequirementError,
    
    # Strategy
    StrategyError,
    InvalidStrategyError,
    StrategyNotPermittedError,
    
    # Configuration
    ConfigurationError,
    MissingConfigError,
    InvalidConfigError,
    
    # Rate Limiting
    RateLimitError,
    
    # Utilities
    get_recovery_strategy
)

# Connection monitoring
from src.core.connection_monitor import (
    ConnectionMonitor,
    ConnectionState,
    ConnectionHealth,
    with_connection_retry
)

# Rate limiting
from src.core.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStats,
    TokenBucket,
    SlidingWindowCounter,
    rate_limited,
    get_rate_limiter,
    set_rate_limiter
)

# Settings and configuration
from src.core.settings import (
    Settings,
    TradingMode,
    LogLevel,
    AccountLevel,
    get_settings,
    reload_settings,
    override_settings
)

__all__ = [
    # Exceptions
    'SumpPumpError',
    'ErrorSeverity',
    'TWSConnectionError',
    'ConnectionLostError',
    'ConnectionTimeoutError',
    'MarketDataError',
    'NoMarketDataError',
    'MarketDataLimitError',
    'TradingError',
    'OrderValidationError',
    'InsufficientFundsError',
    'PositionLimitError',
    'RiskError',
    'MaxLossExceededError',
    'MarginRequirementError',
    'StrategyError',
    'InvalidStrategyError',
    'StrategyNotPermittedError',
    'ConfigurationError',
    'MissingConfigError',
    'InvalidConfigError',
    'RateLimitError',
    'get_recovery_strategy',
    
    # Connection monitoring
    'ConnectionMonitor',
    'ConnectionState',
    'ConnectionHealth',
    'with_connection_retry',
    
    # Rate limiting
    'RateLimiter',
    'RateLimitConfig',
    'RateLimitStats',
    'TokenBucket',
    'SlidingWindowCounter',
    'rate_limited',
    'get_rate_limiter',
    'set_rate_limiter',
    
    # Settings
    'Settings',
    'TradingMode',
    'LogLevel',
    'AccountLevel',
    'get_settings',
    'reload_settings',
    'override_settings'
]