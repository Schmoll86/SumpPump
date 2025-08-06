"""
TWS Connection Manager using ib_async.
Handles connection, reconnection, and market data subscriptions.
"""

import asyncio
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, date
from contextlib import asynccontextmanager
from decimal import Decimal

from ib_async import IB, Contract, Option, Stock, MarketOrder, LimitOrder, ComboLeg, Order, util
from loguru import logger
import math

from src.config import config
from src.models import OptionContract, OptionRight, Greeks, Strategy


def _safe_sleep(duration: float):
    """Sleep that handles both async and sync contexts."""
    try:
        # Check if we're in an async context
        loop = asyncio.get_running_loop()
        if loop.is_running():
            # We're in a running event loop, use sync sleep
            import time
            time.sleep(duration)
        else:
            # No running loop, this shouldn't happen in async context
            import time
            time.sleep(duration)
    except RuntimeError:
        # No event loop running, use sync sleep
        import time
        time.sleep(duration)


async def _async_safe_sleep(duration: float):
    """Async sleep that gracefully falls back to sync when needed."""
    try:
        await asyncio.sleep(duration)
    except RuntimeError as e:
        if "This event loop is already running" in str(e):
            # Fall back to synchronous sleep
            import time
            time.sleep(duration)
        else:
            raise


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
        
    async def connect(self) -> None:
        """
        Establish connection to TWS.
        
        Raises:
            TWSConnectionError: If connection fails after max attempts
        """
        self.ib = IB()
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.ib.connectAsync(
                    host=config.tws.host,
                    port=config.tws.port,
                    clientId=config.tws.client_id,
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
                    
                logger.info(f"Connected to TWS at {config.tws.host}:{config.tws.port}")
                return
                
            except Exception as e:
                self.reconnect_attempts += 1
                logger.error(f"Connection attempt {self.reconnect_attempts} failed: {e}")
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    await _async_safe_sleep(2 ** self.reconnect_attempts)  # Exponential backoff
                    
        raise TWSConnectionError(f"Failed to connect after {self.max_reconnect_attempts} attempts")
        
    async def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self.ib and self.connected:
            # Cancel all active subscriptions
            for contract in self._active_subscriptions:
                self.ib.cancelMktData(contract)
            self._active_subscriptions.clear()
            
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from TWS")
            
    async def ensure_connected(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        if not self.connected or not self.ib.isConnected():
            logger.warning("Connection lost, attempting to reconnect...")
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
        return Option(symbol, expiry, strike, right, exchange)
    
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
                                '',  # Simplified - let IBKR decide what to send
                                False, 
                                False
                            )
                            self._active_subscriptions.add(option)
                            self._subscription_count += 1
                            
                            # Wait for data to populate
                            await asyncio.sleep(0.5)
                                
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
            
            # Cancel market data subscriptions to free up resources
            for contract in list(self._active_subscriptions):
                try:
                    self.ib.cancelMktData(contract)
                except:
                    pass
            self._active_subscriptions.clear()
            self._subscription_count = 0
            
            # Cancel stock ticker
            try:
                self.ib.cancelMktData(stock)
            except:
                pass
            
            logger.info(f"Fetched {len(options_list)} option contracts for {symbol}")
            return options_list
            
        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            # Clean up any partial subscriptions
            try:
                self._active_subscriptions.clear()
                self._subscription_count = 0
            except:
                pass
            raise TWSConnectionError(f"Failed to fetch options chain for {symbol}: {e}")
    
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
            import time
            time.sleep(2)  # Wait for data synchronously
            account_values = self.ib.accountSummary()
            logger.info(f"Retrieved {len(account_values)} account values")
            
            # Get positions
            self.ib.reqPositions()
            time.sleep(1)  # Wait for data synchronously
            positions = self.ib.positions()
            logger.info(f"Retrieved {len(positions)} positions")
            
            # Get open orders  
            self.ib.reqOpenOrders()
            time.sleep(1)  # Wait for data synchronously
            open_orders = self.ib.openOrders()
            logger.info(f"Retrieved {len(open_orders)} open orders")
            
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
            
            # Parse open orders
            for order in open_orders:
                account_info['open_orders'].append({
                    'order_id': order.orderId,
                    'symbol': order.contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'order_type': order.orderType,
                    'status': order.status
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
                managed_accounts = self.ib.managedAccounts()
                logger.info(f"Available accounts: {managed_accounts}")
                if managed_accounts:
                    account_id = managed_accounts[0]  # Use first available account
                    logger.info(f"Auto-detected account ID: {account_id}")
                else:
                    logger.error("No managed accounts found")
                    account_id = ""
            
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
            
            # Get open orders  
            self.ib.reqOpenOrders()
            await _async_safe_sleep(1)  # Wait for order data
            open_orders = self.ib.openOrders()
            logger.info(f"Retrieved {len(open_orders)} open orders")
            
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
            
            # Parse open orders
            for order in open_orders:
                account_info['open_orders'].append({
                    'order_id': order.orderId,
                    'symbol': order.contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'order_type': order.orderType,
                    'status': order.status
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
                
            # Place the order
            trade = self.ib.placeOrder(stock, order)
            
            # Wait for order to be acknowledged
            await _async_safe_sleep(2)
            
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

    async def place_combo_order(self, strategy: Strategy, order_type: str = 'MKT') -> Dict[str, Any]:
        """
        Place a combo order for an options strategy.
        
        Args:
            strategy: Strategy object with legs
            order_type: 'MKT' for market, 'LMT' for limit
        
        Returns:
            Order placement result
        """
        try:
            await self.ensure_connected()
            
            # Create combo contract
            combo = Contract()
            combo.symbol = strategy.legs[0].contract.symbol
            combo.secType = 'BAG'
            combo.currency = 'USD'
            combo.exchange = 'SMART'
            
            combo_legs = []
            for leg in strategy.legs:
                # Create the actual IB contract for this leg
                ib_contract = self.create_option_contract(
                    leg.contract.symbol,
                    leg.contract.expiry.strftime('%Y%m%d'),
                    leg.contract.strike,
                    leg.contract.right.value,
                    'SMART'
                )
                
                # Qualify the contract
                qualified = await self.ib.qualifyContractsAsync(ib_contract)
                if qualified:
                    ib_contract = qualified[0]
                
                # Create combo leg
                combo_leg = ComboLeg()
                combo_leg.conId = ib_contract.conId
                combo_leg.ratio = leg.quantity
                combo_leg.action = leg.action.value
                combo_leg.exchange = 'SMART'
                
                combo_legs.append(combo_leg)
            
            combo.comboLegs = combo_legs
            
            # Create order
            if order_type == 'MKT':
                order = MarketOrder('BUY', 1)  # Quantity 1 for combo
            else:
                # For limit orders, get the net debit/credit
                if hasattr(strategy, 'calculate_net_debit_credit'):
                    # If it's a BaseStrategy with async method
                    net_debit_credit = await strategy.calculate_net_debit_credit()
                elif hasattr(strategy, 'net_debit_credit'):
                    # If it's a Strategy dataclass with property
                    net_debit_credit = strategy.net_debit_credit
                else:
                    # Fallback - calculate from legs
                    net_debit_credit = sum(leg.cost for leg in strategy.legs) if strategy.legs else 0
                    
                limit_price = abs(net_debit_credit)
                order = LimitOrder('BUY', 1, limit_price)
            
            # Place the order
            trade = self.ib.placeOrder(combo, order)
            
            # Wait for order to be acknowledged
            await _async_safe_sleep(2)
            
            return {
                'order_id': trade.order.orderId,
                'status': trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Submitted',
                'strategy': strategy.name if hasattr(strategy, 'name') else 'Options Strategy',
                'max_loss': strategy.max_loss if hasattr(strategy, 'max_loss') else 0,
                'max_profit': strategy.max_profit if hasattr(strategy, 'max_profit') else 0
            }
            
        except Exception as e:
            strategy_name = getattr(strategy, 'name', 'Unknown Strategy')
            logger.error(f"Error placing combo order for {strategy_name}: {e}")
            raise TWSConnectionError(f"Failed to place combo order: {e}")

# Global connection instance
tws_connection = TWSConnection()
