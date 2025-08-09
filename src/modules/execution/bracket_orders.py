"""
Bracket order implementation for automatic risk management.
Places entry, profit target, and stop loss as a single unit.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger
from ib_async import (
    Contract, Order, Trade, 
    MarketOrder, LimitOrder, StopOrder,
    BracketOrder as IBBracketOrder
)

from src.modules.tws.connection import get_tws_connection


@dataclass
class BracketOrderParams:
    """Parameters for bracket order creation."""
    entry_price: float
    take_profit_percent: float = 50.0  # % above entry
    stop_loss_percent: float = 25.0    # % below entry
    quantity: int = 1
    trailing_stop: bool = False
    trailing_amount: Optional[float] = None
    one_cancels_all: bool = True
    
    def calculate_levels(self) -> Tuple[float, float]:
        """Calculate profit and stop levels."""
        if self.take_profit_percent > 0:
            profit_target = self.entry_price * (1 + self.take_profit_percent / 100)
        else:
            profit_target = None
            
        if self.stop_loss_percent > 0:
            stop_loss = self.entry_price * (1 - self.stop_loss_percent / 100)
        else:
            stop_loss = None
            
        return profit_target, stop_loss


class BracketOrderManager:
    """Manages bracket orders for risk management."""
    
    def __init__(self):
        """Initialize bracket order manager."""
        self.tws = None
        self.active_brackets: Dict[str, Dict[str, Any]] = {}
        
    async def _ensure_connection(self):
        """Ensure TWS connection."""
        if not self.tws:
            self.tws = await get_tws_connection()
    
    async def place_bracket_order(
        self,
        contract: Contract,
        action: str,  # 'BUY' or 'SELL'
        params: BracketOrderParams
    ) -> Dict[str, Any]:
        """
        Place a bracket order with entry, profit target, and stop loss.
        
        Args:
            contract: Contract to trade
            action: 'BUY' or 'SELL'
            params: Bracket order parameters
            
        Returns:
            Order placement results
        """
        await self._ensure_connection()
        ib = self.tws.ib
        
        logger.info(
            f"[BRACKET] Creating bracket order for {contract.symbol} "
            f"{action} {params.quantity} @ {params.entry_price}"
        )
        
        # Calculate levels
        profit_target, stop_loss = params.calculate_levels()
        
        logger.info(
            f"[BRACKET] Levels - Entry: {params.entry_price:.2f}, "
            f"Target: {profit_target:.2f if profit_target else 'None'}, "
            f"Stop: {stop_loss:.2f if stop_loss else 'None'}"
        )
        
        # Place parent order first to get order ID
        parent = LimitOrder(action, params.quantity, params.entry_price)
        parent.orderType = 'LMT'
        parent.transmit = False  # Don't transmit yet
        
        # Place parent to get order ID
        parent_trade = ib.placeOrder(contract, parent)
        parent_order_id = parent_trade.order.orderId
        trades = [parent_trade]
        
        logger.debug(f"[BRACKET] Placed parent order: {parent_order_id}")
        
        # Create child orders with parent ID
        if profit_target:
            profit_action = 'SELL' if action == 'BUY' else 'BUY'
            profit = LimitOrder(profit_action, params.quantity, profit_target)
            profit.parentId = parent_order_id
            profit.transmit = False
            profit_trade = ib.placeOrder(contract, profit)
            trades.append(profit_trade)
            logger.debug(f"[BRACKET] Placed profit target: {profit_trade.order.orderId}")
        
        if stop_loss:
            stop_action = 'SELL' if action == 'BUY' else 'BUY'
            stop = StopOrder(stop_action, params.quantity, stop_loss)
            stop.parentId = parent_order_id
            stop.transmit = True  # Transmit all orders now
            
            # Set OCA group
            if len(trades) > 1:  # Have profit order
                import time
                oca_group = f"bracket_{int(time.time())}"
                trades[1].order.ocaGroup = oca_group
                stop.ocaGroup = oca_group
                
            stop_trade = ib.placeOrder(contract, stop)
            trades.append(stop_trade)
            logger.debug(f"[BRACKET] Placed stop loss: {stop_trade.order.orderId}")
            
        # Wait for parent order to be acknowledged
        parent_trade = trades[0]
        await asyncio.sleep(1)
        
        # Store bracket info
        bracket_id = f"bracket_{contract.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.active_brackets[bracket_id] = {
            'contract': contract,
            'parent_order': parent_trade.order.orderId,
            'profit_order': trades[1].order.orderId if len(trades) > 1 else None,
            'stop_order': trades[2].order.orderId if len(trades) > 2 else None,
            'trades': trades,
            'params': params,
            'status': 'PENDING'
        }
        
        logger.info(
            f"[BRACKET] Bracket order placed - "
            f"Parent: {parent_trade.order.orderId}, "
            f"Target: {trades[1].order.orderId if len(trades) > 1 else 'None'}, "
            f"Stop: {trades[2].order.orderId if len(trades) > 2 else 'None'}"
        )
        
        return {
            'status': 'success',
            'bracket_id': bracket_id,
            'symbol': contract.symbol,
            'action': action,
            'quantity': params.quantity,
            'levels': {
                'entry': params.entry_price,
                'profit_target': profit_target,
                'stop_loss': stop_loss
            },
            'orders': {
                'parent': parent_trade.order.orderId,
                'profit': trades[1].order.orderId if len(trades) > 1 else None,
                'stop': trades[2].order.orderId if len(trades) > 2 else None
            },
            'message': 'Bracket order placed. All three orders are linked.'
        }
    
    def _create_bracket_orders(
        self,
        action: str,
        quantity: int,
        limit_price: float,
        take_profit_price: Optional[float],
        stop_loss_price: Optional[float],
        trailing_stop: bool = False,
        trailing_amount: Optional[float] = None
    ) -> List[Order]:
        """
        Create the three orders for a bracket.
        
        Args:
            action: 'BUY' or 'SELL'
            quantity: Number of shares/contracts
            limit_price: Entry price
            take_profit_price: Profit target price
            stop_loss_price: Stop loss price
            trailing_stop: Use trailing stop
            trailing_amount: Trailing amount
            
        Returns:
            List of three orders [parent, profit, stop]
        """
        # Parent order (entry)
        parent = LimitOrder(action, quantity, limit_price)
        parent.orderType = 'LMT'
        parent.transmit = False  # Don't transmit until all orders created
        
        orders = [parent]
        
        # Profit target order (opposite action)
        if take_profit_price:
            profit_action = 'SELL' if action == 'BUY' else 'BUY'
            profit = LimitOrder(profit_action, quantity, take_profit_price)
            profit.parentId = parent.orderId
            profit.transmit = False
            orders.append(profit)
        
        # Stop loss order
        if stop_loss_price:
            stop_action = 'SELL' if action == 'BUY' else 'BUY'
            
            if trailing_stop and trailing_amount:
                # Trailing stop
                stop = Order()
                stop.action = stop_action
                stop.orderType = 'TRAIL'
                stop.totalQuantity = quantity
                stop.trailStopPrice = stop_loss_price
                stop.auxPrice = trailing_amount  # Trailing amount
            else:
                # Fixed stop
                stop = StopOrder(stop_action, quantity, stop_loss_price)
                
            stop.parentId = parent.orderId
            stop.transmit = True  # Transmit all orders now
            orders.append(stop)
        else:
            # If no stop, transmit with last order
            orders[-1].transmit = True
            
        # Set OCA group for one-cancels-all
        import time
        oca_group = f"bracket_{int(time.time())}"
        for order in orders[1:]:  # Skip parent
            order.ocaGroup = oca_group
            order.ocaType = 1  # Cancel all remaining orders with block
            
        logger.debug(f"[BRACKET] Created {len(orders)} orders with OCA group {oca_group}")
        
        return orders
    
    async def place_options_bracket(
        self,
        contract: Contract,
        action: str,
        quantity: int,
        entry_limit: float,
        profit_percent: float = 100.0,  # 100% profit target
        stop_percent: float = 50.0       # 50% stop loss
    ) -> Dict[str, Any]:
        """
        Place bracket order specifically for options.
        
        Args:
            contract: Option contract
            action: 'BUY' or 'SELL'
            quantity: Number of contracts
            entry_limit: Entry limit price
            profit_percent: Profit target as % of premium
            stop_percent: Stop loss as % of premium
            
        Returns:
            Bracket order result
        """
        if contract.secType != 'OPT':
            return {
                'status': 'error',
                'error': 'Contract must be an option',
                'message': 'Use place_bracket_order for stocks'
            }
            
        logger.info(
            f"[BRACKET] Options bracket for {contract.symbol} "
            f"{contract.strike} {contract.right}"
        )
        
        # Calculate option-specific levels
        # For BUY: profit is higher, stop is lower
        # For SELL: profit is lower, stop is higher
        if action == 'BUY':
            profit_target = entry_limit * (1 + profit_percent / 100)
            stop_loss = entry_limit * (1 - stop_percent / 100)
        else:  # SELL
            profit_target = entry_limit * (1 - profit_percent / 100)
            stop_loss = entry_limit * (1 + stop_percent / 100)
            
        params = BracketOrderParams(
            entry_price=entry_limit,
            take_profit_percent=0,  # We calculate manually
            stop_loss_percent=0,     # We calculate manually
            quantity=quantity
        )
        
        # Override calculated levels
        params.entry_price = entry_limit
        
        # Create orders manually for options
        await self._ensure_connection()
        ib = self.tws.ib
        
        # Parent order
        parent = LimitOrder(action, quantity, entry_limit)
        parent.transmit = False
        
        # Profit order
        profit_action = 'SELL' if action == 'BUY' else 'BUY'
        profit = LimitOrder(profit_action, quantity, profit_target)
        profit.parentId = parent.orderId
        profit.transmit = False
        
        # Stop order
        stop = StopOrder(profit_action, quantity, stop_loss)
        stop.parentId = parent.orderId
        stop.transmit = True
        
        # OCA group
        oca_group = f"opt_bracket_{contract.symbol}_{datetime.now().strftime('%H%M%S')}"
        profit.ocaGroup = oca_group
        stop.ocaGroup = oca_group
        profit.ocaType = 1
        stop.ocaType = 1
        
        # Place orders
        trades = []
        for order in [parent, profit, stop]:
            trade = ib.placeOrder(contract, order)
            trades.append(trade)
            
        logger.info(
            f"[BRACKET] Options bracket placed - "
            f"Entry: ${entry_limit:.2f}, "
            f"Target: ${profit_target:.2f}, "
            f"Stop: ${stop_loss:.2f}"
        )
        
        return {
            'status': 'success',
            'contract': f"{contract.symbol} {contract.strike} {contract.right}",
            'action': action,
            'quantity': quantity,
            'levels': {
                'entry': entry_limit,
                'profit_target': profit_target,
                'stop_loss': stop_loss
            },
            'premium_risk': {
                'max_profit': (profit_target - entry_limit) * quantity * 100,
                'max_loss': (entry_limit - stop_loss) * quantity * 100
            },
            'orders': {
                'parent': trades[0].order.orderId,
                'profit': trades[1].order.orderId,
                'stop': trades[2].order.orderId
            }
        }
    
    async def get_bracket_status(self, bracket_id: str) -> Dict[str, Any]:
        """
        Get status of a bracket order.
        
        Args:
            bracket_id: Bracket order ID
            
        Returns:
            Bracket order status
        """
        if bracket_id not in self.active_brackets:
            return {
                'status': 'error',
                'error': 'Bracket not found',
                'message': f'No bracket with ID {bracket_id}'
            }
            
        bracket = self.active_brackets[bracket_id]
        trades = bracket['trades']
        
        # Check status of each order
        statuses = []
        for i, trade in enumerate(trades):
            order_type = ['parent', 'profit', 'stop'][i] if i < 3 else 'unknown'
            statuses.append({
                'type': order_type,
                'order_id': trade.order.orderId,
                'status': trade.orderStatus.status,
                'filled': trade.orderStatus.filled,
                'remaining': trade.orderStatus.remaining,
                'avg_fill_price': trade.orderStatus.avgFillPrice
            })
            
        return {
            'status': 'success',
            'bracket_id': bracket_id,
            'contract': bracket['contract'].symbol,
            'order_statuses': statuses,
            'overall_status': self._determine_bracket_status(statuses)
        }
    
    def _determine_bracket_status(self, statuses: List[Dict]) -> str:
        """Determine overall bracket status."""
        parent_status = statuses[0]['status'] if statuses else 'UNKNOWN'
        
        if parent_status in ['PendingSubmit', 'PreSubmitted', 'Submitted']:
            return 'PENDING'
        elif parent_status == 'Filled':
            # Check child orders
            child_statuses = [s['status'] for s in statuses[1:]]
            if any(s == 'Filled' for s in child_statuses):
                return 'CLOSED'
            else:
                return 'ACTIVE'
        elif parent_status == 'Cancelled':
            return 'CANCELLED'
        else:
            return parent_status
    
    async def cancel_bracket(self, bracket_id: str) -> Dict[str, Any]:
        """
        Cancel an entire bracket order.
        
        Args:
            bracket_id: Bracket order ID
            
        Returns:
            Cancellation result
        """
        if bracket_id not in self.active_brackets:
            return {
                'status': 'error',
                'error': 'Bracket not found'
            }
            
        await self._ensure_connection()
        ib = self.tws.ib
        
        bracket = self.active_brackets[bracket_id]
        trades = bracket['trades']
        
        cancelled = []
        for trade in trades:
            if trade.orderStatus.status not in ['Filled', 'Cancelled']:
                ib.cancelOrder(trade.order)
                cancelled.append(trade.order.orderId)
                
        logger.info(f"[BRACKET] Cancelled {len(cancelled)} orders for bracket {bracket_id}")
        
        return {
            'status': 'success',
            'bracket_id': bracket_id,
            'cancelled_orders': cancelled,
            'message': f'Cancelled {len(cancelled)} orders'
        }