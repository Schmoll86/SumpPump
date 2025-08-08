"""
TWS Connection Manager using ib_async.
Handles connection, reconnection, and market data subscriptions.
"""

import asyncio
import time
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, date
from contextlib import asynccontextmanager
from decimal import Decimal

# Apply nest_asyncio to allow nested event loops
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # Will log warning below

from ib_async import IB, Contract, Option, Stock, MarketOrder, LimitOrder, ComboLeg, Order, util
from loguru import logger
import math

# Log nest_asyncio status after logger is imported
try:
    import nest_asyncio
    logger.info("nest_asyncio applied - nested event loops enabled")
except ImportError:
    logger.warning("nest_asyncio not installed - install with: pip install nest-asyncio")

from src.config import config
from src.models import OptionContract, OptionRight, Greeks, Strategy


async def _async_safe_sleep(duration: float):
    """Async sleep - always use asyncio.sleep in async context."""
    await asyncio.sleep(duration)


class TWSConnectionError(Exception):
    """Custom exception for TWS connection issues."""
    pass


class TWSConnection:
    """
    Manages TWS connection with automatic reconnection and error handling.
    Uses ib_async for async operations.
    """
    
    # IBKR market data limits
    MAX_MARKET_DATA_LINES = 95  # Keep under 100 to be safe
    
    def __init__(self):
        """Initialize TWS connection manager."""
        self.ib: Optional[IB] = None
        self.connected: bool = False
        self.reconnect_attempts: int = 0
        self.max_reconnect_attempts: int = 5
        self._active_subscriptions: Set[Contract] = set()
        self._subscription_count: int = 0
        self._monitor_task: Optional[asyncio.Task] = None
        self._current_client_id: Optional[int] = None
        
    async def _find_available_client_id(self) -> int:
        """
        Find an available client ID by trying different IDs.
        
        Returns:
            Available client ID
        """
        # Start with configured ID or 5 as default
        base_id = config.tws.client_id if config.tws.client_id else 5
        
        # Try base ID and then increments
        for offset in range(20):  # Try up to 20 different IDs
            test_id = base_id + offset
            
            try:
                test_ib = IB()
                # Try quick connect with short timeout
                await asyncio.wait_for(
                    test_ib.connectAsync(
                        host=config.tws.host,
                        port=config.tws.port,
                        clientId=test_id,
                        timeout=5
                    ),
                    timeout=6
                )
                
                # Success! This ID works
                test_ib.disconnect()
                logger.info(f"Found available client ID: {test_id}")
                return test_id
                
            except Exception as e:
                # This ID didn't work, try next
                if test_ib and test_ib.isConnected():
                    test_ib.disconnect()
                    
                error_str = str(e)
                if "already in use" in error_str:
                    logger.debug(f"Client ID {test_id} already in use, trying next...")
                    continue
                elif "TimeoutError" in error_str:
                    # TWS not responding at all
                    logger.error("TWS not responding to connection attempts")
                    raise TWSConnectionError("TWS not responding - check if API is enabled")
        
        raise TWSConnectionError("No available client IDs found (tried 20)")
    
    async def connect(self) -> None:
        """
        Establish connection to TWS with dynamic client ID allocation.
        
        Raises:
            TWSConnectionError: If connection fails after max attempts
        """
        if not self.ib:
            logger.info("Creating new IB instance in async context")
            self.ib = IB()
        
        # Find available client ID if not already set
        if self._current_client_id is None:
            self._current_client_id = await self._find_available_client_id()
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.ib.connectAsync(
                    host=config.tws.host,
                    port=config.tws.port,
                    clientId=self._current_client_id,
                    timeout=config.tws.timeout,
                    readonly=config.tws.readonly,
                    account=config.tws.account
                )
                
                self.connected = True
                self.reconnect_attempts = 0
                
                # Configure market data
                if not config.tws.use_delayed_data:
                    self.ib.reqMarketDataType(1)  # Live data
                else:
                    self.ib.reqMarketDataType(3)  # Delayed data
                    
                logger.info(f"Connected to TWS at {config.tws.host}:{config.tws.port} with client ID {self._current_client_id}")
                
                # Start connection monitor if not already running
                if not self._monitor_task or self._monitor_task.done():
                    self._monitor_task = asyncio.create_task(self._monitor_connection())
                    logger.info("Started connection monitor")
                
                return
                
            except Exception as e:
                self.reconnect_attempts += 1
                logger.error(f"Connection attempt {self.reconnect_attempts} failed: {e}")
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    await _async_safe_sleep(2 ** self.reconnect_attempts)  # Exponential backoff
                    
        raise TWSConnectionError(f"Failed to connect after {self.max_reconnect_attempts} attempts")
    
    async def _monitor_connection(self) -> None:
        """
        Monitor connection health and auto-reconnect if needed.
        Runs as background task.
        """
        logger.info("Connection monitor started")
        
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                if not self.ib or not self.ib.isConnected():
                    logger.warning("Connection lost, attempting reconnect...")
                    self.connected = False
                    
                    # Try to reconnect with new client ID if needed
                    self._current_client_id = None  # Force new ID search
                    self.reconnect_attempts = 0
                    
                    try:
                        await self.connect()
                        logger.info("Successfully reconnected to TWS")
                    except Exception as e:
                        logger.error(f"Reconnection failed: {e}")
                        
            except asyncio.CancelledError:
                logger.info("Connection monitor stopped")
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
        
    async def disconnect(self) -> None:
        """Disconnect from TWS and stop monitoring."""
        # Stop monitor task
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.ib and self.connected:
            # Cancel all active subscriptions
            for contract in self._active_subscriptions:
                self.ib.cancelMktData(contract)
            self._active_subscriptions.clear()
            
            self.ib.disconnect()
            self.connected = False
            self._current_client_id = None
            logger.info("Disconnected from TWS")
            
    async def ensure_connected(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        if not self.connected or (self.ib and not self.ib.isConnected()):
            logger.warning("Connection lost or not established, attempting to connect...")
            
            # Check if we're in an event loop already
            try:
                loop = asyncio.get_running_loop()
                logger.debug(f"Running in existing event loop: {id(loop)}")
            except RuntimeError:
                logger.error("No running event loop - cannot connect in sync context")
                raise TWSConnectionError("Must call ensure_connected from async context")
            
            await self.connect()
            
    @asynccontextmanager
    async def session(self):
        """Context manager for TWS connection."""
        try:
            await self.connect()
            yield self
        finally:
            await self.disconnect()
    
    def create_stock_contract(self, symbol: str, exchange: str = 'SMART') -> Stock:
        """
        Create a stock contract.
        
        Args:
            symbol: Stock symbol
            exchange: Exchange (default SMART for routing)
        
        Returns:
            Stock contract object
        """
        return Stock(symbol, exchange, 'USD')
    
    def create_option_contract(
        self, 
        symbol: str, 
        expiry: str, 
        strike: float, 
        right: str,
        exchange: str = 'SMART'
    ) -> Option:
        """
        Create an option contract.
        
        Args:
            symbol: Underlying symbol
            expiry: Expiration date (YYYYMMDD format)
            strike: Strike price
            right: 'C' for call, 'P' for put
            exchange: Exchange (default SMART)
        
        Returns:
            Option contract object
        """
        # Create option with explicit multiplier for standard options
        option = Option(symbol, expiry, strike, right, exchange, currency='USD')
        option.multiplier = '100'  # Standard option multiplier
        return option
    
    async def get_options_chain(
        self, 
        symbol: str, 
        expiry: Optional[str] = None,
        max_strikes: int = 5,
        strike_range_pct: float = 0.10
    ) -> List[OptionContract]:
        """
        Fetch full options chain for a symbol with Greeks.
        
        Args:
            symbol: Stock symbol
            expiry: Optional expiration date filter (YYYY-MM-DD)
        
        Returns:
            List of OptionContract objects with Greeks
        """
        # Track resources for cleanup
        stock_ticker = None
        subscribed_contracts = set()
        
        try:
            await self.ensure_connected()
            
            # Get underlying stock price first
            stock = self.create_stock_contract(symbol)
            await self.ib.qualifyContractsAsync(stock)
            
            # Get stock ticker for current price
            stock_ticker = self.ib.reqMktData(stock, '', False, False)
            self._subscription_count = 1  # Start counting with stock
            await asyncio.sleep(2)  # Wait for data
            
            underlying_price = stock_ticker.marketPrice()
            if not underlying_price or underlying_price <= 0:
                underlying_price = stock_ticker.last or stock_ticker.close
                
            logger.info(f"Underlying {symbol} price: {underlying_price}")
            
            # Get option chain parameters
            chains = await self.ib.reqSecDefOptParamsAsync(
                stock.symbol, '', stock.secType, stock.conId
            )
            
            if not chains:
                logger.warning(f"No option chains found for {symbol}")
                return []
            
            options_list = []
            
            # Collect all expiries first
            all_expiries = set()
            for chain in chains:
                all_expiries.update(chain.expirations)
            sorted_expiries = sorted(all_expiries)
            
            # Filter by expiry if provided
            target_expiries = []
            if expiry:
                # Convert YYYY-MM-DD to YYYYMMDD
                expiry_date = datetime.strptime(expiry, '%Y-%m-%d').strftime('%Y%m%d')
                if expiry_date in sorted_expiries:
                    target_expiries = [expiry_date]
                else:
                    logger.warning(f"Requested expiry {expiry} not found in available expiries")
                    target_expiries = sorted_expiries[:1]  # Use closest expiry
            else:
                # Get next expiry only (to stay within limits)
                target_expiries = sorted_expiries[:1]  # Just the nearest expiry
            
            for expiry_str in target_expiries:
                # Find the chain that contains this expiry
                chain_to_use = None
                for chain in chains:
                    if expiry_str in chain.expirations:
                        chain_to_use = chain
                        break
                
                if not chain_to_use:
                    continue
                        
                # Get strikes around current price (using parameters)
                min_strike = underlying_price * (1 - strike_range_pct)
                max_strike = underlying_price * (1 + strike_range_pct)
                
                relevant_strikes = [s for s in chain_to_use.strikes if min_strike <= s <= max_strike]
                
                # Sort by distance from current price and limit
                relevant_strikes.sort(key=lambda x: abs(x - underlying_price))
                relevant_strikes = relevant_strikes[:max_strikes]  # Limit number of strikes
                    
                logger.info(f"Processing {len(relevant_strikes)} strikes for {expiry_str}")
                
                for strike in relevant_strikes:
                    # Check if we're approaching the limit
                    if self._subscription_count >= self.MAX_MARKET_DATA_LINES - 2:
                        logger.warning(f"Reached market data limit ({self._subscription_count}/{self.MAX_MARKET_DATA_LINES})")
                        break
                    
                    for right in ['C', 'P']:
                        try:
                            # Create option contract
                            option = self.create_option_contract(
                                symbol, expiry_str, strike, right, chain_to_use.exchange
                            )
                            
                            # Qualify contract
                            qualified = await self.ib.qualifyContractsAsync(option)
                            if not qualified:
                                logger.debug(f"Could not qualify {symbol} {expiry_str} {strike} {right}")
                                continue
                            option = qualified[0]  # Use the qualified contract
                            
                            # Request market data with Greek computation
                            ticker = self.ib.reqMktData(
                                option, 
                                '106',  # Request Greeks explicitly (13=model option, 106=option Greeks)
                                False, 
                                False
                            )
                            subscribed_contracts.add(option)  # Track for cleanup
                            self._active_subscriptions.add(option)
                            self._subscription_count += 1
                            
                            # Wait longer for Greeks data to populate with retry
                            max_wait = 3  # Max 3 seconds total
                            wait_interval = 0.5
                            waited = 0
                            
                            while waited < max_wait:
                                await asyncio.sleep(wait_interval)
                                waited += wait_interval
                                
                                # Check if Greeks have arrived
                                if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks:
                                    logger.debug(f"Greeks received after {waited}s for {symbol} {strike} {right}")
                                    break
                                elif ticker.bid is not None and ticker.ask is not None:
                                    # We have prices but no Greeks yet
                                    if waited >= 2.0:  # After 2 seconds, try to request IV calculation
                                        mid_price = (ticker.bid + ticker.ask) / 2
                                        self.ib.reqCalculateImpliedVolatility(option, mid_price, underlying_price)
                                        logger.debug(f"Requested IV calculation for {symbol} {strike} {right}")
                                
                            # Extract data
                            if ticker.bid is not None and ticker.ask is not None:
                                # Parse expiry
                                expiry_dt = datetime.strptime(expiry_str, '%Y%m%d')
                                
                                # Create Greeks object (check for attributes)
                                greeks = Greeks(
                                    delta=0.0,
                                    gamma=0.0,
                                    theta=0.0,
                                    vega=0.0,
                                    rho=None
                                )
                                
                                if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks:
                                    mg = ticker.modelGreeks
                                    if hasattr(mg, 'delta'): greeks.delta = mg.delta or 0.0
                                    if hasattr(mg, 'gamma'): greeks.gamma = mg.gamma or 0.0
                                    if hasattr(mg, 'theta'): greeks.theta = mg.theta or 0.0
                                    if hasattr(mg, 'vega'): greeks.vega = mg.vega or 0.0
                                    if hasattr(mg, 'rho'): greeks.rho = mg.rho
                                
                                # Create OptionContract (check attributes)
                                opt_contract = OptionContract(
                                    symbol=symbol,
                                    strike=strike,
                                    expiry=expiry_dt,
                                    right=OptionRight.CALL if right == 'C' else OptionRight.PUT,
                                    bid=float(ticker.bid) if ticker.bid is not None else 0.0,
                                    ask=float(ticker.ask) if ticker.ask is not None else 0.0,
                                    last=float(ticker.last) if hasattr(ticker, 'last') and ticker.last is not None else 0.0,
                                    volume=int(ticker.volume) if hasattr(ticker, 'volume') and ticker.volume and not math.isnan(ticker.volume) else 0,
                                    open_interest=0,  # Not always available from ticker
                                    iv=mg.impliedVol if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks and hasattr(ticker.modelGreeks, 'impliedVol') else 0.0,
                                    greeks=greeks,
                                    underlying_price=underlying_price
                                )
                                
                                options_list.append(opt_contract)
                                logger.debug(f"Added option: {symbol} {expiry_str} {strike} {right}")
                                
                        except Exception as e:
                            logger.warning(f"Error fetching option {symbol} {expiry_str} {strike} {right}: {e}")
                            continue
            
            logger.info(f"Fetched {len(options_list)} option contracts for {symbol}")
            return options_list
            
        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            raise TWSConnectionError(f"Failed to fetch options chain for {symbol}: {e}")
            
        finally:
            # ALWAYS clean up market data subscriptions
            logger.debug(f"Cleaning up {len(subscribed_contracts)} market data subscriptions")
            
            # Cancel all option subscriptions
            for contract in subscribed_contracts:
                try:
                    self.ib.cancelMktData(contract)
                    if contract in self._active_subscriptions:
                        self._active_subscriptions.remove(contract)
                except Exception as e:
                    logger.debug(f"Error canceling market data: {e}")
            
            # Cancel stock ticker if it exists
            if stock_ticker:
                try:
                    self.ib.cancelMktData(stock)
                except:
                    pass
            
            # Update subscription count
            self._subscription_count = max(0, self._subscription_count - len(subscribed_contracts) - 1)
            
            logger.debug(f"Cleanup complete. Active subscriptions: {self._subscription_count}")
    
    async def subscribe_to_market_data(self, contract: Contract) -> Any:
        """
        Subscribe to real-time market data for a contract.
        
        Args:
            contract: IB contract object
        
        Returns:
            Ticker object for real-time updates
        """
        await self.ensure_connected()
        
        ticker = self.ib.reqMktData(contract, '', False, False)
        self._active_subscriptions.add(contract)
        
        return ticker
    
    def get_account_info_sync(self) -> Dict[str, Any]:
        """
        Get account information including balances and positions (synchronous version).
        
        Returns:
            Dictionary with account details
        """
        try:
            if not self.connected or not self.ib.isConnected():
                logger.error("TWS not connected - connection required before calling get_account_info")
                return {
                    'error': 'TWS not connected',
                    'account_id': config.tws.account,
                    'net_liquidation': 0.0,
                    'available_funds': 0.0,
                    'buying_power': 0.0,
                    'positions': [],
                    'open_orders': []
                }
            
            logger.info("Fetching account information from TWS")
            
            # Auto-detect account ID if not configured
            account_id = config.tws.account
            if not account_id or account_id.strip() == "" or "#" in account_id:
                logger.info("No valid account ID configured, attempting to detect...")
                managed_accounts = self.ib.managedAccounts()
                logger.info(f"Available accounts: {managed_accounts}")
                if managed_accounts:
                    account_id = managed_accounts[0]  # Use first available account
                    logger.info(f"Auto-detected account ID: {account_id}")
                else:
                    logger.error("No managed accounts found")
                    account_id = ""
            
            # Get account summary
            self.ib.reqAccountSummary()
            time.sleep(2)  # Wait for data synchronously
            account_values = self.ib.accountSummary()
            logger.info(f"Retrieved {len(account_values)} account values")
            
            # Get positions
            self.ib.reqPositions()
            time.sleep(1)  # Wait for data synchronously
            positions = self.ib.positions()
            logger.info(f"Retrieved {len(positions)} positions")
            
            # Get open orders (use openTrades to get both order and contract info)
            self.ib.reqOpenOrders()
            time.sleep(1)  # Wait for data synchronously
            open_trades = self.ib.openTrades()
            logger.info(f"Retrieved {len(open_trades)} open orders")
            
            # Initialize account info with detected account ID
            account_info = {
                'account_id': account_id or config.tws.account,
                'net_liquidation': 0.0,
                'available_funds': 0.0,
                'buying_power': 0.0,
                'positions': [],
                'open_orders': []
            }
            
            # Parse account values (filter by USD currency)
            for av in account_values:
                logger.debug(f"Account value: {av.tag} = {av.value} ({av.currency})")
                if av.currency == 'USD':  # Only process USD values
                    if av.tag == 'NetLiquidation':
                        account_info['net_liquidation'] = float(av.value)
                    elif av.tag == 'AvailableFunds':
                        account_info['available_funds'] = float(av.value)
                    elif av.tag == 'BuyingPower':
                        account_info['buying_power'] = float(av.value)
            
            # Parse positions
            for pos in positions:
                account_info['positions'].append({
                    'symbol': pos.contract.symbol,
                    'position': pos.position,
                    'avg_cost': pos.avgCost,
                    'contract': str(pos.contract)
                })
            
            # Parse open orders (now using Trade objects)
            for trade in open_trades:
                account_info['open_orders'].append({
                    'order_id': trade.order.orderId,
                    'symbol': trade.contract.symbol,
                    'action': trade.order.action,
                    'quantity': trade.order.totalQuantity,
                    'order_type': trade.order.orderType,
                    'status': trade.orderStatus.status
                })
            
            logger.info(f"Account info: NetLiq=${account_info['net_liquidation']:,.2f}, "
                       f"Available=${account_info['available_funds']:,.2f}, "
                       f"BuyingPower=${account_info['buying_power']:,.2f}")
            
            return account_info
            
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {
                'error': str(e),
                'account_id': config.tws.account,
                'net_liquidation': 0.0,
                'available_funds': 0.0,
                'buying_power': 0.0,
                'positions': [],
                'open_orders': []
            }

    async def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information including balances and positions.
        
        Returns:
            Dictionary with account details
        """
        try:
            # Ensure we're connected - now with proper async handling
            if not self.connected or not self.ib.isConnected():
                logger.warning("Connection lost, attempting to reconnect...")
                try:
                    await self.connect()
                except RuntimeError:
                    # If in nested event loop, return error
                    logger.error("Cannot reconnect in nested event loop context")
                    return {
                        'error': 'TWS connection lost and cannot reconnect in current context',
                        'account_id': config.tws.account,
                        'net_liquidation': 0.0,
                        'available_funds': 0.0,
                        'buying_power': 0.0,
                        'positions': [],
                        'open_orders': []
                    }
            
            if not self.ib.isConnected():
                logger.error("TWS not connected when requesting account info")
                return {
                    'error': 'TWS not connected',
                    'account_id': config.tws.account,
                    'net_liquidation': 0.0,
                    'available_funds': 0.0,
                    'buying_power': 0.0,
                    'positions': [],
                    'open_orders': []
                }
            
            logger.info("Fetching account information from TWS")
            
            # Auto-detect account ID if not configured
            account_id = config.tws.account
            if not account_id or account_id.strip() == "" or "#" in account_id:
                logger.info("No valid account ID configured, attempting to detect...")
                try:
                    managed_accounts = self.ib.managedAccounts()
                    logger.info(f"Available accounts: {managed_accounts}")
                    if managed_accounts:
                        account_id = managed_accounts[0]  # Use first available account
                        logger.info(f"Auto-detected account ID: {account_id}")
                    else:
                        logger.error("No managed accounts found")
                        account_id = ""
                except Exception as e:
                    logger.warning(f"Could not auto-detect account in async context: {e}")
                    account_id = "DU0000000"  # Fallback to demo account pattern
            
            # Get account summary - using proper async/await pattern
            logger.debug("Requesting account summary...")
            self.ib.reqAccountSummary()
            
            # Wait for account data using safe sleep
            logger.debug("Waiting for account data...")
            await _async_safe_sleep(2)
            logger.debug("Getting account summary...")
            account_values = self.ib.accountSummary()
            logger.info(f"Retrieved {len(account_values)} account values")
            
            # Get positions
            self.ib.reqPositions()
            await _async_safe_sleep(1)  # Wait for position data
            positions = self.ib.positions()
            logger.info(f"Retrieved {len(positions)} positions")
            
            # Get open orders (use openTrades to get both order and contract info)
            self.ib.reqOpenOrders()
            await _async_safe_sleep(1)  # Wait for order data
            open_trades = self.ib.openTrades()
            logger.info(f"Retrieved {len(open_trades)} open orders")
            
            # Initialize account info with detected account ID
            account_info = {
                'account_id': account_id or config.tws.account,
                'net_liquidation': 0.0,
                'available_funds': 0.0,
                'buying_power': 0.0,
                'positions': [],
                'open_orders': []
            }
            
            # Parse account values (filter by USD currency)
            for av in account_values:
                logger.debug(f"Account value: {av.tag} = {av.value} ({av.currency})")
                if av.currency == 'USD':  # Only process USD values
                    if av.tag == 'NetLiquidation':
                        account_info['net_liquidation'] = float(av.value)
                    elif av.tag == 'AvailableFunds':
                        account_info['available_funds'] = float(av.value)
                    elif av.tag == 'BuyingPower':
                        account_info['buying_power'] = float(av.value)
            
            # Parse positions
            for pos in positions:
                account_info['positions'].append({
                    'symbol': pos.contract.symbol,
                    'position': pos.position,
                    'avg_cost': pos.avgCost,
                    'contract': str(pos.contract)
                })
            
            # Parse open orders (now using Trade objects)
            for trade in open_trades:
                account_info['open_orders'].append({
                    'order_id': trade.order.orderId,
                    'symbol': trade.contract.symbol,
                    'action': trade.order.action,
                    'quantity': trade.order.totalQuantity,
                    'order_type': trade.order.orderType,
                    'status': trade.orderStatus.status
                })
            
            logger.info(f"Account info: NetLiq=${account_info['net_liquidation']:,.2f}, "
                       f"Available=${account_info['available_funds']:,.2f}, "
                       f"BuyingPower=${account_info['buying_power']:,.2f}")
            
            return account_info
            
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {
                'error': str(e),
                'account_id': config.tws.account,
                'net_liquidation': 0.0,
                'available_funds': 0.0,
                'buying_power': 0.0,
                'positions': [],
                'open_orders': []
            }
    
    async def place_stock_order(self, symbol: str, quantity: int, action: str = 'BUY', order_type: str = 'LMT', limit_price: Optional[float] = None) -> Dict[str, Any]:
        """
        Place a stock order.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            action: 'BUY' or 'SELL'
            order_type: 'MKT' for market, 'LMT' for limit
            limit_price: Limit price (required for limit orders)
        
        Returns:
            Order placement result
        """
        try:
            await self.ensure_connected()
            
            # Create stock contract
            stock = self.create_stock_contract(symbol)
            qualified = await self.ib.qualifyContractsAsync(stock)
            if qualified:
                stock = qualified[0]
            
            # Create order
            if order_type == 'MKT':
                order = MarketOrder(action, quantity)
            elif order_type == 'LMT':
                if limit_price is None:
                    raise ValueError("Limit price required for limit orders")
                order = LimitOrder(action, quantity, limit_price)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")
            
            # CRITICAL FIX: Add explicit account and time_in_force
            order.account = config.tws.account if config.tws.account else self.account_id
            order.tif = "GTC"  # Good Till Cancelled
            
            # Add SMART routing for price improvement on all orders
            from ib_async import TagValue
            order.smartComboRoutingParams = [
                TagValue("NonGuaranteed", "1")  # Enable immediate price improvement
            ]
            
            # Place the order
            trade = self.ib.placeOrder(stock, order)
            
            # Wait for order to be acknowledged
            await asyncio.sleep(2)
            
            logger.info(f"Placed {action} order for {quantity} shares of {symbol} at {limit_price if limit_price else 'market price'}")
            
            return {
                'order_id': trade.order.orderId,
                'status': trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Submitted',
                'symbol': symbol,
                'quantity': quantity,
                'action': action,
                'order_type': order_type,
                'limit_price': limit_price
            }
            
        except Exception as e:
            logger.error(f"Error placing stock order for {symbol}: {e}")
            raise TWSConnectionError(f"Failed to place stock order: {e}")

    async def place_option_order(self, leg, order_type: str = 'MKT', limit_price: Optional[float] = None) -> Dict[str, Any]:
        """
        Place a single option order (for long calls/puts).
        
        Args:
            leg: Single OptionLeg object containing contract, action, and quantity
            order_type: 'MKT' for market, 'LMT' for limit
            limit_price: Limit price for the order (optional, uses mid if not provided)
        
        Returns:
            Order placement result
        """
        try:
            await self.ensure_connected()
            
            # Extract leg information
            if hasattr(leg, 'contract'):
                # It's an OptionLeg object
                symbol = leg.contract.symbol
                expiry = leg.contract.expiry.strftime('%Y%m%d')
                strike = leg.contract.strike
                right = leg.contract.right.value if hasattr(leg.contract.right, 'value') else leg.contract.right
                action = leg.action.value if hasattr(leg.action, 'value') else leg.action
                quantity = leg.quantity
                bid = leg.contract.bid if hasattr(leg.contract, 'bid') else 0
                ask = leg.contract.ask if hasattr(leg.contract, 'ask') else 0
            else:
                # It's a dict (backward compatibility)
                contract_data = leg.get('contract', {})
                symbol = contract_data.get('symbol', '')
                expiry = contract_data.get('expiry', '')
                if isinstance(expiry, str):
                    from datetime import datetime
                    expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00')).strftime('%Y%m%d')
                elif hasattr(expiry, 'strftime'):
                    expiry = expiry.strftime('%Y%m%d')
                strike = float(contract_data.get('strike', 0))
                right = contract_data.get('right', 'C')
                if hasattr(right, 'value'):
                    right = right.value
                action = leg.get('action', 'BUY')
                if hasattr(action, 'value'):
                    action = action.value
                quantity = int(leg.get('quantity', 1))
                bid = float(contract_data.get('bid', 0))
                ask = float(contract_data.get('ask', 0))
            
            # Ensure right is single character
            if right in ['CALL', 'Call']:
                right = 'C'
            elif right in ['PUT', 'Put']:
                right = 'P'
            
            # Create the option contract
            option_contract = self.create_option_contract(
                symbol,
                expiry,
                strike,
                right,
                'SMART'
            )
            
            # Qualify the contract
            qualified = await self.ib.qualifyContractsAsync(option_contract)
            if qualified:
                option_contract = qualified[0]
                logger.info(f"Qualified option contract: {symbol} {strike}{right} {expiry}")
            else:
                logger.warning(f"Could not qualify option contract: {symbol} {strike}{right} {expiry}")
            
            # Create order
            if order_type == 'MKT':
                order = MarketOrder(action, quantity)
                logger.info(f"Creating market order: {action} {quantity} contracts")
            else:
                # For limit orders, use provided price or calculate from bid/ask
                if limit_price is None:
                    if bid > 0 and ask > 0:
                        # Use slightly aggressive pricing for better fill
                        if action == 'BUY':
                            limit_price = bid + (ask - bid) * 0.6  # 60% toward ask for buys
                        else:
                            limit_price = ask - (ask - bid) * 0.6  # 60% toward bid for sells
                    else:
                        raise ValueError("Limit price required for limit orders when bid/ask not available")
                
                # Round to 2 decimal places for options
                limit_price = round(limit_price, 2)
                order = LimitOrder(action, quantity, limit_price)
                logger.info(f"Creating limit order: {action} {quantity} contracts at ${limit_price}")
            
            # Set account and time in force
            order.account = config.tws.account if config.tws.account else self.account_id
            order.tif = "GTC"  # Good Till Cancelled
            
            # Add SMART routing for price improvement
            from ib_async import TagValue
            order.smartComboRoutingParams = [
                TagValue("NonGuaranteed", "1")  # Enable immediate price improvement
            ]
            
            # Place the order
            trade = self.ib.placeOrder(option_contract, order)
            logger.info(f"Placed single option order: {action} {quantity} {symbol} {strike}{right} {expiry}")
            
            # Wait for order to be acknowledged
            await asyncio.sleep(2)
            
            return {
                'order_id': trade.order.orderId,
                'status': trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Submitted',
                'contract': f"{symbol} {strike}{right} {expiry}",
                'action': action,
                'quantity': quantity,
                'order_type': order_type,
                'limit_price': limit_price if order_type == 'LMT' else None,
                'message': f"Single option order placed: {action} {quantity} {symbol} {strike}{right}"
            }
            
        except Exception as e:
            logger.error(f"Error placing single option order: {e}")
            raise TWSConnectionError(f"Failed to place option order: {e}")

    async def place_combo_order(self, strategy, order_type: str = 'MKT') -> Dict[str, Any]:
        """
        Place a combo order for an options strategy.
        
        Args:
            strategy: Strategy object with legs (or dict for backward compatibility)
            order_type: 'MKT' for market, 'LMT' for limit
        
        Returns:
            Order placement result
        """
        try:
            await self.ensure_connected()
            
            # Handle both Strategy objects and dicts for backward compatibility
            if isinstance(strategy, dict):
                # If it's a dict, extract the necessary fields
                strategy_legs = strategy.get('legs', [])
                strategy_name = strategy.get('name', 'Options Strategy')
                strategy_max_loss = strategy.get('max_loss_raw', strategy.get('analysis', {}).get('max_loss', 0))
                strategy_max_profit = strategy.get('max_profit_raw', strategy.get('analysis', {}).get('max_profit', 0))
                # Get symbol from first leg
                if strategy_legs and isinstance(strategy_legs[0], dict):
                    symbol = strategy_legs[0].get('contract', {}).get('symbol', '')
                else:
                    symbol = ''
                logger.warning(f"place_combo_order received dict instead of Strategy object - converting")
            else:
                # It's a Strategy object
                strategy_legs = strategy.legs
                strategy_name = strategy.name if hasattr(strategy, 'name') else 'Options Strategy'
                strategy_max_loss = strategy.max_loss if hasattr(strategy, 'max_loss') else 0
                strategy_max_profit = strategy.max_profit if hasattr(strategy, 'max_profit') else 0
                # Get symbol from first leg
                if strategy_legs and hasattr(strategy_legs[0], 'contract'):
                    symbol = strategy_legs[0].contract.symbol
                else:
                    symbol = ''
            
            if not strategy_legs:
                raise TWSConnectionError("Strategy has no legs")
            
            # Create combo contract
            combo = Contract()
            combo.symbol = symbol
            combo.secType = 'BAG'
            combo.currency = 'USD'
            combo.exchange = 'SMART'
            
            combo_legs = []
            for leg in strategy_legs:
                # Handle both OptionLeg objects and dict legs
                if isinstance(leg, dict):
                    # Extract from dict
                    contract_data = leg.get('contract', {})
                    leg_symbol = contract_data.get('symbol', '')
                    leg_expiry = contract_data.get('expiry', '')
                    if isinstance(leg_expiry, str):
                        # Parse ISO format and convert to YYYYMMDD
                        from datetime import datetime
                        leg_expiry = datetime.fromisoformat(leg_expiry.replace('Z', '+00:00')).strftime('%Y%m%d')
                    elif hasattr(leg_expiry, 'strftime'):
                        leg_expiry = leg_expiry.strftime('%Y%m%d')
                    leg_strike = float(contract_data.get('strike', 0))
                    leg_right = contract_data.get('right', 'C')
                    if hasattr(leg_right, 'value'):
                        leg_right = leg_right.value
                    leg_action = leg.get('action', 'BUY')
                    if hasattr(leg_action, 'value'):
                        leg_action = leg_action.value
                    leg_quantity = int(leg.get('quantity', 1))
                else:
                    # It's an OptionLeg object
                    leg_symbol = leg.contract.symbol
                    leg_expiry = leg.contract.expiry.strftime('%Y%m%d')
                    leg_strike = leg.contract.strike
                    leg_right = leg.contract.right.value if hasattr(leg.contract.right, 'value') else leg.contract.right
                    leg_action = leg.action.value if hasattr(leg.action, 'value') else leg.action
                    leg_quantity = leg.quantity
                
                # Create the actual IB contract for this leg
                ib_contract = self.create_option_contract(
                    leg_symbol,
                    leg_expiry,
                    leg_strike,
                    leg_right,
                    'SMART'
                )
                
                # Qualify the contract
                qualified = await self.ib.qualifyContractsAsync(ib_contract)
                if qualified:
                    ib_contract = qualified[0]
                
                # Create combo leg
                combo_leg = ComboLeg()
                combo_leg.conId = ib_contract.conId
                combo_leg.ratio = leg_quantity
                combo_leg.action = leg_action
                combo_leg.exchange = 'SMART'
                
                combo_legs.append(combo_leg)
            
            combo.comboLegs = combo_legs
            
            # Create order
            if order_type == 'MKT':
                order = MarketOrder('BUY', 1)  # Quantity 1 for combo
            else:
                # For limit orders, get the net debit/credit
                # Import here to avoid circular dependency
                from src.modules.strategies.base import BaseStrategy
                from src.models import Strategy
                
                if isinstance(strategy, BaseStrategy):
                    # BaseStrategy with async method
                    net_debit_credit = await strategy.calculate_net_debit_credit()
                elif hasattr(strategy, 'net_debit_credit'):
                    # Strategy dataclass with property
                    net_debit_credit = strategy.net_debit_credit
                elif isinstance(strategy, dict):
                    # Dict strategy - get from stored values
                    net_debit_credit = strategy.get('required_capital', 0)
                    if net_debit_credit == 0:
                        net_debit_credit = strategy.get('analysis', {}).get('net_debit', 0)
                else:
                    # Fallback - calculate from legs
                    if hasattr(strategy, 'legs') and strategy.legs:
                        net_debit_credit = sum(leg.cost for leg in strategy.legs if hasattr(leg, 'cost')) 
                    else:
                        net_debit_credit = 0
                    
                limit_price = abs(net_debit_credit)
                order = LimitOrder('BUY', 1, limit_price)
            
            # CRITICAL FIX: Add explicit account and time_in_force
            order.account = config.tws.account if config.tws.account else self.account_id
            order.tif = "GTC"  # Good Till Cancelled
            
            # Add SMART routing for price improvement (NonGuaranteed for immediate execution)
            from ib_async import TagValue
            order.smartComboRoutingParams = [
                TagValue("NonGuaranteed", "1")  # Enable price improvement
            ]
            
            # Set order combo legs for native spread execution
            order.orderComboLegs = []  # IBKR will calculate automatically for BAG orders
            
            # Place the order with native spread execution
            trade = self.ib.placeOrder(combo, order)
            logger.info(f"Placed native spread order (BAG) for {strategy_name} with SMART routing")
            
            # Wait for order to be acknowledged
            await asyncio.sleep(2)
            
            return {
                'order_id': trade.order.orderId,
                'status': trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Submitted',
                'strategy': strategy_name,
                'max_loss': strategy_max_loss,
                'max_profit': strategy_max_profit
            }
            
        except Exception as e:
            strategy_name = getattr(strategy, 'name', 'Unknown Strategy')
            logger.error(f"Error placing combo order for {strategy_name}: {e}")
            raise TWSConnectionError(f"Failed to place combo order: {e}")
    
    async def place_bracket_order(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        stop_loss_price: float,
        profit_target_price: float,
        is_option: bool = False,
        option_params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Place a bracket order with entry, stop loss, and profit target.
        
        Args:
            symbol: Stock or underlying symbol
            quantity: Number of shares/contracts
            entry_price: Entry limit price
            stop_loss_price: Stop loss trigger price
            profit_target_price: Profit target limit price
            is_option: Whether this is for options
            option_params: Dict with expiry, strike, right for options
        
        Returns:
            Order placement result with all three order IDs
        """
        try:
            await self.ensure_connected()
            
            # Create contract
            if is_option and option_params:
                contract = self.create_option_contract(
                    symbol,
                    option_params['expiry'],
                    option_params['strike'],
                    option_params['right'],
                    'SMART'
                )
            else:
                contract = Stock(symbol, 'SMART', 'USD')
            
            # Qualify contract
            qualified = await self.ib.qualifyContractsAsync(contract)
            if qualified:
                contract = qualified[0]
            
            # Create parent order (entry) with SMART routing
            from ib_async import TagValue
            parent_order = LimitOrder('BUY', quantity, entry_price)
            parent_order.transmit = False  # Don't transmit until bracket is complete
            parent_order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
            # CRITICAL FIX: Add explicit account and time_in_force
            parent_order.account = config.tws.account if config.tws.account else self.account_id
            parent_order.tif = "GTC"  # Good Till Cancelled
            
            # Place parent order
            parent_trade = self.ib.placeOrder(contract, parent_order)
            parent_id = parent_trade.order.orderId
            
            # Create stop loss order
            stop_order = Order()
            stop_order.action = 'SELL'
            stop_order.totalQuantity = quantity
            stop_order.orderType = 'STP'
            stop_order.auxPrice = stop_loss_price  # Stop trigger price
            stop_order.parentId = parent_id
            stop_order.transmit = False
            # CRITICAL FIX: Add explicit account and time_in_force
            stop_order.account = config.tws.account if config.tws.account else self.account_id
            stop_order.tif = "GTC"  # Good Till Cancelled
            
            # Place stop loss
            stop_trade = self.ib.placeOrder(contract, stop_order)
            
            # Create profit target order
            profit_order = LimitOrder('SELL', quantity, profit_target_price)
            profit_order.parentId = parent_id
            profit_order.transmit = True  # Transmit all orders now
            profit_order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
            # CRITICAL FIX: Add explicit account and time_in_force
            profit_order.account = config.tws.account if config.tws.account else self.account_id
            profit_order.tif = "GTC"  # Good Till Cancelled
            
            # Place profit target (this transmits all three)
            profit_trade = self.ib.placeOrder(contract, profit_order)
            
            # Wait for acknowledgment
            await asyncio.sleep(2)
            
            logger.info(f"Placed bracket order for {symbol}: Entry={entry_price}, Stop={stop_loss_price}, Target={profit_target_price}")
            
            return {
                'parent_order_id': parent_id,
                'stop_order_id': stop_trade.order.orderId,
                'profit_order_id': profit_trade.order.orderId,
                'symbol': symbol,
                'quantity': quantity,
                'entry_price': entry_price,
                'stop_loss': stop_loss_price,
                'profit_target': profit_target_price,
                'max_risk': (entry_price - stop_loss_price) * quantity,
                'max_reward': (profit_target_price - entry_price) * quantity
            }
            
        except Exception as e:
            logger.error(f"Error placing bracket order for {symbol}: {e}")
            raise TWSConnectionError(f"Failed to place bracket order: {e}")
    
    async def get_account_summary(self) -> Dict[str, Any]:
        """
        Get account summary including buying power and margin.
        
        Returns:
            Account summary data
        """
        try:
            await self.ensure_connected()
            
            # Request account summary
            account_summary = self.ib.accountSummary()
            
            summary_dict = {}
            for item in account_summary:
                summary_dict[item.tag] = {
                    'value': item.value,
                    'currency': item.currency,
                    'account': item.account
                }
            
            return summary_dict
            
        except Exception as e:
            logger.error(f"Failed to get account summary: {e}")
            raise TWSConnectionError(f"Failed to get account summary: {e}")
    
    async def get_positions_with_pnl(self) -> List[Dict[str, Any]]:
        """
        Get all positions with detailed P&L calculations.
        
        Returns:
            List of positions with P&L data
        """
        try:
            await self.ensure_connected()
            
            positions = self.ib.positions()
            portfolio = self.ib.portfolio()
            
            # Match positions with portfolio items
            position_data = []
            
            for pos in positions:
                # Find matching portfolio item
                portfolio_item = next(
                    (p for p in portfolio if p.contract.conId == pos.contract.conId),
                    None
                )
                
                pos_dict = {
                    'contract': pos.contract,
                    'position': pos.position,
                    'avg_cost': pos.avgCost,
                    'account': pos.account
                }
                
                if portfolio_item:
                    pos_dict.update({
                        'market_price': portfolio_item.marketPrice,
                        'market_value': portfolio_item.marketValue,
                        'unrealized_pnl': portfolio_item.unrealizedPNL,
                        'realized_pnl': portfolio_item.realizedPNL
                    })
                
                position_data.append(pos_dict)
            
            return position_data
            
        except Exception as e:
            logger.error(f"Failed to get positions with P&L: {e}")
            raise TWSConnectionError(f"Failed to get positions with P&L: {e}")
    
    async def place_oca_order(
        self,
        orders: List[Tuple[Contract, Order]],
        oca_group: str,
        oca_type: int = 1  # 1 = Cancel all remaining orders with block
    ) -> List:
        """
        Place One-Cancels-All order group.
        
        Args:
            orders: List of (contract, order) tuples
            oca_group: OCA group name
            oca_type: OCA type (1, 2, or 3)
        
        Returns:
            List of Trade objects
        """
        try:
            await self.ensure_connected()
            
            trades = []
            
            for contract, order in orders:
                # Set OCA properties
                order.ocaGroup = oca_group
                order.ocaType = oca_type
                
                # Place order
                trade = self.ib.placeOrder(contract, order)
                trades.append(trade)
            
            return trades
            
        except Exception as e:
            logger.error(f"Failed to place OCA orders: {e}")
            raise TWSConnectionError(f"Failed to place OCA orders: {e}")

# Global connection instance - lazy initialization
_tws_connection_instance = None

def get_tws_connection():
    """Get or create the global TWS connection instance."""
    global _tws_connection_instance
    if _tws_connection_instance is None:
        logger.info("Creating new TWS connection instance (lazy)")
        _tws_connection_instance = TWSConnection()
    return _tws_connection_instance

# Lazy singleton - don't create until first use
class LazyTWSConnection:
    """Proxy that creates connection on first attribute access."""
    
    def __getattr__(self, name):
        """Create connection on first access."""
        return getattr(get_tws_connection(), name)

# Use lazy proxy to prevent immediate instantiation
tws_connection = LazyTWSConnection()
