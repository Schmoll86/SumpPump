"""
Custom exception hierarchy for SumpPump trading system.
Provides structured error handling across all modules.
"""

from typing import Optional, Dict, Any
from enum import Enum


class ErrorSeverity(Enum):
    """Error severity levels for logging and handling decisions."""
    LOW = "low"       # Can continue, minor issue
    MEDIUM = "medium" # Should warn user, may affect functionality
    HIGH = "high"     # Critical issue, stop current operation
    CRITICAL = "critical"  # System failure, disconnect required


class SumpPumpError(Exception):
    """Base exception for all SumpPump errors."""
    
    def __init__(
        self, 
        message: str, 
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        details: Optional[Dict[str, Any]] = None,
        recovery_action: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.details = details or {}
        self.recovery_action = recovery_action
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for MCP responses."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "severity": self.severity.value,
            "details": self.details,
            "recovery_action": self.recovery_action
        }


# Connection Errors
class TWSConnectionError(SumpPumpError):
    """TWS connection related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            severity=kwargs.get('severity', ErrorSeverity.HIGH),
            **{k: v for k, v in kwargs.items() if k != 'severity'}
        )


class ConnectionLostError(TWSConnectionError):
    """Connection to TWS was lost."""
    def __init__(self, message: str = "Lost connection to TWS"):
        super().__init__(
            message,
            severity=ErrorSeverity.CRITICAL,
            recovery_action="Attempting automatic reconnection..."
        )


class ConnectionTimeoutError(TWSConnectionError):
    """Connection attempt timed out."""
    def __init__(self, timeout: int = 30):
        super().__init__(
            f"Connection timeout after {timeout} seconds",
            severity=ErrorSeverity.HIGH,
            details={"timeout": timeout},
            recovery_action="Check TWS is running and API is enabled on port 7497"
        )


# Market Data Errors
class MarketDataError(SumpPumpError):
    """Market data related errors."""
    pass


class NoMarketDataError(MarketDataError):
    """No market data available for symbol."""
    def __init__(self, symbol: str, reason: str = "Unknown"):
        super().__init__(
            f"No market data for {symbol}: {reason}",
            severity=ErrorSeverity.MEDIUM,
            details={"symbol": symbol, "reason": reason},
            recovery_action="Check market hours and data subscriptions"
        )


class MarketDataLimitError(MarketDataError):
    """Exceeded market data line limit."""
    def __init__(self, current: int, limit: int):
        super().__init__(
            f"Market data limit exceeded: {current}/{limit}",
            severity=ErrorSeverity.HIGH,
            details={"current": current, "limit": limit},
            recovery_action="Reduce number of simultaneous subscriptions"
        )


# Trading Errors
class TradingError(SumpPumpError):
    """Trading and order related errors."""
    pass


class OrderValidationError(TradingError):
    """Order failed validation checks."""
    def __init__(self, message: str, field: str = None, value: Any = None):
        super().__init__(
            message,
            severity=ErrorSeverity.HIGH,
            details={"field": field, "value": value} if field else {},
            recovery_action="Review order parameters and retry"
        )


class InsufficientFundsError(TradingError):
    """Insufficient funds for trade."""
    def __init__(self, required: float, available: float):
        super().__init__(
            f"Insufficient funds: required ${required:.2f}, available ${available:.2f}",
            severity=ErrorSeverity.HIGH,
            details={"required": required, "available": available},
            recovery_action="Reduce position size or add funds"
        )


class PositionLimitError(TradingError):
    """Position limit exceeded."""
    def __init__(self, symbol: str, limit: int):
        super().__init__(
            f"Position limit exceeded for {symbol}",
            severity=ErrorSeverity.HIGH,
            details={"symbol": symbol, "limit": limit},
            recovery_action="Close existing positions before opening new ones"
        )


# Risk Management Errors
class RiskError(SumpPumpError):
    """Risk management related errors."""
    pass


class MaxLossExceededError(RiskError):
    """Max loss threshold exceeded."""
    def __init__(self, max_loss: float, calculated_loss: float):
        super().__init__(
            f"Max loss exceeded: ${calculated_loss:.2f} > ${max_loss:.2f}",
            severity=ErrorSeverity.HIGH,
            details={"max_loss": max_loss, "calculated_loss": calculated_loss},
            recovery_action="Reduce position size or adjust strategy"
        )


class MarginRequirementError(RiskError):
    """Margin requirement not met."""
    def __init__(self, required_margin: float, available_margin: float):
        super().__init__(
            f"Margin requirement not met: need ${required_margin:.2f}, have ${available_margin:.2f}",
            severity=ErrorSeverity.HIGH,
            details={"required": required_margin, "available": available_margin},
            recovery_action="Reduce leverage or add margin"
        )


# Strategy Errors
class StrategyError(SumpPumpError):
    """Strategy calculation and validation errors."""
    pass


class InvalidStrategyError(StrategyError):
    """Invalid strategy configuration."""
    def __init__(self, strategy_name: str, reason: str):
        super().__init__(
            f"Invalid {strategy_name} strategy: {reason}",
            severity=ErrorSeverity.MEDIUM,
            details={"strategy": strategy_name, "reason": reason},
            recovery_action="Review strategy parameters"
        )


class StrategyNotPermittedError(StrategyError):
    """Strategy not permitted for account level."""
    def __init__(self, strategy_name: str, required_level: int, current_level: int = 2):
        super().__init__(
            f"{strategy_name} requires Level {required_level} (current: Level {current_level})",
            severity=ErrorSeverity.HIGH,
            details={
                "strategy": strategy_name, 
                "required_level": required_level,
                "current_level": current_level
            },
            recovery_action="Use permitted strategies or upgrade account level"
        )


# Configuration Errors
class ConfigurationError(SumpPumpError):
    """Configuration and setup errors."""
    pass


class MissingConfigError(ConfigurationError):
    """Required configuration missing."""
    def __init__(self, config_key: str):
        super().__init__(
            f"Missing required configuration: {config_key}",
            severity=ErrorSeverity.CRITICAL,
            details={"missing_key": config_key},
            recovery_action=f"Set {config_key} in .env file"
        )


class InvalidConfigError(ConfigurationError):
    """Invalid configuration value."""
    def __init__(self, config_key: str, value: Any, expected: str):
        super().__init__(
            f"Invalid {config_key}: {value} (expected: {expected})",
            severity=ErrorSeverity.HIGH,
            details={"key": config_key, "value": value, "expected": expected},
            recovery_action=f"Update {config_key} in .env file"
        )


# API Rate Limiting
class RateLimitError(SumpPumpError):
    """API rate limit exceeded."""
    def __init__(self, limit_type: str = "requests", retry_after: int = None):
        super().__init__(
            f"Rate limit exceeded for {limit_type}",
            severity=ErrorSeverity.MEDIUM,
            details={"limit_type": limit_type, "retry_after": retry_after},
            recovery_action=f"Wait {retry_after} seconds before retrying" if retry_after else "Reduce request frequency"
        )


# Utility function for error recovery
def get_recovery_strategy(error: SumpPumpError) -> Dict[str, Any]:
    """
    Get recovery strategy based on error type and severity.
    
    Returns dict with:
    - should_retry: bool
    - retry_delay: int (seconds)
    - max_retries: int
    - action: str (reconnect, wait, abort, etc.)
    """
    if isinstance(error, ConnectionLostError):
        return {
            "should_retry": True,
            "retry_delay": 5,
            "max_retries": 3,
            "action": "reconnect"
        }
    elif isinstance(error, ConnectionTimeoutError):
        return {
            "should_retry": True,
            "retry_delay": 10,
            "max_retries": 2,
            "action": "reconnect"
        }
    elif isinstance(error, RateLimitError):
        return {
            "should_retry": True,
            "retry_delay": error.details.get("retry_after", 60),
            "max_retries": 1,
            "action": "wait"
        }
    elif isinstance(error, MarketDataLimitError):
        return {
            "should_retry": False,
            "retry_delay": 0,
            "max_retries": 0,
            "action": "reduce_subscriptions"
        }
    elif error.severity == ErrorSeverity.CRITICAL:
        return {
            "should_retry": False,
            "retry_delay": 0,
            "max_retries": 0,
            "action": "abort"
        }
    else:
        return {
            "should_retry": error.severity in [ErrorSeverity.LOW, ErrorSeverity.MEDIUM],
            "retry_delay": 5,
            "max_retries": 1,
            "action": "retry"
        }