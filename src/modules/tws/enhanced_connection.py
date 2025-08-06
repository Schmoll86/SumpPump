"""
Enhanced TWS Connection Manager with integrated monitoring, rate limiting, and error handling.
Built on top of the existing connection with new infrastructure.
"""

import asyncio
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, date
from contextlib import asynccontextmanager
from decimal import Decimal
import math

from ib_async import IB, Contract, Option, Stock, MarketOrder, LimitOrder, ComboLeg, Order, util
from loguru import logger

# Import new core infrastructure
from src.core import (
    # Settings
    get_settings,
    Settings,
    
    # Exceptions
    TWSConnectionError,
    ConnectionLostError,
    ConnectionTimeoutError,
    MarketDataError,
    NoMarketDataError,
    MarketDataLimitError,
    OrderValidationError,
    RateLimitError,
    
    # Connection monitoring
    ConnectionMonitor,
    ConnectionState,
    with_connection_retry,
    
    # Rate limiting
    RateLimiter,
    RateLimitConfig,
    rate_limited,
    
    # Recovery
    get_recovery_strategy
)

from src.models import OptionContract, OptionRight, Greeks, Strategy
from src.modules.tws.connection import TWSConnection as BaseTWSConnection


class EnhancedTWSConnection(BaseTWSConnection):
    """
    Enhanced TWS connection with monitoring, rate limiting, and improved error handling.
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize enhanced TWS connection.
        
        Args:
            settings: Application settings (uses global if not provided)
        """
        super().__init__()
        
        # Load settings
        self.settings = settings or get_settings()
        
        # Initialize rate limiter
        if self.settings.enable_rate_limiting:
            rate_config = RateLimitConfig(
                max_requests_per_second=self.settings.max_requests_per_second,
                max_orders_per_second=self.settings.max_orders_per_second,
                max_market_data_lines=self.settings.max_market_data_lines
            )
            self.rate_limiter = RateLimiter(rate_config)
        else:
            self.rate_limiter = None
        
        # Initialize connection monitor
        if self.settings.enable_connection_monitor:
            self.connection_monitor = ConnectionMonitor(
                connection_factory=self._create_connection,
                heartbeat_interval=self.settings.heartbeat_interval,
                max_reconnect_attempts=self.settings.max_reconnect_attempts,
                reconnect_delay=self.settings.reconnect_delay
            )
            
            # Register callbacks
            self.connection_monitor.on_connected(self._on_monitor_connected)
            self.connection_monitor.on_disconnected(self._on_monitor_disconnected)
            self.connection_monitor.on_error(self._on_monitor_error)
        else:
            self.connection_monitor = None
        
        # Performance metrics
        self.metrics = {
            "requests_sent": 0,
            "requests_successful": 0,
            "requests_failed": 0,
            "total_latency_ms": 0,
            "connection_uptime": 0,
            "last_error": None
        }
    
    def _create_connection(self) -> IB:
        """
        Factory method to create IB connection instance.
        Used by connection monitor.
        """
        ib = IB()
        # Configure IB instance
        ib.RequestTimeout = self.settings.request_timeout
        return ib
    
    async def _on_monitor_connected(self):
        """Callback when monitor establishes connection."""
        logger.info("Connection monitor: Connected to TWS")
        self.connected = True
        self.ib = self.connection_monitor.connection
    
    async def _on_monitor_disconnected(self):
        """Callback when monitor detects disconnection."""
        logger.warning("Connection monitor: Disconnected from TWS")
        self.connected = False
    
    async def _on_monitor_error(self, error: Exception):
        """Callback when monitor encounters error."""
        logger.error(f"Connection monitor error: {error}")
        self.metrics["last_error"] = str(error)
    
    @with_connection_retry(max_retries=3)
    @rate_limited(operation_type="general")
    async def connect(self) -> bool:
        """
        Connect to TWS with monitoring and rate limiting.
        
        Returns:
            bool: True if connected successfully
        """
        try:
            if self.connection_monitor:
                # Use connection monitor
                await self.connection_monitor.start()
                self.ib = self.connection_monitor.connection
                self.connected = self.connection_monitor.is_connected
            else:
                # Direct connection (fallback)
                self.ib = self._create_connection()
                
                # Get connection parameters from settings
                params = self.settings.get_tws_connection_params()
                
                await self.ib.connectAsync(
                    host=params["host"],
                    port=params["port"],
                    clientId=params["client_id"],
                    timeout=params["timeout"]
                )
                
                self.connected = True
                
            logger.info(f"Connected to TWS at {self.settings.tws_host}:{self.settings.tws_port}")
            
            # Auto-detect account if not set
            if not self.settings.tws_account:
                accounts = self.ib.managedAccounts()
                if accounts:
                    self.settings.tws_account = accounts[0]
                    logger.info(f"Auto-detected account: {self.settings.tws_account}")
            
            return True
            
        except asyncio.TimeoutError:
            raise ConnectionTimeoutError(self.settings.tws_timeout)
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise TWSConnectionError(f"Failed to connect to TWS: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from TWS with cleanup."""
        try:
            # Clear rate limiter subscriptions
            if self.rate_limiter:
                await self.rate_limiter.clear_market_data_subscriptions()
            
            # Stop connection monitor
            if self.connection_monitor:
                await self.connection_monitor.stop()
            else:
                # Direct disconnect
                if self.ib and self.ib.isConnected():
                    self.ib.disconnect()
            
            self.connected = False
            self.ib = None
            logger.info("Disconnected from TWS")
            
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data", weight=10)
    async def get_options_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        strike_range_pct: float = 0.2,
        max_strikes: int = 10
    ) -> List[OptionContract]:
        """
        Get options chain with rate limiting and monitoring.
        
        Args:
            symbol: Underlying symbol
            expiry: Optional expiry date (YYYY-MM-DD)
            strike_range_pct: Strike range as percentage of spot
            max_strikes: Maximum strikes per expiry
            
        Returns:
            List of OptionContract objects
        """
        # Track metrics
        start_time = asyncio.get_event_loop().time()
        self.metrics["requests_sent"] += 1
        
        try:
            # Add to rate limiter if tracking subscriptions
            if self.rate_limiter:
                await self.rate_limiter.add_market_data_subscription(symbol)
            
            # Call parent implementation
            result = await super().get_options_chain(
                symbol, expiry, strike_range_pct, max_strikes
            )
            
            # Update metrics
            self.metrics["requests_successful"] += 1
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            self.metrics["total_latency_ms"] += latency
            
            return result
            
        except Exception as e:
            self.metrics["requests_failed"] += 1
            self.metrics["last_error"] = str(e)
            
            # Check if it's a rate limit error
            if "rate" in str(e).lower() and "limit" in str(e).lower():
                if self.rate_limiter:
                    self.rate_limiter.handle_rate_limit_error(str(e))
                raise RateLimitError(limit_type="market_data")
            
            # Check if it's a market data limit
            if "market data lines" in str(e).lower():
                raise MarketDataLimitError(
                    current=self._subscription_count,
                    limit=self.MAX_MARKET_DATA_LINES
                )
            
            raise
            
        finally:
            # Remove from rate limiter
            if self.rate_limiter:
                await self.rate_limiter.remove_market_data_subscription(symbol)
    
    @with_connection_retry()
    @rate_limited(operation_type="order", weight=5)
    async def place_combo_order(
        self,
        strategy: Strategy,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        confirmation_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Place combo order with enhanced error handling and rate limiting.
        
        Args:
            strategy: Strategy object with legs
            order_type: Order type (MKT or LMT)
            limit_price: Limit price for LMT orders
            confirmation_token: Required confirmation token
            
        Returns:
            Order execution details
        """
        # Validate confirmation in live mode
        if self.settings.trading_mode.value == "live" and self.settings.require_confirmation:
            if not confirmation_token:
                raise OrderValidationError(
                    "Confirmation token required for live trading",
                    field="confirmation_token"
                )
        
        # Track metrics
        start_time = asyncio.get_event_loop().time()
        self.metrics["requests_sent"] += 1
        
        try:
            # Call parent implementation
            result = await super().place_combo_order(
                strategy, order_type, limit_price, confirmation_token
            )
            
            # Update metrics
            self.metrics["requests_successful"] += 1
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            self.metrics["total_latency_ms"] += latency
            
            # Auto stop-loss prompt if enabled
            if self.settings.auto_stop_loss and result.get("status") == "filled":
                logger.info("Auto stop-loss enabled - prompting for stop loss order")
                # This would trigger a callback to the MCP server
                result["needs_stop_loss"] = True
                result["suggested_stop_loss"] = result.get("avg_fill_price", 0) * (1 - self.settings.default_stop_loss_pct)
            
            return result
            
        except Exception as e:
            self.metrics["requests_failed"] += 1
            self.metrics["last_error"] = str(e)
            
            # Enhanced error handling with recovery strategy
            recovery = get_recovery_strategy(e)
            
            if recovery["should_retry"] and recovery["max_retries"] > 0:
                logger.warning(f"Order failed, will retry: {e}")
                await asyncio.sleep(recovery["retry_delay"])
                # Retry logic would go here
            
            raise
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance and health metrics.
        
        Returns:
            Dictionary of metrics
        """
        metrics = self.metrics.copy()
        
        # Add connection monitor health
        if self.connection_monitor:
            metrics["connection_health"] = self.connection_monitor.get_health()
        
        # Add rate limiter stats
        if self.rate_limiter:
            metrics["rate_limiter"] = self.rate_limiter.get_stats()
        
        # Calculate averages
        if metrics["requests_successful"] > 0:
            metrics["avg_latency_ms"] = metrics["total_latency_ms"] / metrics["requests_successful"]
        else:
            metrics["avg_latency_ms"] = 0
        
        if metrics["requests_sent"] > 0:
            metrics["success_rate"] = metrics["requests_successful"] / metrics["requests_sent"]
        else:
            metrics["success_rate"] = 0
        
        return metrics
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check.
        
        Returns:
            Health status dictionary
        """
        health = {
            "connected": self.connected,
            "timestamp": datetime.now().isoformat(),
            "checks": {}
        }
        
        # Check connection
        if self.ib and self.ib.isConnected():
            health["checks"]["connection"] = "ok"
        else:
            health["checks"]["connection"] = "failed"
            health["connected"] = False
        
        # Check account
        try:
            if self.connected:
                account_values = await self.ib.accountSummaryAsync()
                if account_values:
                    health["checks"]["account"] = "ok"
                    health["account_id"] = self.settings.tws_account
                else:
                    health["checks"]["account"] = "no data"
        except Exception as e:
            health["checks"]["account"] = f"error: {e}"
        
        # Check market data
        try:
            if self.connected:
                # Try to get SPY quote as health check
                spy = Stock("SPY", "SMART", "USD")
                await self.ib.qualifyContractsAsync(spy)
                ticker = self.ib.reqMktData(spy, "", False, False)
                await asyncio.sleep(1)
                
                if ticker.last or ticker.close:
                    health["checks"]["market_data"] = "ok"
                else:
                    health["checks"]["market_data"] = "no data"
                
                self.ib.cancelMktData(spy)
        except Exception as e:
            health["checks"]["market_data"] = f"error: {e}"
        
        # Add metrics
        health["metrics"] = self.get_metrics()
        
        # Overall health
        health["healthy"] = all(
            v == "ok" for v in health["checks"].values()
        )
        
        return health


class TWSConnectionPool:
    """
    Connection pool for managing multiple TWS connections.
    Useful for parallel operations and load distribution.
    """
    
    def __init__(self, pool_size: int = 3, settings: Optional[Settings] = None):
        """
        Initialize connection pool.
        
        Args:
            pool_size: Number of connections in pool
            settings: Application settings
        """
        self.pool_size = pool_size
        self.settings = settings or get_settings()
        self.connections: List[EnhancedTWSConnection] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(pool_size)
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize all connections in pool."""
        if self._initialized:
            return
        
        logger.info(f"Initializing connection pool with {self.pool_size} connections")
        
        for i in range(self.pool_size):
            # Create connection with unique client ID
            settings_copy = self.settings.copy()
            settings_copy.tws_client_id = self.settings.tws_client_id + i
            
            conn = EnhancedTWSConnection(settings_copy)
            await conn.connect()
            
            self.connections.append(conn)
            await self.available.put(conn)
        
        self._initialized = True
        logger.info(f"Connection pool initialized with {self.pool_size} connections")
    
    @asynccontextmanager
    async def acquire(self):
        """
        Acquire a connection from pool.
        
        Usage:
            async with pool.acquire() as conn:
                # Use connection
        """
        await self.semaphore.acquire()
        conn = await self.available.get()
        
        try:
            # Ensure connection is healthy
            if not conn.connected:
                await conn.connect()
            
            yield conn
            
        finally:
            # Return to pool
            await self.available.put(conn)
            self.semaphore.release()
    
    async def close(self) -> None:
        """Close all connections in pool."""
        logger.info("Closing connection pool")
        
        for conn in self.connections:
            try:
                await conn.disconnect()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
        
        self.connections.clear()
        self._initialized = False
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of all connections."""
        health = {
            "pool_size": self.pool_size,
            "available": self.available.qsize(),
            "connections": []
        }
        
        for i, conn in enumerate(self.connections):
            conn_health = await conn.health_check()
            conn_health["id"] = i
            health["connections"].append(conn_health)
        
        health["healthy"] = all(
            c["healthy"] for c in health["connections"]
        )
        
        return health