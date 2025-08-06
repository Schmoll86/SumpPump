# src/config.py
"""
Configuration management for SumpPump MCP Server.
Loads environment variables and provides centralized config access.
"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class TWSConfig:
    """TWS connection configuration."""
    host: str = os.getenv("TWS_HOST", "127.0.0.1")
    port: int = int(os.getenv("TWS_PORT", "7497"))
    client_id: int = int(os.getenv("TWS_CLIENT_ID", "5"))  # Use 5 to avoid conflicts with paper trading
    account: Optional[str] = os.getenv("TWS_ACCOUNT")
    timeout: float = 30.0
    
    # TWS API Settings
    download_open_orders: bool = True
    readonly: bool = False
    
    # Market Data Settings
    use_delayed_data: bool = os.getenv("USE_DELAYED_DATA", "false").lower() == "true"
    market_data_timeout: int = int(os.getenv("MARKET_DATA_TIMEOUT", "30"))

@dataclass
class MCPConfig:
    """MCP server configuration."""
    server_name: str = os.getenv("MCP_SERVER_NAME", "sump-pump")
    server_port: int = int(os.getenv("MCP_SERVER_PORT", "8765"))
    log_level: str = os.getenv("MCP_LOG_LEVEL", "INFO")

@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_position_size_percent: float = float(os.getenv("MAX_POSITION_SIZE_PERCENT", "5.0"))
    default_stop_loss_percent: float = float(os.getenv("DEFAULT_STOP_LOSS_PERCENT", "10.0"))
    require_confirmation: bool = os.getenv("REQUIRE_CONFIRMATION", "true").lower() == "true"
    min_option_volume: int = int(os.getenv("MIN_OPTION_VOLUME", "10"))
    min_open_interest: int = int(os.getenv("MIN_OPEN_INTEREST", "50"))

@dataclass
class CacheConfig:
    """Cache configuration."""
    cache_type: str = os.getenv("CACHE_TYPE", "sqlite")
    cache_db_path: Path = Path(os.getenv("CACHE_DB_PATH", "./cache/session_data.db"))
    redis_url: Optional[str] = os.getenv("REDIS_URL")
    options_chain_cache_ttl: int = int(os.getenv("OPTIONS_CHAIN_CACHE_TTL", "300"))

@dataclass
class LogConfig:
    """Logging configuration."""
    log_file_path: Path = Path(os.getenv("LOG_FILE_PATH", "./logs/sump_pump.log"))
    log_rotation: str = os.getenv("LOG_ROTATION", "1 day")
    log_retention: str = os.getenv("LOG_RETENTION", "30 days")
    log_format: str = os.getenv("LOG_FORMAT", "json")
    debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"

@dataclass
class DataConfig:
    """Enhanced data and news configuration for all data feeds."""
    historical_data_duration: str = os.getenv("HISTORICAL_DATA_DURATION", "30 D")
    bar_size_setting: str = os.getenv("BAR_SIZE_SETTING", "1 hour")
    subscribe_to_news: bool = os.getenv("SUBSCRIBE_TO_NEWS", "true").lower() == "true"
    
    # Level 2 Depth Configuration
    use_level2_depth: bool = os.getenv("USE_LEVEL2_DEPTH", "true").lower() == "true"
    depth_provider: str = os.getenv("DEPTH_PROVIDER", "IEX")
    max_depth_levels: int = int(os.getenv("MAX_DEPTH_LEVELS", "10"))
    use_smart_depth: bool = os.getenv("USE_SMART_DEPTH", "true").lower() == "true"
    
    # Index Trading Configuration
    enable_index_trading: bool = os.getenv("ENABLE_INDEX_TRADING", "true").lower() == "true"
    index_exchanges: str = os.getenv("INDEX_EXCHANGES", "CBOE,CME,NASDAQ")
    
    # Cryptocurrency Configuration
    use_crypto_feed: bool = os.getenv("USE_CRYPTO_FEED", "false").lower() == "true"
    crypto_exchange: str = os.getenv("CRYPTO_EXCHANGE", "PAXOS")
    crypto_symbols: str = os.getenv("CRYPTO_SYMBOLS", "BTC,ETH,SOL")
    
    # Forex Configuration
    use_fx_feed: bool = os.getenv("USE_FX_FEED", "false").lower() == "true"
    fx_exchange: str = os.getenv("FX_EXCHANGE", "IDEALPRO")
    fx_pairs: str = os.getenv("FX_PAIRS", "EURUSD,GBPUSD,USDJPY")
    
    # Bond Configuration
    use_bond_feed: bool = os.getenv("USE_BOND_FEED", "false").lower() == "true"
    
    # News Configuration
    news_providers: str = os.getenv("NEWS_PROVIDERS", "dow_jones,reuters,benzinga,fly_on_the_wall")
    use_realtime_news: bool = os.getenv("USE_REALTIME_NEWS", "true").lower() == "true"
    news_bulletin_subscription: bool = os.getenv("NEWS_BULLETIN_SUBSCRIPTION", "true").lower() == "true"
    
    def __post_init__(self):
        """Initialize lists after dataclass init."""
        self.news_providers_list = self.news_providers.split(",") if self.news_providers else []
        self.index_exchanges_list = self.index_exchanges.split(",") if self.index_exchanges else []
        self.crypto_symbols_list = self.crypto_symbols.split(",") if self.crypto_symbols else []
        self.fx_pairs_list = self.fx_pairs.split(",") if self.fx_pairs else []

class Config:
    """Main configuration container."""
    def __init__(self):
        self.tws = TWSConfig()
        self.mcp = MCPConfig()
        self.risk = RiskConfig()
        self.cache = CacheConfig()
        self.log = LogConfig()
        self.data = DataConfig()
        
# Global config instance
config = Config()
