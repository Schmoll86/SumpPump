"""
Conditional order execution for IBKR TWS.
Implements price-based, time-based, and margin-based conditional orders.
Includes specific support for buy-to-close orders on short options.
"""

import asyncio
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, time
from loguru import logger

from ib_async import (
    Contract, Option, Stock, Order, Trade,
    MarketOrder, LimitOrder, StopOrder,
    TagValue, PriceCondition, TimeCondition, 
    MarginCondition, PercentChangeCondition
)


async def create_conditional_order(
    tws_connection,
    symbol: str,
    contract_type: str,  # 'STOCK', 'OPTION'
    action: str,  # 'BUY', 'SELL', 'BUY_TO_CLOSE', 'SELL_TO_CLOSE'
    quantity: int,
    order_type: str,  # 'MKT', 'LMT', 'STP', 'STP_LMT'
    conditions: List[Dict[str, Any]],  # List of condition specifications
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    # Option-specific parameters
    strike: Optional[float] = None,
    expiry: Optional[str] = None,  # YYYYMMDD format
    right: Optional[str] = None,  # 'C' or 'P'
    # Advanced parameters
    one_cancels_all: bool = False,
    trigger_method: str = 'Last',  # 'Last', 'DoubleLast', 'BidAsk', 'LastBidAsk', 'MidPoint'
    outside_rth: bool = False,  # Allow trigger outside regular trading hours
    parent_order_id: Optional[int] = None  # For bracket orders
) -> Dict[str, Any]:
    """
    Create a conditional order with multiple trigger conditions.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Underlying symbol
        contract_type: 'STOCK' or 'OPTION'
        action: Order action (BUY, SELL, BUY_TO_CLOSE, SELL_TO_CLOSE)
        quantity: Number of shares/contracts
        order_type: Order type (MKT, LMT, STP, STP_LMT)
        conditions: List of conditions, each dict containing:
            - type: 'price', 'time', 'margin', 'percent_change'
            - operator: 'above', 'below', 'at' (for price/margin)
            - value: Trigger value
            - conj_type: 'AND' or 'OR' (how to combine with other conditions)
        limit_price: Limit price for LMT orders
        stop_price: Stop price for STP orders
        strike: Option strike price
        expiry: Option expiration (YYYYMMDD)
        right: Option right ('C' or 'P')
        one_cancels_all: Create OCA group
        trigger_method: How to evaluate price conditions
        outside_rth: Allow triggering outside regular hours
        parent_order_id: Link to parent order for brackets
    
    Returns:
        Order confirmation with details
    """
    logger.info(f"Creating conditional {action} order for {quantity} {symbol}")
    
    try:
        await tws_connection.ensure_connected()
        
        # Create the contract
        if contract_type == 'OPTION':
            if not all([strike, expiry, right]):
                return {
                    'error': 'Missing option parameters',
                    'message': 'Strike, expiry, and right required for options',
                    'status': 'failed'
                }
            
            contract = Option(symbol, expiry, strike, right, 'SMART', currency='USD')
            
        else:  # STOCK
            contract = Stock(symbol, 'SMART', 'USD')
        
        # Qualify the contract
        qualified = await tws_connection.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]
        else:
            return {
                'error': 'Contract not found',
                'message': f'Could not qualify {contract_type} contract for {symbol}',
                'status': 'failed'
            }
        
        # Handle special actions
        if action == 'BUY_TO_CLOSE':
            # This is closing a short position
            action = 'BUY'
            is_closing = True
        elif action == 'SELL_TO_CLOSE':
            # This is closing a long position
            action = 'SELL'
            is_closing = True
        else:
            is_closing = False
        
        # Create the base order
        if order_type == 'MKT':
            order = MarketOrder(action, quantity)
            
        elif order_type == 'LMT':
            if limit_price is None:
                return {
                    'error': 'Missing limit price',
                    'message': 'Limit price required for LMT orders',
                    'status': 'failed'
                }
            order = LimitOrder(action, quantity, limit_price)
            
        elif order_type == 'STP':
            if stop_price is None:
                return {
                    'error': 'Missing stop price',
                    'message': 'Stop price required for STP orders',
                    'status': 'failed'
                }
            order = StopOrder(action, quantity, stop_price)
            
        elif order_type == 'STP_LMT':
            if stop_price is None or limit_price is None:
                return {
                    'error': 'Missing prices',
                    'message': 'Both stop and limit prices required for STP_LMT orders',
                    'status': 'failed'
                }
            order = Order()
            order.action = action
            order.orderType = 'STP LMT'
            order.totalQuantity = quantity
            order.auxPrice = stop_price
            order.lmtPrice = limit_price
            
        else:
            return {
                'error': 'Invalid order type',
                'message': f'Order type {order_type} not supported',
                'status': 'failed'
            }
        
        # Build conditions list
        order_conditions = []
        
        for i, cond_spec in enumerate(conditions):
            cond_type = cond_spec.get('type')
            
            if cond_type == 'price':
                # Create price condition
                price_cond = PriceCondition()
                price_cond.conId = contract.conId
                price_cond.exchange = contract.exchange or 'SMART'
                price_cond.isMore = (cond_spec.get('operator') == 'above')
                price_cond.price = cond_spec.get('value')
                
                # Set trigger method
                trigger_map = {
                    'Last': PriceCondition.TriggerMethod.Last,
                    'DoubleLast': PriceCondition.TriggerMethod.DoubleLast,
                    'BidAsk': PriceCondition.TriggerMethod.BidAsk,
                    'LastBidAsk': PriceCondition.TriggerMethod.LastBidAsk,
                    'MidPoint': PriceCondition.TriggerMethod.MidPoint
                }
                price_cond.triggerMethod = trigger_map.get(trigger_method, PriceCondition.TriggerMethod.Last)
                
                # Set conjunction type (how to combine with next condition)
                if i < len(conditions) - 1:
                    price_cond.conjunctionType = cond_spec.get('conj_type', 'AND')
                
                order_conditions.append(price_cond)
                
            elif cond_type == 'time':
                # Create time condition
                time_cond = TimeCondition()
                time_cond.isMore = True  # Trigger after specified time
                time_cond.time = cond_spec.get('value')  # Format: "YYYYMMDD HH:MM:SS"
                
                if i < len(conditions) - 1:
                    time_cond.conjunctionType = cond_spec.get('conj_type', 'AND')
                
                order_conditions.append(time_cond)
                
            elif cond_type == 'margin':
                # Create margin condition
                margin_cond = MarginCondition()
                margin_cond.isMore = (cond_spec.get('operator') == 'above')
                margin_cond.percent = cond_spec.get('value')
                
                if i < len(conditions) - 1:
                    margin_cond.conjunctionType = cond_spec.get('conj_type', 'AND')
                
                order_conditions.append(margin_cond)
                
            elif cond_type == 'percent_change':
                # Create percent change condition
                pct_cond = PercentChangeCondition()
                pct_cond.conId = contract.conId
                pct_cond.exchange = contract.exchange or 'SMART'
                pct_cond.isMore = (cond_spec.get('operator') == 'above')
                pct_cond.changePercent = cond_spec.get('value')
                
                if i < len(conditions) - 1:
                    pct_cond.conjunctionType = cond_spec.get('conj_type', 'AND')
                
                order_conditions.append(pct_cond)
        
        # Attach conditions to order
        if order_conditions:
            order.conditions = order_conditions
            order.conditionsIgnoreRth = outside_rth
            order.conditionsCancelOrder = False  # Don't cancel order if conditions become false
        
        # Set additional order attributes
        order.tif = 'GTC'  # Good Till Cancelled
        order.transmit = True
        # CRITICAL FIX: Add explicit account field
        order.account = "U16348403"
        
        # Add SMART routing
        order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        
        # Handle OCA group
        if one_cancels_all:
            import time
            oca_group = f"OCA_{symbol}_{int(time.time())}"
            order.ocaGroup = oca_group
            order.ocaType = 1  # Cancel all remaining orders with block
        
        # Link to parent order if specified
        if parent_order_id:
            order.parentId = parent_order_id
        
        # Place the conditional order
        trade = tws_connection.ib.placeOrder(contract, order)
        
        # Wait for order acknowledgment
        await asyncio.sleep(2)
        
        # Build condition summary
        condition_summary = []
        for cond in conditions:
            if cond['type'] == 'price':
                condition_summary.append(f"{symbol} {cond['operator']} ${cond['value']}")
            elif cond['type'] == 'time':
                condition_summary.append(f"after {cond['value']}")
            elif cond['type'] == 'margin':
                condition_summary.append(f"margin {cond['operator']} {cond['value']}%")
            elif cond['type'] == 'percent_change':
                condition_summary.append(f"{symbol} changes {cond['operator']} {cond['value']}%")
        
        logger.info(f"Placed conditional order {trade.order.orderId}: {' AND '.join(condition_summary)}")
        
        return {
            'status': 'success',
            'order_id': trade.order.orderId,
            'symbol': symbol,
            'contract_type': contract_type,
            'action': f"{action}{'_TO_CLOSE' if is_closing else ''}",
            'quantity': quantity,
            'order_type': order_type,
            'conditions': condition_summary,
            'trigger_method': trigger_method,
            'outside_rth': outside_rth,
            'prices': {
                'limit': limit_price,
                'stop': stop_price
            },
            'option_details': {
                'strike': strike,
                'expiry': expiry,
                'right': right
            } if contract_type == 'OPTION' else None,
            'message': f'Conditional order will execute when: {" AND ".join(condition_summary)}',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to create conditional order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Conditional order creation failed. Check parameters and connection.'
        }


