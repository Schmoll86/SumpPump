"""
Extended Hours Trading Module
Implements IBKR best practices for after-hours and overnight trading
"""

import asyncio
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime, timedelta, time
from dataclasses import dataclass
from enum import Enum
from loguru import logger

from ib_async import (
    Stock, Option, Contract,
    MarketOrder, LimitOrder, StopOrder, Order
)


class TimeInForce(Enum):
    """Time in Force options per IBKR API."""
    DAY = "DAY"           # Day order (default)
    GTC = "GTC"           # Good Till Cancelled
    IOC = "IOC"           # Immediate or Cancel
    GTD = "GTD"           # Good Till Date
    OPG = "OPG"           # At the Opening
    FOK = "FOK"           # Fill or Kill
    DTC = "DTC"           # Day Till Cancelled


class TradingSession(Enum):
    """Trading session types."""
    REGULAR = "regular"                # 9:30 AM - 4:00 PM ET
    PRE_MARKET = "pre_market"          # 4:00 AM - 9:30 AM ET
    AFTER_HOURS = "after_hours"        # 4:00 PM - 8:00 PM ET
    OVERNIGHT = "overnight"             # 8:00 PM - 4:00 AM ET
    EXTENDED = "extended"               # All non-regular hours


@dataclass
class ExtendedHoursConfig:
    """Configuration for extended hours trading."""
    allow_pre_market: bool = True
    allow_after_hours: bool = True
    allow_overnight: bool = False  # Requires special permission
    
    # Venue preferences
    use_overnight_venue: bool = False  # Use IBEOS or OVERNIGHT
    smart_routing: bool = True         # Use SMART routing during regular hours
    
    # Risk limits for extended hours
    max_order_size_extended: int = 100  # Smaller size for extended hours
    limit_order_only: bool = True       # No market orders in extended hours
    
    # Time restrictions
    no_orders_after: Optional[time] = time(23, 0)  # No orders after 11 PM
    no_orders_before: Optional[time] = time(4, 0)  # No orders before 4 AM


class ExtendedHoursValidator:
    """Validates orders for extended hours trading."""
    
    def __init__(self, config: Optional[ExtendedHoursConfig] = None):
        self.config = config or ExtendedHoursConfig()
        
        # IBKR trading hours (ET)
        self.regular_start = time(9, 30)
        self.regular_end = time(16, 0)
        self.pre_market_start = time(4, 0)
        self.after_hours_end = time(20, 0)
        self.overnight_start = time(20, 0)
        self.overnight_end = time(3, 50)
    
    def get_current_session(self) -> TradingSession:
        """Determine current trading session."""
        now = datetime.now()
        current_time = now.time()
        
        # Check if weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return TradingSession.OVERNIGHT if self.config.allow_overnight else TradingSession.EXTENDED
        
        # Regular hours
        if self.regular_start <= current_time < self.regular_end:
            return TradingSession.REGULAR
        
        # Pre-market
        if self.pre_market_start <= current_time < self.regular_start:
            return TradingSession.PRE_MARKET
        
        # After-hours
        if self.regular_end <= current_time < self.after_hours_end:
            return TradingSession.AFTER_HOURS
        
        # Overnight
        if current_time >= self.overnight_start or current_time < self.overnight_end:
            return TradingSession.OVERNIGHT
        
        return TradingSession.EXTENDED
    
    def validate_extended_order(
        self,
        symbol: str,
        order_type: str,
        quantity: int,
        session: Optional[TradingSession] = None
    ) -> tuple[bool, str]:
        """
        Validate order for extended hours trading.
        
        Returns:
            (is_valid, message)
        """
        if session is None:
            session = self.get_current_session()
        
        # Check session permissions
        if session == TradingSession.PRE_MARKET and not self.config.allow_pre_market:
            return False, "Pre-market trading not enabled"
        
        if session == TradingSession.AFTER_HOURS and not self.config.allow_after_hours:
            return False, "After-hours trading not enabled"
        
        if session == TradingSession.OVERNIGHT and not self.config.allow_overnight:
            return False, "Overnight trading not enabled (requires special permission)"
        
        # Check order type restrictions
        if session != TradingSession.REGULAR:
            if self.config.limit_order_only and order_type == "MKT":
                return False, f"Market orders not allowed during {session.value}. Use limit orders."
            
            # Check size limits
            if quantity > self.config.max_order_size_extended:
                return False, f"Order size {quantity} exceeds extended hours limit {self.config.max_order_size_extended}"
        
        # Check time restrictions
        now = datetime.now().time()
        if self.config.no_orders_after and now > self.config.no_orders_after:
            return False, f"Orders not allowed after {self.config.no_orders_after}"
        
        if self.config.no_orders_before and now < self.config.no_orders_before:
            return False, f"Orders not allowed before {self.config.no_orders_before}"
        
        return True, f"Order valid for {session.value} session"


