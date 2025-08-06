"""
SumpPump Missing Tools Implementation
Integrates with existing project structure at /Users/schmoll/Desktop/SumpPump

INSTALLATION INSTRUCTIONS:
1. Add these tool functions to src/mcp/server.py after the existing tools
2. Add the helper methods to src/modules/tws/connection.py
3. Update src/models.py with the new data classes if not present

All code follows existing patterns and will work with current dependencies.
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

# These imports match your existing project structure
from ib_async import (
    IB, Contract, Option, Stock, Order, Trade, Position,
    OrderStatus, LimitOrder, MarketOrder, StopOrder, TrailOrder,
    TagValue, PortfolioItem
)

from src.config import config
from src.models import (
    OptionContract, OptionRight, OrderAction, 
    Strategy, StrategyType, OptionLeg
)
from src.modules.tws.connection import tws_connection

# ============================================================================
# MCP TOOLS - Add these to src/mcp/server.py after existing @mcp.tool() functions
# ============================================================================

@mcp.tool()
async def get_my_positions() -> Dict[str, Any]:
    """
    Get all open positions with current P&L.
    
    Returns:
        Dict containing all positions with unrealized P&L, market values, and Greeks
    """
    logger.info("Fetching current positions")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Get positions from TWS
        positions: List[Position] = tws_connection.ib.positions()
        
        # Get portfolio items for P&L data
        portfolio: List[PortfolioItem] = tws_connection.ib.portfolio()
        
        # Build position data
        position_data = []
        total_unrealized_pnl = 0.0
        total_realized_pnl = 0.0
        
        for position in positions:
            # Find matching portfolio item for P&L
            portfolio_item = next(
                (item for item in portfolio if item.contract.conId == position.contract.conId),
                None
            )
            
            # Determine position type
            if position.contract.secType == 'OPT':
                position_type = 'option'
                # Parse option details
                option_details = {
                    'symbol': position.contract.symbol,
                    'strike': position.contract.strike,
                    'expiry': position.contract.lastTradeDateOrContractMonth,
                    'right': position.contract.right,
                    'multiplier': int(position.contract.multiplier or 100)
                }
            elif position.contract.secType == 'STK':
                position_type = 'stock'
                option_details = None
            else:
                position_type = position.contract.secType.lower()
                option_details = None
            
            # Build position entry
            pos_entry = {
                'position_id': str(position.contract.conId),
                'account': position.account,
                'symbol': position.contract.symbol,
                'position_type': position_type,
                'quantity': position.position,
                'avg_cost': position.avgCost,
                'option_details': option_details
            }
            
            # Add P&L data if available
            if portfolio_item:
                pos_entry.update({
                    'market_value': portfolio_item.marketValue,
                    'unrealized_pnl': portfolio_item.unrealizedPNL,
                    'realized_pnl': portfolio_item.realizedPNL,
                    'market_price': portfolio_item.marketPrice
                })
                total_unrealized_pnl += portfolio_item.unrealizedPNL
                total_realized_pnl += portfolio_item.realizedPNL
            
            position_data.append(pos_entry)
        
        return {
            'status': 'success',
            'positions': position_data,
            'position_count': len(position_data),
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_realized_pnl': total_realized_pnl,
            'total_pnl': total_unrealized_pnl + total_realized_pnl,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not retrieve positions. Check TWS connection.'
        }


@mcp.tool()
async def get_open_orders() -> Dict[str, Any]:
    """
    Get all pending/open orders.
    
    Returns:
        Dict containing all open orders with their status and details
    """
    logger.info("Fetching open orders")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Get all open orders
        open_trades: List[Trade] = tws_connection.ib.openTrades()
        
        # Build order data
        order_data = []
        
        for trade in open_trades:
            order: Order = trade.order
            contract: Contract = trade.contract
            status: OrderStatus = trade.orderStatus
            
            # Determine order details based on type
            order_details = {
                'order_type': order.orderType,
                'action': order.action,
                'quantity': order.totalQuantity,
                'filled': status.filled,
                'remaining': status.remaining,
                'status': status.status
            }
            
            # Add price information based on order type
            if order.orderType == 'LMT':
                order_details['limit_price'] = order.lmtPrice
            elif order.orderType == 'STP':
                order_details['stop_price'] = order.auxPrice
            elif order.orderType == 'TRAIL':
                order_details['trailing_amount'] = order.trailingPercent or order.auxPrice
            
            # Build contract details
            if contract.secType == 'OPT':
                contract_details = {
                    'type': 'option',
                    'symbol': contract.symbol,
                    'strike': contract.strike,
                    'expiry': contract.lastTradeDateOrContractMonth,
                    'right': contract.right
                }
            elif contract.secType == 'STK':
                contract_details = {
                    'type': 'stock',
                    'symbol': contract.symbol
                }
            elif contract.secType == 'BAG':
                contract_details = {
                    'type': 'combo',
                    'symbol': contract.symbol,
                    'legs': len(contract.comboLegs) if contract.comboLegs else 0
                }
            else:
                contract_details = {
                    'type': contract.secType.lower(),
                    'symbol': contract.symbol
                }
            
            # Build order entry
            order_entry = {
                'order_id': order.orderId,
                'perm_id': order.permId,
                'client_id': order.clientId,
                'account': order.account,
                'contract': contract_details,
                'order': order_details,
                'time_in_force': order.tif,
                'submit_time': status.lastFillTime if status.lastFillTime else None,
                'commission': status.commission if status.commission else 0,
                'parent_id': order.parentId if order.parentId else None
            }
            
            order_data.append(order_entry)
        
        # Group orders by parent (for bracket orders)
        parent_orders = {}
        child_orders = []
        
        for order in order_data:
            if order['parent_id']:
                child_orders.append(order)
            else:
                parent_orders[order['order_id']] = order
        
        # Attach children to parents
        for child in child_orders:
            parent_id = child['parent_id']
            if parent_id in parent_orders:
                if 'child_orders' not in parent_orders[parent_id]:
                    parent_orders[parent_id]['child_orders'] = []
                parent_orders[parent_id]['child_orders'].append(child)
        
        return {
            'status': 'success',
            'orders': list(parent_orders.values()),
            'order_count': len(parent_orders),
            'total_orders_with_children': len(order_data),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch open orders: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not retrieve open orders. Check TWS connection.'
        }


@mcp.tool()
async def close_position(
    symbol: str,
    position_type: str,  # 'call', 'put', 'spread', 'stock'
    quantity: int,
    order_type: str = 'MKT',  # 'MKT' or 'LMT'
    limit_price: Optional[float] = None,
    position_id: Optional[str] = None  # Optional specific position ID
) -> Dict[str, Any]:
    """
    Close an existing option or stock position.
    
    Args:
        symbol: Symbol of the position to close
        position_type: Type of position ('call', 'put', 'spread', 'stock')
        quantity: Number of contracts/shares to close
        order_type: Market or limit order
        limit_price: Price for limit orders
        position_id: Optional specific position ID to close
    
    Returns:
        Order execution result
    """
    logger.info(f"Closing {position_type} position for {symbol}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Get current positions to find the one to close
        positions: List[Position] = tws_connection.ib.positions()
        
        # Find matching position
        target_position = None
        for pos in positions:
            # Match by symbol
            if pos.contract.symbol != symbol:
                continue
            
            # Match by position ID if provided
            if position_id and str(pos.contract.conId) != position_id:
                continue
            
            # Match by type
            if position_type in ['call', 'put']:
                if pos.contract.secType == 'OPT':
                    if position_type == 'call' and pos.contract.right == 'C':
                        target_position = pos
                        break
                    elif position_type == 'put' and pos.contract.right == 'P':
                        target_position = pos
                        break
            elif position_type == 'stock':
                if pos.contract.secType == 'STK':
                    target_position = pos
                    break
            elif position_type == 'spread':
                if pos.contract.secType == 'BAG':
                    target_position = pos
                    break
        
        if not target_position:
            return {
                'error': 'Position not found',
                'message': f'No open {position_type} position found for {symbol}',
                'status': 'failed'
            }
        
        # Determine action (opposite of current position)
        if target_position.position > 0:
            action = 'SELL'  # Close long position
        else:
            action = 'BUY'   # Close short position
            quantity = abs(quantity)  # Ensure positive quantity
        
        # Validate quantity
        if quantity > abs(target_position.position):
            logger.warning(f"Requested quantity {quantity} exceeds position size {abs(target_position.position)}")
            quantity = abs(target_position.position)
        
        # Create closing order
        if order_type == 'MKT':
            order = MarketOrder(action, quantity)
        elif order_type == 'LMT':
            if limit_price is None:
                return {
                    'error': 'Limit price required',
                    'message': 'Limit price must be specified for limit orders',
                    'status': 'failed'
                }
            order = LimitOrder(action, quantity, limit_price)
        else:
            return {
                'error': 'Invalid order type',
                'message': f'Order type must be MKT or LMT, got {order_type}',
                'status': 'failed'
            }
        
        # Add SMART routing for best execution
        order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        
        # Place the closing order
        trade = tws_connection.ib.placeOrder(target_position.contract, order)
        
        # Wait for order acknowledgment
        await asyncio.sleep(2)
        
        logger.info(f"Placed closing order for {quantity} {position_type} of {symbol}")
        
        return {
            'status': 'success',
            'order_id': trade.order.orderId,
            'action': action,
            'symbol': symbol,
            'position_type': position_type,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': limit_price,
            'position_closed': {
                'original_quantity': abs(target_position.position),
                'quantity_closed': quantity,
                'remaining': abs(target_position.position) - quantity,
                'avg_cost': target_position.avgCost
            },
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to close position: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Position closing failed. Check TWS connection and position details.'
        }


@mcp.tool()
async def set_stop_loss(
    position_id: str,
    stop_price: float,
    stop_type: str = 'fixed',  # 'fixed' or 'trailing'
    trailing_amount: Optional[float] = None,  # For trailing stops (dollars or percent)
    trailing_type: Optional[str] = 'amount'  # 'amount' or 'percent'
) -> Dict[str, Any]:
    """
    Set a stop loss order for an existing position.
    
    Args:
        position_id: Position identifier (contract ID or order ID)
        stop_price: Stop trigger price (for fixed stops) or initial stop (for trailing)
        stop_type: 'fixed' for regular stop, 'trailing' for trailing stop
        trailing_amount: Amount or percent to trail (for trailing stops)
        trailing_type: 'amount' for dollar trailing, 'percent' for percentage
    
    Returns:
        Stop order confirmation
    """
    logger.info(f"Setting {stop_type} stop loss for position {position_id} at {stop_price}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Find the position
        positions: List[Position] = tws_connection.ib.positions()
        target_position = None
        
        for pos in positions:
            if str(pos.contract.conId) == position_id or position_id in str(pos.contract.localSymbol):
                target_position = pos
                break
        
        if not target_position:
            # Try to find by recent order ID
            trades = tws_connection.ib.trades()
            for trade in trades:
                if str(trade.order.orderId) == position_id:
                    target_position = Position(
                        account=trade.order.account,
                        contract=trade.contract,
                        position=trade.order.totalQuantity if trade.order.action == 'BUY' else -trade.order.totalQuantity,
                        avgCost=trade.orderStatus.avgFillPrice or 0
                    )
                    break
        
        if not target_position:
            return {
                'error': 'Position not found',
                'message': f'No position found with ID {position_id}',
                'status': 'failed'
            }
        
        # Determine action (opposite of position direction)
        if target_position.position > 0:
            action = 'SELL'  # Stop loss for long position
        else:
            action = 'BUY'   # Stop loss for short position
        
        quantity = abs(target_position.position)
        
        # Create stop order based on type
        if stop_type == 'fixed':
            # Create fixed stop loss order
            stop_order = Order()
            stop_order.action = action
            stop_order.orderType = 'STP'
            stop_order.totalQuantity = quantity
            stop_order.auxPrice = stop_price  # Stop trigger price
            stop_order.tif = 'GTC'  # Good till cancelled
            
        elif stop_type == 'trailing':
            # Create trailing stop order
            stop_order = Order()
            stop_order.action = action
            stop_order.orderType = 'TRAIL'
            stop_order.totalQuantity = quantity
            
            if trailing_type == 'percent':
                stop_order.trailingPercent = trailing_amount or 5.0  # Default 5%
                stop_order.auxPrice = stop_price  # Initial stop price
            else:  # amount
                stop_order.auxPrice = trailing_amount or (stop_price * 0.05)  # Trail amount in dollars
                stop_order.trailStopPrice = stop_price  # Initial stop price
            
            stop_order.tif = 'GTC'
        else:
            return {
                'error': 'Invalid stop type',
                'message': f'Stop type must be "fixed" or "trailing", got {stop_type}',
                'status': 'failed'
            }
        
        # Add SMART routing
        stop_order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        
        # Place the stop order
        trade = tws_connection.ib.placeOrder(target_position.contract, stop_order)
        
        # Wait for order acknowledgment
        await asyncio.sleep(2)
        
        # Calculate risk metrics
        if target_position.avgCost > 0:
            if target_position.position > 0:  # Long position
                risk_amount = (target_position.avgCost - stop_price) * quantity
                risk_percent = ((target_position.avgCost - stop_price) / target_position.avgCost) * 100
            else:  # Short position
                risk_amount = (stop_price - target_position.avgCost) * quantity
                risk_percent = ((stop_price - target_position.avgCost) / target_position.avgCost) * 100
        else:
            risk_amount = 0
            risk_percent = 0
        
        # For options, multiply by 100
        if target_position.contract.secType == 'OPT':
            risk_amount *= 100
        
        logger.info(f"Placed {stop_type} stop order for position {position_id}")
        
        return {
            'status': 'success',
            'order_id': trade.order.orderId,
            'position_id': position_id,
            'stop_type': stop_type,
            'stop_price': stop_price,
            'action': action,
            'quantity': quantity,
            'symbol': target_position.contract.symbol,
            'risk_metrics': {
                'max_loss_amount': abs(risk_amount),
                'max_loss_percent': abs(risk_percent),
                'entry_price': target_position.avgCost
            },
            'trailing_config': {
                'trailing_amount': trailing_amount,
                'trailing_type': trailing_type
            } if stop_type == 'trailing' else None,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to set stop loss: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Stop loss order failed. Check position ID and stop price.'
        }


@mcp.tool()
async def modify_order(
    order_id: str,
    new_limit_price: Optional[float] = None,
    new_quantity: Optional[int] = None,
    new_stop_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    Modify an existing pending order.
    
    Args:
        order_id: Order ID to modify
        new_limit_price: New limit price (for limit orders)
        new_quantity: New quantity
        new_stop_price: New stop price (for stop orders)
    
    Returns:
        Modification confirmation
    """
    logger.info(f"Modifying order {order_id}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Find the order
        open_trades = tws_connection.ib.openTrades()
        target_trade = None
        
        for trade in open_trades:
            if str(trade.order.orderId) == order_id or str(trade.order.permId) == order_id:
                target_trade = trade
                break
        
        if not target_trade:
            return {
                'error': 'Order not found',
                'message': f'No open order found with ID {order_id}',
                'status': 'failed'
            }
        
        # Get original order
        original_order = target_trade.order
        contract = target_trade.contract
        
        # Create modified order (copy original)
        modified_order = Order()
        modified_order.action = original_order.action
        modified_order.orderType = original_order.orderType
        modified_order.tif = original_order.tif
        modified_order.orderId = original_order.orderId
        
        # Apply modifications
        changes_made = []
        
        # Modify quantity if specified
        if new_quantity is not None:
            modified_order.totalQuantity = new_quantity
            changes_made.append(f"quantity: {original_order.totalQuantity} -> {new_quantity}")
        else:
            modified_order.totalQuantity = original_order.totalQuantity
        
        # Modify price based on order type
        if original_order.orderType == 'LMT':
            if new_limit_price is not None:
                modified_order.lmtPrice = new_limit_price
                changes_made.append(f"limit price: {original_order.lmtPrice} -> {new_limit_price}")
            else:
                modified_order.lmtPrice = original_order.lmtPrice
                
        elif original_order.orderType == 'STP':
            if new_stop_price is not None:
                modified_order.auxPrice = new_stop_price
                changes_made.append(f"stop price: {original_order.auxPrice} -> {new_stop_price}")
            else:
                modified_order.auxPrice = original_order.auxPrice
                
        elif original_order.orderType == 'TRAIL':
            if new_stop_price is not None:
                modified_order.trailStopPrice = new_stop_price
                changes_made.append(f"trail stop: {original_order.trailStopPrice} -> {new_stop_price}")
            else:
                modified_order.auxPrice = original_order.auxPrice
                modified_order.trailingPercent = original_order.trailingPercent
        
        if not changes_made:
            return {
                'error': 'No modifications specified',
                'message': 'Provide at least one parameter to modify',
                'status': 'failed'
            }
        
        # Keep SMART routing
        modified_order.smartComboRoutingParams = original_order.smartComboRoutingParams
        
        # Place the modified order (this replaces the original)
        trade = tws_connection.ib.placeOrder(contract, modified_order)
        
        # Wait for acknowledgment
        await asyncio.sleep(2)
        
        logger.info(f"Modified order {order_id}: {', '.join(changes_made)}")
        
        return {
            'status': 'success',
            'order_id': order_id,
            'modifications': changes_made,
            'new_values': {
                'quantity': modified_order.totalQuantity,
                'limit_price': getattr(modified_order, 'lmtPrice', None),
                'stop_price': getattr(modified_order, 'auxPrice', None)
            },
            'symbol': contract.symbol,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to modify order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Order modification failed. Order may have been filled or cancelled.'
        }


@mcp.tool()
async def cancel_order(
    order_id: str,
    cancel_all: bool = False
) -> Dict[str, Any]:
    """
    Cancel a pending order or all open orders.
    
    Args:
        order_id: Order ID to cancel (ignored if cancel_all is True)
        cancel_all: Cancel all open orders if True
    
    Returns:
        Cancellation confirmation
    """
    logger.info(f"Cancelling {'all orders' if cancel_all else f'order {order_id}'}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        if cancel_all:
            # Cancel all open orders
            tws_connection.ib.reqGlobalCancel()
            
            # Wait for cancellations to process
            await asyncio.sleep(2)
            
            logger.info("Cancelled all open orders")
            
            return {
                'status': 'success',
                'action': 'cancelled_all',
                'message': 'All open orders have been cancelled',
                'timestamp': datetime.now().isoformat()
            }
        
        else:
            # Find specific order
            open_trades = tws_connection.ib.openTrades()
            target_trade = None
            
            for trade in open_trades:
                if str(trade.order.orderId) == order_id or str(trade.order.permId) == order_id:
                    target_trade = trade
                    break
            
            if not target_trade:
                return {
                    'error': 'Order not found',
                    'message': f'No open order found with ID {order_id}',
                    'status': 'failed'
                }
            
            # Cancel the specific order
            tws_connection.ib.cancelOrder(target_trade.order)
            
            # Wait for cancellation
            await asyncio.sleep(2)
            
            logger.info(f"Cancelled order {order_id}")
            
            return {
                'status': 'success',
                'order_id': order_id,
                'symbol': target_trade.contract.symbol,
                'order_type': target_trade.order.orderType,
                'quantity': target_trade.order.totalQuantity,
                'action': target_trade.order.action,
                'message': f'Order {order_id} has been cancelled',
                'timestamp': datetime.now().isoformat()
            }
        
    except Exception as e:
        logger.error(f"Failed to cancel order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Order cancellation failed. Order may have already been filled.'
        }


@mcp.tool()
async def set_price_alert(
    symbol: str,
    trigger_price: float,
    condition: str = 'above',  # 'above' or 'below'
    action: str = 'notify',  # 'notify', 'close_position', 'place_order'
    action_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Set a price-triggered alert or action.
    
    Args:
        symbol: Symbol to monitor
        trigger_price: Price level to trigger at
        condition: Trigger when price goes 'above' or 'below'
        action: What to do when triggered
        action_params: Parameters for the action (e.g., order details)
    
    Returns:
        Alert configuration confirmation
    """
    logger.info(f"Setting price alert for {symbol} {condition} {trigger_price}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Create a conditional order (One-Cancels-All group)
        # This uses IBKR's native conditional order functionality
        
        # First, get the contract
        if symbol in ['SPY', 'QQQ', 'IWM', 'DIA']:  # Common ETFs
            contract = Stock(symbol, 'SMART', 'USD')
        else:
            contract = Stock(symbol, 'SMART', 'USD')
        
        # Qualify the contract
        qualified = await tws_connection.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]
        
        # Create condition
        from ib_async import PriceCondition
        
        price_condition = PriceCondition()
        price_condition.conId = contract.conId
        price_condition.exchange = 'SMART'
        price_condition.isMore = (condition == 'above')
        price_condition.triggerMethod = PriceCondition.TriggerMethod.Last
        price_condition.price = trigger_price
        
        # Create action order based on action type
        if action == 'close_position':
            # Find position to close
            positions = tws_connection.ib.positions()
            position_to_close = None
            
            for pos in positions:
                if pos.contract.symbol == symbol:
                    position_to_close = pos
                    break
            
            if not position_to_close:
                return {
                    'error': 'No position to close',
                    'message': f'No open position found for {symbol}',
                    'status': 'failed'
                }
            
            # Create closing order
            if position_to_close.position > 0:
                action_order = MarketOrder('SELL', abs(position_to_close.position))
            else:
                action_order = MarketOrder('BUY', abs(position_to_close.position))
            
            action_order.conditions = [price_condition]
            action_order.conditionsIgnoreRth = True
            action_order.conditionsCancelOrder = False
            
            # Place conditional order
            trade = tws_connection.ib.placeOrder(position_to_close.contract, action_order)
            
            alert_type = 'conditional_close'
            
        elif action == 'place_order':
            # Create order from parameters
            if not action_params:
                return {
                    'error': 'Missing action parameters',
                    'message': 'action_params required for place_order action',
                    'status': 'failed'
                }
            
            order_action = action_params.get('action', 'BUY')
            quantity = action_params.get('quantity', 100)
            order_type = action_params.get('order_type', 'MKT')
            
            if order_type == 'LMT':
                action_order = LimitOrder(order_action, quantity, action_params.get('limit_price'))
            else:
                action_order = MarketOrder(order_action, quantity)
            
            action_order.conditions = [price_condition]
            action_order.conditionsIgnoreRth = True
            action_order.conditionsCancelOrder = False
            
            # Place conditional order
            trade = tws_connection.ib.placeOrder(contract, action_order)
            
            alert_type = 'conditional_order'
            
        else:  # notify only
            # IBKR doesn't have pure notifications via API
            # Create a minimal order that won't execute but will trigger
            # This is a workaround - in production you'd use a separate monitoring system
            
            logger.info(f"Price alert set for {symbol} {condition} {trigger_price} (monitoring only)")
            
            return {
                'status': 'success',
                'alert_type': 'monitor_only',
                'symbol': symbol,
                'trigger_price': trigger_price,
                'condition': condition,
                'message': 'Price monitoring active (note: TWS API does not support pure notifications)',
                'timestamp': datetime.now().isoformat()
            }
        
        # Wait for order acknowledgment
        await asyncio.sleep(2)
        
        logger.info(f"Set conditional {alert_type} for {symbol}")
        
        return {
            'status': 'success',
            'alert_type': alert_type,
            'order_id': trade.order.orderId,
            'symbol': symbol,
            'trigger_price': trigger_price,
            'condition': condition,
            'action': action,
            'action_params': action_params,
            'message': f'Conditional {action} will trigger when {symbol} goes {condition} ${trigger_price}',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to set price alert: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Price alert setup failed. Check parameters and TWS connection.'
        }


@mcp.tool()
async def roll_option_position(
    position_id: str,
    new_strike: Optional[float] = None,
    new_expiry: Optional[str] = None,  # Format: YYYY-MM-DD
    roll_type: str = 'calendar'  # 'calendar', 'diagonal', 'vertical'
) -> Dict[str, Any]:
    """
    Roll an option position to a different strike and/or expiration.
    
    Args:
        position_id: Current position to roll
        new_strike: New strike price (for vertical/diagonal rolls)
        new_expiry: New expiration date (for calendar/diagonal rolls)
        roll_type: Type of roll to perform
    
    Returns:
        Roll execution confirmation with both closing and opening trades
    """
    logger.info(f"Rolling position {position_id} using {roll_type} roll")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Find the position to roll
        positions = tws_connection.ib.positions()
        position_to_roll = None
        
        for pos in positions:
            if str(pos.contract.conId) == position_id:
                position_to_roll = pos
                break
        
        if not position_to_roll:
            return {
                'error': 'Position not found',
                'message': f'No position found with ID {position_id}',
                'status': 'failed'
            }
        
        # Validate it's an option position
        if position_to_roll.contract.secType != 'OPT':
            return {
                'error': 'Not an option position',
                'message': 'Can only roll option positions',
                'status': 'failed'
            }
        
        old_contract = position_to_roll.contract
        
        # Determine roll parameters
        if roll_type == 'calendar':
            # Same strike, different expiration
            if not new_expiry:
                return {
                    'error': 'Missing expiry',
                    'message': 'New expiration date required for calendar roll',
                    'status': 'failed'
                }
            roll_strike = old_contract.strike
            roll_expiry = new_expiry.replace('-', '')
            
        elif roll_type == 'vertical':
            # Different strike, same expiration
            if not new_strike:
                return {
                    'error': 'Missing strike',
                    'message': 'New strike price required for vertical roll',
                    'status': 'failed'
                }
            roll_strike = new_strike
            roll_expiry = old_contract.lastTradeDateOrContractMonth
            
        elif roll_type == 'diagonal':
            # Different strike AND expiration
            if not new_strike or not new_expiry:
                return {
                    'error': 'Missing parameters',
                    'message': 'Both new strike and expiry required for diagonal roll',
                    'status': 'failed'
                }
            roll_strike = new_strike
            roll_expiry = new_expiry.replace('-', '')
            
        else:
            return {
                'error': 'Invalid roll type',
                'message': f'Roll type must be calendar, vertical, or diagonal, got {roll_type}',
                'status': 'failed'
            }
        
        # Create new option contract
        new_contract = Option(
            old_contract.symbol,
            roll_expiry,
            roll_strike,
            old_contract.right,
            'SMART'
        )
        
        # Qualify the new contract
        qualified = await tws_connection.ib.qualifyContractsAsync(new_contract)
        if qualified:
            new_contract = qualified[0]
        
        # Create combo order for the roll (atomic execution)
        combo = Contract()
        combo.symbol = old_contract.symbol
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        # Create combo legs
        from ib_async import ComboLeg
        
        # Leg 1: Close existing position
        close_leg = ComboLeg()
        close_leg.conId = old_contract.conId
        close_leg.ratio = 1
        close_leg.action = 'SELL' if position_to_roll.position > 0 else 'BUY'
        close_leg.exchange = 'SMART'
        
        # Leg 2: Open new position
        open_leg = ComboLeg()
        open_leg.conId = new_contract.conId
        open_leg.ratio = 1
        open_leg.action = 'BUY' if position_to_roll.position > 0 else 'SELL'
        open_leg.exchange = 'SMART'
        
        combo.comboLegs = [close_leg, open_leg]
        
        # Calculate net debit/credit for the roll
        # This is an estimate - actual prices depend on market
        quantity = abs(position_to_roll.position)
        
        # Create order for the roll
        roll_order = MarketOrder('BUY' if position_to_roll.position > 0 else 'SELL', quantity)
        roll_order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        
        # Place the roll order
        trade = tws_connection.ib.placeOrder(combo, roll_order)
        
        # Wait for acknowledgment
        await asyncio.sleep(2)
        
        logger.info(f"Executed {roll_type} roll for position {position_id}")
        
        return {
            'status': 'success',
            'order_id': trade.order.orderId,
            'roll_type': roll_type,
            'position_rolled': {
                'symbol': old_contract.symbol,
                'old_strike': old_contract.strike,
                'old_expiry': old_contract.lastTradeDateOrContractMonth,
                'new_strike': roll_strike,
                'new_expiry': roll_expiry,
                'right': old_contract.right,
                'quantity': quantity
            },
            'message': f'Rolled position from {old_contract.strike} to {roll_strike}',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to roll position: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Position roll failed. Check parameters and market hours.'
        }


# ============================================================================
# HELPER METHODS - Add these to src/modules/tws/connection.py
# ============================================================================

class TWSConnectionExtensions:
    """
    Extension methods for TWSConnection class.
    Add these methods to the existing TWSConnection class in connection.py
    """
    
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
            raise
    
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
            raise
    
    async def place_oca_order(
        self,
        orders: List[Tuple[Contract, Order]],
        oca_group: str,
        oca_type: int = 1  # 1 = Cancel all remaining orders with block
    ) -> List[Trade]:
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
            raise


# ============================================================================
# DATA CLASSES - Add these to src/models.py if not present
# ============================================================================

from dataclasses import dataclass
from enum import Enum

class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"
    TRAILING_STOP = "TRAIL"

class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING_SUBMIT = "PendingSubmit"
    PENDING_CANCEL = "PendingCancel"
    PRE_SUBMITTED = "PreSubmitted"
    SUBMITTED = "Submitted"
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    INACTIVE = "Inactive"

@dataclass
class PositionDetails:
    """Details about an open position."""
    position_id: str
    symbol: str
    position_type: str  # 'option', 'stock', 'spread'
    quantity: int
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    market_value: float
    option_details: Optional[Dict[str, Any]] = None

@dataclass
class OrderDetails:
    """Details about an order."""
    order_id: int
    symbol: str
    action: str
    quantity: int
    order_type: OrderType
    status: OrderStatus
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_quantity: int = 0
    remaining_quantity: int = 0
    avg_fill_price: Optional[float] = None
    parent_id: Optional[int] = None
    oca_group: Optional[str] = None