async def create_buy_to_close_order(
    tws_connection,
    symbol: str,
    strike: float,
    expiry: str,  # YYYYMMDD
    right: str,  # 'C' or 'P'
    quantity: int,
    trigger_conditions: List[Dict[str, Any]],
    order_type: str = 'MKT',
    limit_price: Optional[float] = None,
    time_in_force: str = 'GTC'
) -> Dict[str, Any]:
    """
    Specialized function for creating buy-to-close orders on short options.
    This is commonly used to close short calls or puts when certain conditions are met.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Underlying symbol
        strike: Option strike price
        expiry: Option expiration (YYYYMMDD)
        right: 'C' for call, 'P' for put
        quantity: Number of contracts to close
        trigger_conditions: List of conditions to trigger the buy-to-close
        order_type: 'MKT' or 'LMT'
        limit_price: Limit price if using LMT order
        time_in_force: Order duration ('GTC', 'DAY', etc.)
    
    Returns:
        Order confirmation
    """
    logger.info(f"Creating buy-to-close order for {quantity} {symbol} {strike}{right} {expiry}")
    
    # Use the general conditional order function with BUY_TO_CLOSE action
    result = await create_conditional_order(
        tws_connection=tws_connection,
        symbol=symbol,
        contract_type='OPTION',
        action='BUY_TO_CLOSE',
        quantity=quantity,
        order_type=order_type,
        conditions=trigger_conditions,
        limit_price=limit_price,
        strike=strike,
        expiry=expiry,
        right=right,
        outside_rth=False,
        one_cancels_all=False
    )
    
    # Add specific buy-to-close context
    if result.get('status') == 'success':
        result['order_purpose'] = 'close_short_option'
        result['risk_reduction'] = True
        result['message'] = f'Buy-to-close order placed for {quantity} {symbol} {strike}{right} contracts'
    
    return result


