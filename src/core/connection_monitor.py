"""
Connection monitoring and recovery system for TWS connection.
Provides automatic reconnection, health checks, and connection pooling.
"""

import asyncio
import logging
from typing import Optional, Callable, Any, Dict
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import time

from src.core.exceptions import (
    ConnectionLostError,
    ConnectionTimeoutError,
    TWSConnectionError,
    get_recovery_strategy
)


logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Connection state machine states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    SHUTDOWN = "shutdown"


@dataclass
class ConnectionHealth:
    """Connection health metrics."""
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_heartbeat: Optional[datetime] = None
    connection_time: Optional[datetime] = None
    reconnect_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    latency_ms: float = 0
    messages_sent: int = 0
    messages_received: int = 0
    
    @property
    def uptime(self) -> Optional[timedelta]:
        """Get connection uptime."""
        if self.connection_time:
            return datetime.now() - self.connection_time
        return None
    
    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        if self.state != ConnectionState.CONNECTED:
            return False
        if self.last_heartbeat:
            # Consider unhealthy if no heartbeat for 30 seconds
            return (datetime.now() - self.last_heartbeat).seconds < 30
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "state": self.state.value,
            "healthy": self.is_healthy,
            "uptime": str(self.uptime) if self.uptime else None,
            "reconnect_count": self.reconnect_count,
            "error_count": self.error_count,
            "latency_ms": self.latency_ms,
            "last_error": self.last_error
        }