async def create_extended_hours_order(
    tws_connection,
    symbol: str,
    action: Literal["BUY", "SELL"],
    quantity: int,
    order_type: Literal["MKT", "LMT", "STP", "STP_LMT"] = "LMT",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: str = "DAY",
    outside_rth: bool = False,
    good_till_date: Optional[str] = None,  # Format: "YYYYMMDD HH:MM:SS"
    extended_hours_config: Optional[ExtendedHoursConfig] = None
) -> Dict[str, Any]:
    """
    Create order with extended hours support following IBKR best practices.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Stock symbol
        action: BUY or SELL
        quantity: Number of shares
        order_type: Order type (MKT, LMT, STP, STP_LMT)
        limit_price: Limit price for LMT orders
        stop_price: Stop price for STP orders
        time_in_force: DAY, GTC, IOC, GTD, OPG
        outside_rth: Allow execution outside regular trading hours
        good_till_date: Expiration for GTD orders
        extended_hours_config: Configuration for extended hours
        
    Returns:
        Order creation result
    """
    logger.info(f"[EXTENDED] Creating {order_type} {action} order for {quantity} {symbol}")
    
    # Initialize validator
    config = extended_hours_config or ExtendedHoursConfig()
    validator = ExtendedHoursValidator(config)
    
    # Get current session
    session = validator.get_current_session()
    logger.info(f"[EXTENDED] Current session: {session.value}")
    
    # Validate order for extended hours
    is_valid, message = validator.validate_extended_order(
        symbol, order_type, quantity, session
    )
    
    if not is_valid:
        logger.warning(f"[EXTENDED] Order validation failed: {message}")
        return {
            'status': 'blocked',
            'error': 'EXTENDED_HOURS_VALIDATION',
            'message': message,
            'session': session.value,
            'recommendation': 'Use limit orders with smaller size for extended hours'
        }
    
    try:
        # Create contract
        contract = Stock(symbol, 'SMART', 'USD')
        
        # Determine routing based on session
        if session == TradingSession.OVERNIGHT and config.use_overnight_venue:
            # Use OVERNIGHT venue for overnight session
            contract.exchange = 'OVERNIGHT'
            logger.info("[EXTENDED] Using OVERNIGHT venue")
        elif session != TradingSession.REGULAR and not config.smart_routing:
            # Use specific exchange for extended hours
            contract.exchange = 'ISLAND'  # NASDAQ for extended hours
            logger.info("[EXTENDED] Using ISLAND exchange for extended hours")
        
        # Create order based on type
        if order_type == "MKT":
            if session != TradingSession.REGULAR and config.limit_order_only:
                # Convert to limit order at bid/ask
                logger.warning("[EXTENDED] Converting market order to limit for extended hours")
                # Get current quote
                ticker = tws_connection.ib.reqMktData(contract)
                await asyncio.sleep(1)
                
                if action == "BUY":
                    limit_price = ticker.ask or ticker.last
                else:
                    limit_price = ticker.bid or ticker.last
                
                tws_connection.ib.cancelMktData(contract)
                
                if not limit_price:
                    return {
                        'status': 'failed',
                        'error': 'NO_QUOTE',
                        'message': 'Cannot get quote for limit price conversion'
                    }
                
                order = LimitOrder(action, quantity, limit_price)
            else:
                order = MarketOrder(action, quantity)
        
        elif order_type == "LMT":
            if not limit_price:
                return {
                    'status': 'failed',
                    'error': 'MISSING_LIMIT_PRICE',
                    'message': 'Limit price required for LMT orders'
                }
            order = LimitOrder(action, quantity, limit_price)
        
        elif order_type == "STP":
            if not stop_price:
                return {
                    'status': 'failed',
                    'error': 'MISSING_STOP_PRICE',
                    'message': 'Stop price required for STP orders'
                }
            order = StopOrder(action, quantity, stop_price)
        
        elif order_type == "STP_LMT":
            if not stop_price or not limit_price:
                return {
                    'status': 'failed',
                    'error': 'MISSING_PRICES',
                    'message': 'Both stop and limit prices required for STP_LMT'
                }
            order = Order()
            order.action = action
            order.orderType = "STP LMT"
            order.totalQuantity = quantity
            order.lmtPrice = limit_price
            order.auxPrice = stop_price
        
        else:
            return {
                'status': 'failed',
                'error': 'INVALID_ORDER_TYPE',
                'message': f'Unsupported order type: {order_type}'
            }
        
        # Set extended hours parameters
        order.outsideRth = outside_rth
        order.tif = time_in_force
        # CRITICAL FIX: Add explicit account field
        order.account = "U16348403"
        order.transmit = True  # Transmit order immediately
        
        # Set GTD expiration if specified
        if time_in_force == "GTD":
            if not good_till_date:
                # Default to end of next trading day
                tomorrow = datetime.now() + timedelta(days=1)
                good_till_date = tomorrow.strftime("%Y%m%d 16:00:00")
            order.goodTillDate = good_till_date
        
        # Add special handling for overnight orders
        if session == TradingSession.OVERNIGHT:
            # Set special parameters for overnight trading
            order.algoStrategy = ""  # Clear any algo
            order.algoParams = []
            
            # Ensure order routes to overnight venue
            if config.use_overnight_venue:
                order.exchange = "OVERNIGHT"
        
        # Log order configuration
        logger.info(f"[EXTENDED] Order config: TIF={time_in_force}, OutsideRTH={outside_rth}, Session={session.value}")
        
        # Place the order
        trade = tws_connection.ib.placeOrder(contract, order)
        order_id = trade.order.orderId
        
        # Wait for order acknowledgment
        await asyncio.sleep(2)
        
        # Check order status
        status_msg = trade.orderStatus.status
        
        # Build response
        result = {
            'status': 'success',
            'order_id': order_id,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'order_type': order_type,
            'time_in_force': time_in_force,
            'outside_rth': outside_rth,
            'session': session.value,
            'order_status': status_msg,
            'timestamp': datetime.now().isoformat()
        }
        
        if limit_price:
            result['limit_price'] = limit_price
        if stop_price:
            result['stop_price'] = stop_price
        if good_till_date:
            result['good_till_date'] = good_till_date
        
        # Add warnings for extended hours
        if session != TradingSession.REGULAR:
            result['warnings'] = [
                f"Order placed during {session.value} session",
                "Extended hours trading involves additional risks",
                "Liquidity may be limited",
                "Spreads may be wider than regular hours"
            ]
        
        logger.info(f"[EXTENDED] Order {order_id} placed successfully during {session.value}")
        return result
        
    except Exception as e:
        logger.error(f"[EXTENDED] Order creation failed: {e}")
        return {
            'status': 'failed',
            'error': 'ORDER_CREATION_ERROR',
            'message': str(e),
            'session': session.value
        }


