"""
Direct execution module that bypasses problematic layers.
Provides raw, verified trade execution with minimal abstraction.
"""

import asyncio
from typing import Dict, Any, Optional, Union
from datetime import datetime
from loguru import logger
from decimal import Decimal

from ib_async import (
    Stock, Option, Contract,
    MarketOrder, LimitOrder, Order
)


async def direct_close_position(
    tws_connection,
    symbol: str,
    position_type: str,  # 'call', 'put', 'stock'
    strike: Optional[Union[float, int, str]] = None,
    expiry: Optional[str] = None,  # YYYYMMDD
    right: Optional[str] = None,  # 'C' or 'P'
    quantity: Union[int, str] = None,
    order_type: str = 'MKT',
    limit_price: Optional[Union[float, int, str, Decimal]] = None,
    bypass_safety: bool = False
) -> Dict[str, Any]:
    """
    Direct position close with minimal abstraction.
    Bypasses problematic validation layers.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Symbol to close
        position_type: Type of position
        strike: Option strike (for options)
        expiry: Option expiry (for options)
        right: Option right (for options)
        quantity: Quantity to close (auto-detect if None)
        order_type: MKT or LMT
        limit_price: Limit price for LMT orders
        bypass_safety: Skip safety checks (use with caution)
    
    Returns:
        Execution result with verification
    """
    logger.info(f"DIRECT EXECUTION: Closing {position_type} position for {symbol}")
    
    try:
        # Ensure connection
        if not tws_connection.ib.isConnected():
            await tws_connection.connect()
        
        # Convert types with maximum tolerance
        if quantity is not None:
            try:
                quantity = int(float(str(quantity)))
            except:
                logger.error(f"Cannot parse quantity: {quantity}")
                return {'status': 'failed', 'error': 'INVALID_QUANTITY'}
        
        if limit_price is not None:
            try:
                # Handle all possible numeric representations
                if isinstance(limit_price, str):
                    limit_price = limit_price.replace(',', '')  # Remove commas
                limit_price = float(str(limit_price))
            except:
                logger.error(f"Cannot parse limit_price: {limit_price}")
                return {'status': 'failed', 'error': 'INVALID_LIMIT_PRICE'}
        
        if strike is not None:
            try:
                strike = float(str(strike))
            except:
                logger.error(f"Cannot parse strike: {strike}")
                return {'status': 'failed', 'error': 'INVALID_STRIKE'}
        
        # Find the position
        positions = tws_connection.ib.positions()
        target_position = None
        
        for pos in positions:
            if pos.contract.symbol != symbol:
                continue
            
            # Match by type
            if position_type in ['call', 'put']:
                if pos.contract.secType == 'OPT':
                    # Check strike and right if provided
                    if strike and abs(pos.contract.strike - strike) > 0.01:
                        continue
                    if right and pos.contract.right != right:
                        continue
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
        
        if not target_position:
            logger.error(f"No position found for {symbol} {position_type}")
            return {
                'status': 'failed',
                'error': 'POSITION_NOT_FOUND',
                'message': f'No {position_type} position found for {symbol}',
                'available_positions': [
                    f"{p.contract.symbol} {p.contract.secType} {p.position}" 
                    for p in positions
                ]
            }
        
        # Use actual position size if quantity not specified
        if quantity is None:
            quantity = abs(target_position.position)
        else:
            quantity = min(quantity, abs(target_position.position))
        
        # Determine action (opposite of position)
        if target_position.position > 0:
            action = 'SELL'  # Close long
        else:
            action = 'BUY'   # Close short
        
        logger.info(f"Found position: {target_position.position} contracts/shares")
        logger.info(f"Will {action} {quantity} to close")
        
        # Create order
        if order_type == 'MKT':
            order = MarketOrder(action, quantity)
        elif order_type == 'LMT':
            if limit_price is None:
                logger.error("Limit order requires limit_price")
                return {
                    'status': 'failed',
                    'error': 'MISSING_LIMIT_PRICE',
                    'message': 'Limit orders require limit_price parameter'
                }
            order = LimitOrder(action, quantity, limit_price)
        else:
            logger.error(f"Invalid order type: {order_type}")
            return {
                'status': 'failed',
                'error': 'INVALID_ORDER_TYPE',
                'message': f'Order type must be MKT or LMT, got {order_type}'
            }
        
        # Add account and time_in_force
        # Get account from tws_connection or fallback
        order.account = getattr(tws_connection, 'account_id', "U16348403")
        order.tif = "GTC"  # Good Till Cancelled
        order.transmit = True  # Transmit order immediately
        
        # Get initial position for verification
        initial_position = target_position.position
        
        # Place the order
        logger.info(f"Placing {order_type} order: {action} {quantity} {symbol}")
        trade = tws_connection.ib.placeOrder(target_position.contract, order)
        order_id = trade.order.orderId
        
        logger.info(f"Order {order_id} placed, waiting for execution...")
        
        # Wait for fill with timeout
        filled = False
        for i in range(20):  # 10 seconds total
            await asyncio.sleep(0.5)
            
            # Check order status
            if trade.orderStatus.status == 'Filled':
                filled = True
                break
            elif trade.orderStatus.status in ['Cancelled', 'ApiCancelled', 'Inactive']:
                logger.error(f"Order failed with status: {trade.orderStatus.status}")
                return {
                    'status': 'failed',
                    'error': 'ORDER_REJECTED',
                    'message': f'Order rejected: {trade.orderStatus.status}',
                    'order_id': order_id
                }
        
        # Check if position actually changed
        await asyncio.sleep(1)  # Give it a moment to update
        current_positions = tws_connection.ib.positions()
        current_position = 0
        
        for pos in current_positions:
            if pos.contract.symbol == symbol:
                if position_type in ['call', 'put']:
                    if pos.contract.secType == 'OPT':
                        if strike and abs(pos.contract.strike - strike) > 0.01:
                            continue
                        if right and pos.contract.right != right:
                            continue
                        current_position = pos.position
                        break
                elif position_type == 'stock':
                    if pos.contract.secType == 'STK':
                        current_position = pos.position
                        break
        
        position_change = current_position - initial_position
        
        if abs(position_change) > 0 or filled:
            # Success!
            result = {
                'status': 'success',
                'order_id': order_id,
                'action': action,
                'symbol': symbol,
                'position_type': position_type,
                'quantity_ordered': quantity,
                'quantity_filled': trade.orderStatus.filled,
                'order_type': order_type,
                'limit_price': limit_price,
                'avg_fill_price': trade.orderStatus.avgFillPrice,
                'position_before': initial_position,
                'position_after': current_position,
                'position_change': position_change,
                'verified': True,
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"✅ VERIFIED: Position changed from {initial_position} to {current_position}")
            return result
        else:
            # Order placed but not verified
            logger.warning(f"⚠️ Order placed but execution not verified")
            return {
                'status': 'unverified',
                'order_id': order_id,
                'message': 'Order placed but execution not confirmed',
                'order_status': trade.orderStatus.status,
                'position_before': initial_position,
                'position_after': current_position
            }
            
    except Exception as e:
        logger.error(f"Direct execution failed: {e}")
        import traceback
        return {
            'status': 'failed',
            'error': 'EXECUTION_ERROR',
            'message': str(e),
            'traceback': traceback.format_exc()
        }