class ConnectionMonitor:
    """
    Monitors TWS connection health and handles automatic recovery.
    """
    
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        heartbeat_interval: int = 10,
        max_reconnect_attempts: int = 5,
        reconnect_delay: int = 5
    ):
        """
        Initialize connection monitor.
        
        Args:
            connection_factory: Callable that creates/returns connection instance
            heartbeat_interval: Seconds between heartbeat checks
            max_reconnect_attempts: Maximum reconnection attempts
            reconnect_delay: Base delay between reconnection attempts (exponential backoff)
        """
        self.connection_factory = connection_factory
        self.heartbeat_interval = heartbeat_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        
        self.health = ConnectionHealth()
        self._connection: Optional[Any] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_lock = asyncio.Lock()
        
        # Callbacks for state changes
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
    
    async def start(self) -> None:
        """Start connection monitoring."""
        logger.info("Starting connection monitor")
        self.health.state = ConnectionState.CONNECTING
        
        try:
            # Initial connection
            await self._connect()
            
            # Start monitoring tasks
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
        except Exception as e:
            logger.error(f"Failed to start connection monitor: {e}")
            self.health.state = ConnectionState.ERROR
            self.health.last_error = str(e)
            raise
    
    async def stop(self) -> None:
        """Stop connection monitoring and disconnect."""
        logger.info("Stopping connection monitor")
        self.health.state = ConnectionState.SHUTDOWN
        self._shutdown_event.set()
        
        # Cancel monitoring tasks
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect
        await self._disconnect()
    
    async def _connect(self) -> None:
        """Establish connection."""
        try:
            logger.info("Establishing connection...")
            self._connection = self.connection_factory()
            
            # If connection has async connect method, await it
            if hasattr(self._connection, 'connect'):
                if asyncio.iscoroutinefunction(self._connection.connect):
                    await self._connection.connect()
                else:
                    self._connection.connect()
            
            # Update health
            self.health.state = ConnectionState.CONNECTED
            self.health.connection_time = datetime.now()
            self.health.last_heartbeat = datetime.now()
            
            logger.info("Connection established successfully")
            
            # Call connected callback
            if self._on_connected:
                await self._call_callback(self._on_connected)
                
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.health.state = ConnectionState.ERROR
            self.health.last_error = str(e)
            self.health.error_count += 1
            raise TWSConnectionError(f"Failed to connect: {e}")
    
    async def _disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._connection:
            try:
                if hasattr(self._connection, 'disconnect'):
                    if asyncio.iscoroutinefunction(self._connection.disconnect):
                        await self._connection.disconnect()
                    else:
                        self._connection.disconnect()
                        
                logger.info("Disconnected successfully")
                
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self._connection = None
                self.health.state = ConnectionState.DISCONNECTED
                
                # Call disconnected callback
                if self._on_disconnected:
                    await self._call_callback(self._on_disconnected)
    
    async def _reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.
        
        Returns:
            bool: True if reconnection successful
        """
        async with self._reconnect_lock:
            if self.health.state == ConnectionState.CONNECTED:
                return True
            
            self.health.state = ConnectionState.RECONNECTING
            attempt = 0
            
            while attempt < self.max_reconnect_attempts:
                attempt += 1
                delay = self.reconnect_delay * (2 ** (attempt - 1))  # Exponential backoff
                
                logger.info(f"Reconnection attempt {attempt}/{self.max_reconnect_attempts} (delay: {delay}s)")
                
                try:
                    # Disconnect first if needed
                    if self._connection:
                        await self._disconnect()
                    
                    # Wait before reconnecting
                    await asyncio.sleep(delay)
                    
                    # Attempt connection
                    await self._connect()
                    
                    # Success
                    self.health.reconnect_count += 1
                    logger.info(f"Reconnection successful after {attempt} attempts")
                    return True
                    
                except Exception as e:
                    logger.warning(f"Reconnection attempt {attempt} failed: {e}")
                    self.health.last_error = str(e)
                    
                    if attempt >= self.max_reconnect_attempts:
                        logger.error(f"Max reconnection attempts reached ({self.max_reconnect_attempts})")
                        self.health.state = ConnectionState.ERROR
                        
                        # Call error callback
                        if self._on_error:
                            await self._call_callback(self._on_error, ConnectionLostError())
                        
                        return False
            
            return False
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info("Connection monitor loop started")
        
        while not self._shutdown_event.is_set():
            try:
                # Check connection health
                if not await self._check_connection():
                    logger.warning("Connection check failed, attempting recovery")
                    await self._reconnect()
                
                # Wait before next check
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                logger.info("Monitor loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                self.health.error_count += 1
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to check connection."""
        logger.info("Heartbeat loop started")
        
        while not self._shutdown_event.is_set():
            try:
                if self.health.state == ConnectionState.CONNECTED and self._connection:
                    # Send heartbeat (ping)
                    start_time = time.time()
                    
                    if hasattr(self._connection, 'ping'):
                        if asyncio.iscoroutinefunction(self._connection.ping):
                            await self._connection.ping()
                        else:
                            self._connection.ping()
                    elif hasattr(self._connection, 'isConnected'):
                        # For ib_async connections
                        is_connected = self._connection.isConnected()
                        if not is_connected:
                            raise ConnectionLostError()
                    
                    # Update latency
                    self.health.latency_ms = (time.time() - start_time) * 1000
                    self.health.last_heartbeat = datetime.now()
                    
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                break
            except ConnectionLostError:
                logger.warning("Heartbeat detected connection loss")
                self.health.state = ConnectionState.DISCONNECTED
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                self.health.error_count += 1
    
    async def _check_connection(self) -> bool:
        """
        Check if connection is alive and healthy.
        
        Returns:
            bool: True if connection is healthy
        """
        if not self._connection:
            return False
        
        if self.health.state != ConnectionState.CONNECTED:
            return False
        
        # Check if connection object has isConnected method
        if hasattr(self._connection, 'isConnected'):
            try:
                connected = self._connection.isConnected()
                if not connected:
                    logger.warning("Connection check: not connected")
                    self.health.state = ConnectionState.DISCONNECTED
                    return False
            except Exception as e:
                logger.error(f"Error checking connection: {e}")
                return False
        
        # Check heartbeat timeout
        if self.health.last_heartbeat:
            time_since_heartbeat = (datetime.now() - self.health.last_heartbeat).seconds
            if time_since_heartbeat > self.heartbeat_interval * 3:
                logger.warning(f"No heartbeat for {time_since_heartbeat} seconds")
                return False
        
        return True
    
    async def _call_callback(self, callback: Callable, *args) -> None:
        """Call callback function safely."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Error in callback: {e}")
    
    def on_connected(self, callback: Callable) -> None:
        """Register callback for connection established."""
        self._on_connected = callback
    
    def on_disconnected(self, callback: Callable) -> None:
        """Register callback for connection lost."""
        self._on_disconnected = callback
    
    def on_error(self, callback: Callable) -> None:
        """Register callback for connection errors."""
        self._on_error = callback
    
    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.health.state == ConnectionState.CONNECTED
    
    @property
    def connection(self) -> Optional[Any]:
        """Get current connection instance."""
        return self._connection if self.is_connected else None
    
    def get_health(self) -> Dict[str, Any]:
        """Get connection health status."""
        return self.health.to_dict()


# Decorator for automatic retry with connection monitoring
def with_connection_retry(max_retries: int = 3, delay: int = 1):
    """
    Decorator for methods that need connection with automatic retry.
    
    Usage:
        @with_connection_retry(max_retries=3)
        async def fetch_data(self):
            # Method that requires connection
    """
    def decorator(func):
        async def wrapper(self, *args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    # Check if self has connection monitor
                    if hasattr(self, 'connection_monitor'):
                        if not self.connection_monitor.is_connected:
                            logger.warning(f"Connection not available, attempting reconnect")
                            await self.connection_monitor._reconnect()
                    
                    # Try the function
                    return await func(self, *args, **kwargs)
                    
                except (ConnectionLostError, TWSConnectionError) as e:
                    last_error = e
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff
                    
                except Exception as e:
                    # Non-connection errors, don't retry
                    raise
            
            # All retries failed
            raise last_error or TWSConnectionError(f"Failed after {max_retries} attempts")
        
        return wrapper
    return decorator