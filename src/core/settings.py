"""
Application settings with Pydantic validation.
Provides type-safe configuration with validation and defaults.
"""

import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from enum import Enum

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from pydantic.types import SecretStr

from src.core.exceptions import ConfigurationError, MissingConfigError, InvalidConfigError


class TradingMode(str, Enum):
    """Trading mode enum."""
    LIVE = "live"
    PAPER = "paper"
    SIMULATION = "simulation"


class LogLevel(str, Enum):
    """Log level enum."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AccountLevel(int, Enum):
    """IBKR account level permissions."""
    LEVEL_1 = 1  # Basic stocks and ETFs
    LEVEL_2 = 2  # Long options, covered strategies
    LEVEL_3 = 3  # Spreads, naked puts
    LEVEL_4 = 4  # Naked calls, complex strategies


class Settings(BaseSettings):
    """
    Application settings with validation.
    
    Settings are loaded from environment variables and .env file.
    All values are validated on load.
    """
    
    # TWS Connection Settings
    tws_host: str = Field(
        default="127.0.0.1",
        description="TWS API hostname",
        pattern="^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$|^localhost$"
    )
    
    tws_port: int = Field(
        default=7497,
        description="TWS API port (7497 for live, 7496 for paper)",
        ge=1,
        le=65535
    )
    
    tws_client_id: int = Field(
        default=5,
        description="TWS client ID (avoid 1 which can conflict)",
        ge=0,
        le=999
    )
    
    tws_account: Optional[str] = Field(
        default=None,
        description="TWS account ID (auto-detected if not set)",
        pattern="^[A-Z0-9]{8}$|^$"
    )
    
    tws_timeout: int = Field(
        default=30,
        description="Connection timeout in seconds",
        ge=5,
        le=300
    )
    
    # Trading Settings
    trading_mode: TradingMode = Field(
        default=TradingMode.LIVE,
        description="Trading mode (live/paper/simulation)"
    )
    
    account_level: AccountLevel = Field(
        default=AccountLevel.LEVEL_2,
        description="IBKR account permission level"
    )
    
    max_position_size: float = Field(
        default=10000.0,
        description="Maximum position size in dollars",
        gt=0
    )
    
    max_daily_loss: float = Field(
        default=1000.0,
        description="Maximum daily loss in dollars",
        gt=0
    )
    
    require_confirmation: bool = Field(
        default=True,
        description="Require confirmation for trades"
    )
    
    auto_stop_loss: bool = Field(
        default=True,
        description="Automatically prompt for stop loss after fills"
    )
    
    default_stop_loss_pct: float = Field(
        default=0.2,
        description="Default stop loss percentage (0.2 = 20%)",
        ge=0.01,
        le=1.0
    )
    
    # Market Data Settings
    use_delayed_data: bool = Field(
        default=False,
        description="Use delayed market data if real-time not available"
    )
    
    market_data_timeout: int = Field(
        default=10,
        description="Market data request timeout in seconds",
        ge=1,
        le=60
    )
    
    max_market_data_lines: int = Field(
        default=100,
        description="Maximum concurrent market data subscriptions",
        ge=1,
        le=100
    )
    
    # Rate Limiting
    max_requests_per_second: int = Field(
        default=50,
        description="Maximum API requests per second",
        ge=1,
        le=100
    )
    
    max_orders_per_second: int = Field(
        default=5,
        description="Maximum order placements per second",
        ge=1,
        le=20
    )
    
    enable_rate_limiting: bool = Field(
        default=True,
        description="Enable rate limiting for API calls"
    )
    
    # Connection Monitoring
    enable_connection_monitor: bool = Field(
        default=True,
        description="Enable automatic connection monitoring and recovery"
    )
    
    heartbeat_interval: int = Field(
        default=10,
        description="Connection heartbeat interval in seconds",
        ge=5,
        le=60
    )
    
    max_reconnect_attempts: int = Field(
        default=5,
        description="Maximum reconnection attempts",
        ge=1,
        le=20
    )
    
    reconnect_delay: int = Field(
        default=5,
        description="Base delay between reconnection attempts in seconds",
        ge=1,
        le=60
    )
    
    # Logging Settings
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level"
    )
    
    log_dir: Path = Field(
        default=Path("logs"),
        description="Directory for log files"
    )
    
    log_to_file: bool = Field(
        default=True,
        description="Enable logging to file"
    )
    
    log_rotation: str = Field(
        default="1 day",
        description="Log rotation schedule"
    )
    
    log_retention: int = Field(
        default=30,
        description="Log retention in days",
        ge=1,
        le=365
    )
    
    # Cache Settings
    cache_dir: Path = Field(
        default=Path("cache"),
        description="Directory for cache files"
    )
    
    cache_ttl: int = Field(
        default=300,
        description="Cache TTL in seconds",
        ge=0,
        le=3600
    )
    
    enable_cache: bool = Field(
        default=True,
        description="Enable caching"
    )
    
    # MCP Server Settings
    mcp_host: str = Field(
        default="127.0.0.1",
        description="MCP server host"
    )
    
    mcp_port: int = Field(
        default=5173,
        description="MCP server port",
        ge=1,
        le=65535
    )
    
    # Security Settings
    encrypt_sensitive_data: bool = Field(
        default=True,
        description="Encrypt sensitive data in logs and cache"
    )
    
    mask_account_numbers: bool = Field(
        default=True,
        description="Mask account numbers in logs"
    )
    
    # Performance Settings
    async_pool_size: int = Field(
        default=10,
        description="Async task pool size",
        ge=1,
        le=100
    )
    
    request_timeout: int = Field(
        default=30,
        description="Default request timeout in seconds",
        ge=5,
        le=300
    )
    
    # Development Settings
    debug_mode: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    
    dry_run: bool = Field(
        default=False,
        description="Dry run mode (no actual trades)"
    )
    
    # Validators
    @field_validator('tws_port')
    @classmethod
    def validate_tws_port(cls, v, info):
        """Validate TWS port matches trading mode."""
        if 'trading_mode' in info.data:
            if info.data['trading_mode'] == TradingMode.PAPER and v == 7497:
                raise ValueError("Paper trading should use port 7496, not 7497")
            elif info.data['trading_mode'] == TradingMode.LIVE and v == 7496:
                raise ValueError("Live trading should use port 7497, not 7496")
        return v
    
    @field_validator('tws_account')
    @classmethod
    def validate_account(cls, v):
        """Validate account ID format."""
        if v and not v.startswith(('DU', 'U')):
            raise ValueError(f"Invalid account ID format: {v}")
        return v
    
    @field_validator('log_dir', 'cache_dir', mode='after')
    @classmethod
    def create_directories(cls, v):
        """Create directories if they don't exist."""
        v = Path(v)
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @model_validator(mode='after')
    def validate_risk_settings(self):
        """Validate risk management settings."""
        if self.max_position_size > self.max_daily_loss * 2:
            raise ValueError("Max position size should not exceed 2x max daily loss")
        return self
    
    @model_validator(mode='after')
    def validate_trading_mode(self):
        """Validate trading mode settings."""
        if self.trading_mode == TradingMode.LIVE and self.dry_run:
            raise ValueError("Cannot use dry_run in LIVE trading mode")
        return self
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "allow",
        "use_enum_values": True
    }
    
    def to_dict(self, exclude_sensitive: bool = True) -> Dict[str, Any]:
        """
        Convert settings to dictionary.
        
        Args:
            exclude_sensitive: Exclude sensitive information
            
        Returns:
            Dict of settings
        """
        data = self.model_dump()
        
        if exclude_sensitive:
            # Remove sensitive fields
            sensitive_fields = ['tws_account', 'api_key', 'secret_key']
            for field in sensitive_fields:
                if field in data:
                    data[field] = "***MASKED***"
        
        return data
    
    def validate_for_trading(self) -> List[str]:
        """
        Validate settings are suitable for trading.
        
        Returns:
            List of validation warnings (empty if all good)
        """
        warnings = []
        
        if self.trading_mode == TradingMode.LIVE:
            if not self.require_confirmation:
                warnings.append("Live trading without confirmation is risky")
            if not self.auto_stop_loss:
                warnings.append("Auto stop-loss is disabled in live trading")
            if self.debug_mode:
                warnings.append("Debug mode is enabled in live trading")
        
        if self.max_position_size > 50000:
            warnings.append(f"Large max position size: ${self.max_position_size}")
        
        if self.max_daily_loss > 5000:
            warnings.append(f"Large max daily loss: ${self.max_daily_loss}")
        
        if not self.enable_rate_limiting:
            warnings.append("Rate limiting is disabled")
        
        if not self.enable_connection_monitor:
            warnings.append("Connection monitoring is disabled")
        
        return warnings
    
    def get_tws_connection_params(self) -> Dict[str, Any]:
        """Get TWS connection parameters."""
        return {
            "host": self.tws_host,
            "port": self.tws_port,
            "client_id": self.tws_client_id,
            "account": self.tws_account,
            "timeout": self.tws_timeout
        }
    
    def get_rate_limit_config(self) -> Dict[str, Any]:
        """Get rate limiting configuration."""
        return {
            "max_requests_per_second": self.max_requests_per_second,
            "max_orders_per_second": self.max_orders_per_second,
            "max_market_data_lines": self.max_market_data_lines,
            "enabled": self.enable_rate_limiting
        }
    
    def get_monitoring_config(self) -> Dict[str, Any]:
        """Get connection monitoring configuration."""
        return {
            "enabled": self.enable_connection_monitor,
            "heartbeat_interval": self.heartbeat_interval,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "reconnect_delay": self.reconnect_delay
        }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get or create settings instance.
    
    Returns:
        Settings instance
        
    Raises:
        ConfigurationError: If settings are invalid
    """
    global _settings
    
    if _settings is None:
        try:
            _settings = Settings()
            
            # Validate for trading
            warnings = _settings.validate_for_trading()
            if warnings:
                import logging
                logger = logging.getLogger(__name__)
                for warning in warnings:
                    logger.warning(f"Configuration warning: {warning}")
                    
        except Exception as e:
            raise ConfigurationError(f"Failed to load settings: {e}")
    
    return _settings


def reload_settings() -> Settings:
    """
    Reload settings from environment.
    
    Returns:
        New settings instance
    """
    global _settings
    _settings = None
    return get_settings()


def override_settings(**kwargs) -> Settings:
    """
    Override settings with provided values.
    
    Args:
        **kwargs: Settings to override
        
    Returns:
        Updated settings instance
    """
    global _settings
    
    if _settings is None:
        _settings = Settings(**kwargs)
    else:
        # Create new instance with overrides
        current_dict = _settings.model_dump()
        current_dict.update(kwargs)
        _settings = Settings(**current_dict)
    
    return _settings