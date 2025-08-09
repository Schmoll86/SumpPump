"""
Position adjustment module.
Handles rolling, resizing, hedging, and partial closing of positions.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from loguru import logger
from ib_async import Option, Stock, Order, MarketOrder, LimitOrder, Position

from src.modules.tws.connection import get_tws_connection


@dataclass
class AdjustmentResult:
    """Result of position adjustment calculation."""
    adjustment_type: str
    current_position: Dict[str, Any]
    new_position: Dict[str, Any]
    orders: List[Dict[str, Any]]
    net_cost: float
    commission_estimate: float
    break_even_change: float
    max_loss_change: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP response."""
        return {
            'adjustment_type': self.adjustment_type,
            'current_position': self.current_position,
            'new_position': self.new_position,
            'orders': self.orders,
            'net_cost': round(self.net_cost, 2),
            'commission_estimate': round(self.commission_estimate, 2),
            'break_even_change': round(self.break_even_change, 2),
            'max_loss_change': round(self.max_loss_change, 2)
        }


class PositionAdjuster:
    """Handles position adjustments."""
    
    def __init__(self):
        """Initialize position adjuster."""
        self.tws = None
        
    async def _ensure_connection(self):
        """Ensure TWS connection is established."""
        if not self.tws:
            self.tws = await get_tws_connection()
    
    async def calculate_roll(
        self,
        position: Position,
        new_expiry: str,
        new_strike: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate option roll adjustment.
        
        Args:
            position: Current position to roll
            new_expiry: New expiration date (YYYYMMDD)
            new_strike: New strike price (optional, defaults to same)
            
        Returns:
            Adjustment details with orders
        """
        await self._ensure_connection()
        
        logger.info(f"[ADJUST] Calculating roll to {new_expiry} strike {new_strike}")
        
        contract = position.contract
        
        # For options, create new contract
        if contract.secType == 'OPT':
            old_option = contract
            
            # Create new option contract
            new_option = Option(
                symbol=old_option.symbol,
                lastTradeDateOrContractMonth=new_expiry,
                strike=new_strike or old_option.strike,
                right=old_option.right,
                exchange=old_option.exchange
            )
            
            # Get current prices
            ib = self.tws.ib
            
            # Get quotes for both
            old_ticker = ib.reqMktData(old_option, snapshot=True)
            new_ticker = ib.reqMktData(new_option, snapshot=True)
            
            await asyncio.sleep(2)  # Wait for data
            
            # Calculate roll cost
            close_cost = old_ticker.ask * abs(position.position) * 100
            open_cost = new_ticker.ask * abs(position.position) * 100
            net_cost = open_cost - close_cost
            
            logger.debug(f"[ADJUST] Roll cost: Close ${close_cost:.2f}, Open ${open_cost:.2f}, Net ${net_cost:.2f}")
            
            # Create orders
            orders = [
                {
                    'action': 'SELL' if position.position > 0 else 'BUY',
                    'quantity': abs(position.position),
                    'contract': old_option,
                    'order_type': 'MKT',
                    'description': f'Close {old_option.symbol} {old_option.strike} {old_option.lastTradeDateOrContractMonth}'
                },
                {
                    'action': 'BUY' if position.position > 0 else 'SELL',
                    'quantity': abs(position.position),
                    'contract': new_option,
                    'order_type': 'MKT',
                    'description': f'Open {new_option.symbol} {new_option.strike} {new_expiry}'
                }
            ]
            
            result = AdjustmentResult(
                adjustment_type='roll',
                current_position={
                    'symbol': old_option.symbol,
                    'strike': old_option.strike,
                    'expiry': old_option.lastTradeDateOrContractMonth,
                    'quantity': position.position
                },
                new_position={
                    'symbol': new_option.symbol,
                    'strike': new_strike or old_option.strike,
                    'expiry': new_expiry,
                    'quantity': position.position
                },
                orders=orders,
                net_cost=net_cost,
                commission_estimate=2.0,  # Estimate
                break_even_change=(new_strike or old_option.strike) - old_option.strike,
                max_loss_change=net_cost
            )
            
            logger.info(f"[ADJUST] Roll calculated: {len(orders)} orders, net cost ${net_cost:.2f}")
            
            return result.to_dict()
            
        else:
            raise ValueError(f"Cannot roll non-option position: {contract.secType}")
    
    async def calculate_resize(
        self,
        position: Position,
        new_quantity: int
    ) -> Dict[str, Any]:
        """
        Calculate position resize (scale in/out).
        
        Args:
            position: Current position
            new_quantity: Target quantity
            
        Returns:
            Adjustment details
        """
        await self._ensure_connection()
        
        current_qty = position.position
        qty_change = new_quantity - current_qty
        
        logger.info(f"[ADJUST] Resizing from {current_qty} to {new_quantity} (change: {qty_change})")
        
        if qty_change == 0:
            return {
                'status': 'no_change',
                'message': 'New quantity equals current quantity'
            }
        
        contract = position.contract
        
        # Get current price
        ib = self.tws.ib
        ticker = ib.reqMktData(contract, snapshot=True)
        await asyncio.sleep(2)
        
        # Determine action
        if qty_change > 0:
            # Adding to position
            action = 'BUY' if current_qty >= 0 else 'SELL'
            price = ticker.ask
        else:
            # Reducing position
            action = 'SELL' if current_qty > 0 else 'BUY'
            price = ticker.bid
            
        cost = abs(qty_change) * price * (100 if contract.secType == 'OPT' else 1)
        
        logger.debug(f"[ADJUST] Resize: {action} {abs(qty_change)} @ ${price:.2f}, cost ${cost:.2f}")
        
        orders = [{
            'action': action,
            'quantity': abs(qty_change),
            'contract': contract,
            'order_type': 'MKT',
            'description': f"{'Scale into' if qty_change > 0 else 'Scale out of'} {contract.symbol}"
        }]
        
        result = AdjustmentResult(
            adjustment_type='resize',
            current_position={
                'symbol': contract.symbol,
                'quantity': current_qty,
                'avg_cost': position.avgCost
            },
            new_position={
                'symbol': contract.symbol,
                'quantity': new_quantity,
                'avg_cost': ((position.avgCost * abs(current_qty)) + (price * abs(qty_change))) / abs(new_quantity) if new_quantity != 0 else 0
            },
            orders=orders,
            net_cost=cost if qty_change > 0 else -cost,
            commission_estimate=1.0,
            break_even_change=0,
            max_loss_change=cost if qty_change > 0 else 0
        )
        
        return result.to_dict()
    
    async def calculate_hedge(
        self,
        position: Position,
        hedge_type: str,
        strike: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate hedge for position.
        
        Args:
            position: Position to hedge
            hedge_type: Type of hedge (protective_put, covered_call)
            strike: Strike price for hedge
            
        Returns:
            Hedge details
        """
        await self._ensure_connection()
        
        logger.info(f"[ADJUST] Calculating {hedge_type} hedge")
        
        contract = position.contract
        
        if contract.secType != 'STK':
            return {
                'status': 'error',
                'message': 'Can only hedge stock positions'
            }
        
        # Get current stock price
        ib = self.tws.ib
        ticker = ib.reqMktData(contract, snapshot=True)
        await asyncio.sleep(2)
        
        current_price = ticker.last or ticker.close
        
        # Determine hedge parameters
        if hedge_type == 'protective_put':
            # Buy puts to protect long stock
            if position.position <= 0:
                return {'status': 'error', 'message': 'Protective puts only for long stock'}
                
            option_right = 'P'
            option_action = 'BUY'
            default_strike = round(current_price * 0.95, 0)  # 5% OTM
            
        elif hedge_type == 'covered_call':
            # Sell calls against long stock
            if position.position <= 0:
                return {'status': 'error', 'message': 'Covered calls only for long stock'}
                
            option_right = 'C'
            option_action = 'SELL'
            default_strike = round(current_price * 1.05, 0)  # 5% OTM
            
        else:
            return {'status': 'error', 'message': f'Unknown hedge type: {hedge_type}'}
        
        # Use provided strike or default
        hedge_strike = strike or default_strike
        
        # Calculate contracts needed (1 option per 100 shares)
        contracts_needed = abs(position.position) // 100
        
        if contracts_needed == 0:
            return {'status': 'error', 'message': 'Position too small to hedge (need 100+ shares)'}
        
        # Create hedge option (30 days out)
        expiry = (datetime.now() + timedelta(days=30)).strftime('%Y%m%d')
        
        hedge_option = Option(
            symbol=contract.symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=hedge_strike,
            right=option_right,
            exchange='SMART'
        )
        
        # Get option price
        opt_ticker = ib.reqMktData(hedge_option, snapshot=True)
        await asyncio.sleep(2)
        
        option_price = opt_ticker.ask if option_action == 'BUY' else opt_ticker.bid
        hedge_cost = contracts_needed * option_price * 100
        
        logger.debug(f"[ADJUST] Hedge: {option_action} {contracts_needed} {hedge_strike} {option_right} @ ${option_price:.2f}")
        
        orders = [{
            'action': option_action,
            'quantity': contracts_needed,
            'contract': hedge_option,
            'order_type': 'MKT',
            'description': f'{hedge_type} for {position.position} shares of {contract.symbol}'
        }]
        
        result = AdjustmentResult(
            adjustment_type='hedge',
            current_position={
                'symbol': contract.symbol,
                'quantity': position.position,
                'unhedged': True
            },
            new_position={
                'symbol': contract.symbol,
                'quantity': position.position,
                'hedge': f'{contracts_needed} {hedge_strike} {option_right}',
                'hedged': True
            },
            orders=orders,
            net_cost=hedge_cost if option_action == 'BUY' else -hedge_cost,
            commission_estimate=1.0,
            break_even_change=hedge_cost / position.position if option_action == 'BUY' else 0,
            max_loss_change=-hedge_cost if hedge_type == 'protective_put' else 0
        )
        
        return result.to_dict()
    
    async def calculate_partial_close(
        self,
        position: Position,
        quantity_to_close: int
    ) -> Dict[str, Any]:
        """
        Calculate partial position close.
        
        Args:
            position: Current position
            quantity_to_close: Quantity to close
            
        Returns:
            Close details
        """
        await self._ensure_connection()
        
        if abs(quantity_to_close) > abs(position.position):
            return {
                'status': 'error',
                'message': f'Cannot close {quantity_to_close}, position is only {position.position}'
            }
        
        logger.info(f"[ADJUST] Partial close {quantity_to_close} of {position.position}")
        
        contract = position.contract
        
        # Get current price
        ib = self.tws.ib
        ticker = ib.reqMktData(contract, snapshot=True)
        await asyncio.sleep(2)
        
        # Determine action (opposite of position)
        if position.position > 0:
            action = 'SELL'
            price = ticker.bid
        else:
            action = 'BUY'
            price = ticker.ask
        
        # Calculate P&L
        close_value = abs(quantity_to_close) * price * (100 if contract.secType == 'OPT' else 1)
        cost_basis = abs(quantity_to_close) * position.avgCost * (100 if contract.secType == 'OPT' else 1)
        estimated_pnl = close_value - cost_basis if position.position > 0 else cost_basis - close_value
        
        logger.debug(f"[ADJUST] Partial close: {action} {abs(quantity_to_close)} @ ${price:.2f}, Est P&L: ${estimated_pnl:.2f}")
        
        orders = [{
            'action': action,
            'quantity': abs(quantity_to_close),
            'contract': contract,
            'order_type': 'MKT',
            'description': f'Partial close {abs(quantity_to_close)} of {contract.symbol}'
        }]
        
        remaining = position.position - quantity_to_close if position.position > 0 else position.position + quantity_to_close
        
        result = AdjustmentResult(
            adjustment_type='partial_close',
            current_position={
                'symbol': contract.symbol,
                'quantity': position.position,
                'avg_cost': position.avgCost
            },
            new_position={
                'symbol': contract.symbol,
                'quantity': remaining,
                'avg_cost': position.avgCost
            },
            orders=orders,
            net_cost=-close_value if position.position > 0 else close_value,
            commission_estimate=1.0,
            break_even_change=0,
            max_loss_change=0
        )
        
        result_dict = result.to_dict()
        result_dict['estimated_pnl'] = round(estimated_pnl, 2)
        
        return result_dict