async def create_protective_conditional(
    tws_connection,
    symbol: str,
    position_type: str,  # 'short_call', 'short_put', 'long_call', 'long_put'
    strike: float,
    expiry: str,
    quantity: int,
    protection_level: float,  # Price level to trigger protection
    protection_type: str = 'stop_loss'  # 'stop_loss', 'profit_target', 'both'
) -> Dict[str, Any]:
    """
    Create protective conditional orders for option positions.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Underlying symbol
        position_type: Type of option position
        strike: Option strike
        expiry: Option expiration
        quantity: Number of contracts
        protection_level: Price to trigger protection
        protection_type: Type of protection to apply
    
    Returns:
        Protection order details
    """
    logger.info(f"Creating protective conditional for {position_type} {symbol} position")
    
    try:
        # Determine right and action based on position type
        if 'call' in position_type:
            right = 'C'
        else:
            right = 'P'
        
        if 'short' in position_type:
            # Short position - need to buy to close
            action = 'BUY_TO_CLOSE'
            condition_operator = 'above' if protection_type == 'stop_loss' else 'below'
        else:
            # Long position - need to sell to close
            action = 'SELL_TO_CLOSE'
            condition_operator = 'below' if protection_type == 'stop_loss' else 'above'
        
        # Create protection conditions
        conditions = [{
            'type': 'price',
            'operator': condition_operator,
            'value': protection_level,
            'conj_type': 'AND'
        }]
        
        # Create the protective order
        result = await create_conditional_order(
            tws_connection=tws_connection,
            symbol=symbol,
            contract_type='OPTION',
            action=action,
            quantity=quantity,
            order_type='MKT',
            conditions=conditions,
            strike=strike,
            expiry=expiry,
            right=right
        )
        
        if result.get('status') == 'success':
            result['protection_type'] = protection_type
            result['protection_level'] = protection_level
            result['position_protected'] = position_type
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to create protective conditional: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Protective order creation failed.'
        }