"""
Execution verification and health check utilities.
Ensures trades actually execute and don't return false positives.
"""

import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from loguru import logger
from ib_async import Position, Trade, OrderStatus


async def verify_order_executed(
    tws_connection,
    order_id: int,
    expected_symbol: str,
    expected_quantity: int,
    initial_positions: Optional[List[Position]] = None,
    timeout: int = 10,
    poll_interval: float = 0.5
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verify that an order actually executed by checking:
    1. Order status shows filled
    2. Position changed as expected
    3. Fill confirmation received
    
    Args:
        tws_connection: Active TWS connection
        order_id: Order ID to verify
        expected_symbol: Symbol that should have changed
        expected_quantity: Expected position change
        initial_positions: Positions before order (if available)
        timeout: Max seconds to wait for execution
        poll_interval: Seconds between checks
    
    Returns:
        (success, message, execution_details)
    """
    logger.info(f"Verifying execution of order {order_id} for {expected_symbol}")
    
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=timeout)
    
    # Get initial positions if not provided
    if initial_positions is None:
        initial_positions = tws_connection.ib.positions()
    
    initial_position = 0
    for pos in initial_positions:
        if pos.contract.symbol == expected_symbol:
            initial_position = pos.position
            break
    
    while datetime.now() < end_time:
        try:
            # Check order status
            open_trades = tws_connection.ib.openTrades()
            for trade in open_trades:
                if trade.order.orderId == order_id:
                    status = trade.orderStatus.status
                    
                    # Check if filled
                    if status == 'Filled':
                        # Verify position changed
                        current_positions = tws_connection.ib.positions()
                        current_position = 0
                        
                        for pos in current_positions:
                            if pos.contract.symbol == expected_symbol:
                                current_position = pos.position
                                break
                        
                        position_change = current_position - initial_position
                        
                        if abs(position_change) > 0:
                            execution_details = {
                                'order_id': order_id,
                                'symbol': expected_symbol,
                                'status': 'FILLED',
                                'filled_quantity': trade.orderStatus.filled,
                                'avg_fill_price': trade.orderStatus.avgFillPrice,
                                'position_before': initial_position,
                                'position_after': current_position,
                                'position_change': position_change,
                                'verification': 'CONFIRMED',
                                'timestamp': datetime.now().isoformat()
                            }
                            
                            logger.info(f"✅ Order {order_id} VERIFIED: Position changed by {position_change}")
                            return True, f"Order filled and verified", execution_details
                        else:
                            logger.warning(f"Order shows filled but position unchanged")
                            # Continue checking - might be processing
                    
                    elif status in ['Cancelled', 'ApiCancelled']:
                        logger.error(f"Order {order_id} was cancelled")
                        return False, f"Order cancelled: {status}", None
                    
                    elif status == 'Inactive':
                        logger.error(f"Order {order_id} is inactive")
                        return False, "Order inactive - may have been rejected", None
            
            # Small delay before next check
            await asyncio.sleep(poll_interval)
            
        except Exception as e:
            logger.error(f"Error checking order status: {e}")
            # Continue trying
        
    # Timeout - check final state
    final_positions = tws_connection.ib.positions()
    final_position = 0
    
    for pos in final_positions:
        if pos.contract.symbol == expected_symbol:
            final_position = pos.position
            break
    
    if final_position != initial_position:
        # Position did change even if we didn't catch the fill
        execution_details = {
            'order_id': order_id,
            'symbol': expected_symbol,
            'status': 'LIKELY_FILLED',
            'position_before': initial_position,
            'position_after': final_position,
            'position_change': final_position - initial_position,
            'verification': 'POSITION_CHANGED',
            'timestamp': datetime.now().isoformat()
        }
        logger.warning(f"Position changed but fill not confirmed for order {order_id}")
        return True, "Position changed indicating likely execution", execution_details
    
    logger.error(f"❌ Order {order_id} verification FAILED - no execution detected")
    return False, f"Order not executed after {timeout} seconds", None


async def check_tws_health(tws_connection) -> Tuple[bool, Dict[str, Any]]:
    """
    Comprehensive TWS connection health check.
    
    Returns:
        (is_healthy, health_details)
    """
    health_report = {
        'connected': False,
        'account_data': False,
        'market_data': False,
        'positions_readable': False,
        'orders_readable': False,
        'api_version': None,
        'account_id': None,
        'errors': [],
        'timestamp': datetime.now().isoformat()
    }
    
    try:
        # Check basic connection
        if not tws_connection.ib.isConnected():
            health_report['errors'].append("Not connected to TWS")
            return False, health_report
        
        health_report['connected'] = True
        
        # Check API version
        client = tws_connection.ib.client
        if client:
            health_report['api_version'] = client.serverVersion()
        
        # Check account access
        accounts = tws_connection.ib.managedAccounts()
        if accounts:
            health_report['account_id'] = accounts[0] if accounts else None
            health_report['account_data'] = True
        else:
            health_report['errors'].append("No managed accounts found")
        
        # Check positions access
        try:
            positions = tws_connection.ib.positions()
            health_report['positions_readable'] = True
            health_report['position_count'] = len(positions)
        except Exception as e:
            health_report['errors'].append(f"Cannot read positions: {e}")
        
        # Check orders access
        try:
            orders = tws_connection.ib.openOrders()
            health_report['orders_readable'] = True
            health_report['open_order_count'] = len(orders)
        except Exception as e:
            health_report['errors'].append(f"Cannot read orders: {e}")
        
        # Test market data with SPY
        try:
            from ib_async import Stock
            spy = Stock('SPY', 'SMART', 'USD')
            ticker = tws_connection.ib.reqMktData(spy, '', False, False)
            await asyncio.sleep(2)
            
            if ticker.bid or ticker.ask or ticker.last:
                health_report['market_data'] = True
                health_report['spy_quote'] = {
                    'bid': ticker.bid,
                    'ask': ticker.ask,
                    'last': ticker.last
                }
            else:
                health_report['errors'].append("No market data received for SPY")
            
            tws_connection.ib.cancelMktData(spy)
            
        except Exception as e:
            health_report['errors'].append(f"Market data test failed: {e}")
        
        # Overall health determination
        is_healthy = (
            health_report['connected'] and
            health_report['account_data'] and
            health_report['positions_readable'] and
            health_report['orders_readable']
        )
        
        if is_healthy:
            logger.info("✅ TWS connection healthy")
        else:
            logger.warning(f"⚠️ TWS connection issues: {health_report['errors']}")
        
        return is_healthy, health_report
        
    except Exception as e:
        health_report['errors'].append(f"Health check failed: {e}")
        logger.error(f"TWS health check error: {e}")
        return False, health_report


async def execute_with_verification(
    tws_connection,
    contract,
    order,
    expected_symbol: str,
    expected_quantity: int,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Execute an order and verify it actually fills.
    
    Args:
        tws_connection: Active TWS connection
        contract: IB contract object
        order: IB order object
        expected_symbol: Symbol expecting to change
        expected_quantity: Expected position change
        max_retries: Max attempts if order fails
    
    Returns:
        Execution result with verification
    """
    logger.info(f"Executing order with verification for {expected_symbol}")
    
    # First check connection health
    is_healthy, health = await check_tws_health(tws_connection)
    if not is_healthy:
        return {
            'status': 'failed',
            'error': 'TWS_UNHEALTHY',
            'message': f"TWS connection issues: {health['errors']}",
            'health_report': health
        }
    
    # Get initial positions
    initial_positions = tws_connection.ib.positions()
    
    for attempt in range(max_retries):
        try:
            # Place the order
            trade = tws_connection.ib.placeOrder(contract, order)
            order_id = trade.order.orderId
            
            logger.info(f"Order {order_id} placed, verifying execution...")
            
            # Wait a moment for order to be acknowledged
            await asyncio.sleep(1)
            
            # Verify execution
            verified, message, details = await verify_order_executed(
                tws_connection,
                order_id,
                expected_symbol,
                expected_quantity,
                initial_positions,
                timeout=15
            )
            
            if verified:
                return {
                    'status': 'success',
                    'order_id': order_id,
                    'message': message,
                    'execution_details': details,
                    'verified': True,
                    'attempt': attempt + 1
                }
            else:
                logger.warning(f"Attempt {attempt + 1} failed: {message}")
                
                # Cancel the failed order
                try:
                    tws_connection.ib.cancelOrder(trade.order)
                    await asyncio.sleep(2)
                except:
                    pass
                
                if attempt < max_retries - 1:
                    logger.info("Retrying order...")
                    await asyncio.sleep(3)
                
        except Exception as e:
            logger.error(f"Order execution error on attempt {attempt + 1}: {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
    
    return {
        'status': 'failed',
        'error': 'EXECUTION_FAILED',
        'message': f"Order failed after {max_retries} attempts",
        'last_error': str(e) if 'e' in locals() else 'Unknown error'
    }