async def emergency_market_close(
    tws_connection,
    symbol: str,
    force: bool = False
) -> Dict[str, Any]:
    """
    Emergency close ALL positions for a symbol using market orders.
    USE WITH EXTREME CAUTION.
    
    Args:
        tws_connection: Active TWS connection
        symbol: Symbol to close all positions
        force: Skip all safety checks
    
    Returns:
        Execution results
    """
    logger.warning(f"🚨 EMERGENCY CLOSE for {symbol}")
    
    if not force:
        logger.error("Emergency close requires force=True")
        return {
            'status': 'blocked',
            'error': 'SAFETY_CHECK',
            'message': 'Emergency close requires force=True parameter'
        }
    
    results = []
    positions = tws_connection.ib.positions()
    
    for pos in positions:
        if pos.contract.symbol == symbol and pos.position != 0:
            logger.info(f"Closing: {pos.contract.localSymbol} position={pos.position}")
            
            # Determine position type
            if pos.contract.secType == 'OPT':
                position_type = 'call' if pos.contract.right == 'C' else 'put'
            else:
                position_type = 'stock'
            
            result = await direct_close_position(
                tws_connection,
                symbol,
                position_type,
                strike=pos.contract.strike if pos.contract.secType == 'OPT' else None,
                right=pos.contract.right if pos.contract.secType == 'OPT' else None,
                quantity=abs(pos.position),
                order_type='MKT',
                bypass_safety=True
            )
            
            results.append(result)
    
    return {
        'status': 'completed',
        'symbol': symbol,
        'positions_closed': len(results),
        'results': results,
        'timestamp': datetime.now().isoformat()
    }