async def modify_for_extended_hours(
    tws_connection,
    order_id: int,
    enable_extended: bool = True,
    new_tif: Optional[str] = None
) -> Dict[str, Any]:
    """
    Modify existing order to enable/disable extended hours trading.
    
    Args:
        tws_connection: Active TWS connection
        order_id: Order ID to modify
        enable_extended: Enable or disable extended hours
        new_tif: New time in force (optional)
        
    Returns:
        Modification result
    """
    logger.info(f"[EXTENDED] Modifying order {order_id} for extended hours: {enable_extended}")
    
    try:
        # Find the order
        open_orders = tws_connection.ib.openOrders()
        target_order = None
        
        for order in open_orders:
            if order.orderId == order_id:
                target_order = order
                break
        
        if not target_order:
            return {
                'status': 'failed',
                'error': 'ORDER_NOT_FOUND',
                'message': f'Order {order_id} not found in open orders'
            }
        
        # Modify extended hours settings
        target_order.outsideRth = enable_extended
        
        if new_tif:
            target_order.tif = new_tif
        
        # CRITICAL FIX: Ensure account is set
        target_order.account = "U16348403"
        
        # Get the contract for this order
        open_trades = tws_connection.ib.openTrades()
        target_trade = None
        
        for trade in open_trades:
            if trade.order.orderId == order_id:
                target_trade = trade
                break
        
        if not target_trade:
            return {
                'status': 'failed',
                'error': 'TRADE_NOT_FOUND',
                'message': f'Trade for order {order_id} not found'
            }
        
        # Place modified order
        modified_trade = tws_connection.ib.placeOrder(
            target_trade.contract,
            target_order
        )
        
        await asyncio.sleep(1)
        
        return {
            'status': 'success',
            'order_id': order_id,
            'outside_rth': enable_extended,
            'time_in_force': target_order.tif,
            'message': f'Order modified for {"extended" if enable_extended else "regular"} hours',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[EXTENDED] Order modification failed: {e}")
        return {
            'status': 'failed',
            'error': 'MODIFICATION_ERROR',
            'message': str(e)
        }


def get_extended_hours_schedule() -> Dict[str, Any]:
    """
    Get current extended hours trading schedule.
    
    Returns:
        Trading schedule information
    """
    now = datetime.now()
    current_time = now.time()
    weekday = now.weekday()
    
    # Define schedule (all times ET)
    schedule = {
        'current_time': now.isoformat(),
        'timezone': 'ET',
        'weekday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][weekday],
        'sessions': {
            'pre_market': {
                'start': '04:00',
                'end': '09:30',
                'active': time(4, 0) <= current_time < time(9, 30) and weekday < 5
            },
            'regular': {
                'start': '09:30',
                'end': '16:00',
                'active': time(9, 30) <= current_time < time(16, 0) and weekday < 5
            },
            'after_hours': {
                'start': '16:00',
                'end': '20:00',
                'active': time(16, 0) <= current_time < time(20, 0) and weekday < 5
            },
            'overnight': {
                'start': '20:00',
                'end': '03:50',
                'active': (current_time >= time(20, 0) or current_time < time(3, 50)) and weekday < 5,
                'note': 'Requires special permission'
            }
        }
    }
    
    # Determine current session
    validator = ExtendedHoursValidator()
    current_session = validator.get_current_session()
    schedule['current_session'] = current_session.value
    
    # Add recommendations
    if current_session == TradingSession.REGULAR:
        schedule['recommendation'] = 'Regular hours - all order types available'
    elif current_session in [TradingSession.PRE_MARKET, TradingSession.AFTER_HOURS]:
        schedule['recommendation'] = 'Extended hours - use limit orders, expect wider spreads'
    elif current_session == TradingSession.OVERNIGHT:
        schedule['recommendation'] = 'Overnight session - limited liquidity, use caution'
    else:
        schedule['recommendation'] = 'Market closed - orders will queue for next session'
    
    return schedule


# Export main functions
__all__ = [
    'create_extended_hours_order',
    'modify_for_extended_hours',
    'get_extended_hours_schedule',
    'ExtendedHoursConfig',
    'ExtendedHoursValidator',
    'TimeInForce',
    'TradingSession'
]