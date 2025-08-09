"""
Portfolio-level data aggregation and analysis.
Provides comprehensive portfolio summary with P&L and Greeks.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass, asdict

from loguru import logger
from ib_async import Contract, Option, Stock

from src.modules.tws.connection import get_tws_connection
# Type coercion not needed - using ib_async types directly


@dataclass
class PortfolioGreeks:
    """Aggregate Greeks for entire portfolio."""
    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0
    total_rho: float = 0.0
    beta_weighted_delta: Optional[float] = None
    positions_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP response."""
        return {
            'total_delta': round(self.total_delta, 4),
            'total_gamma': round(self.total_gamma, 4),
            'total_theta': round(self.total_theta, 4),
            'total_vega': round(self.total_vega, 4),
            'total_rho': round(self.total_rho, 4),
            'beta_weighted_delta': round(self.beta_weighted_delta, 4) if self.beta_weighted_delta else None,
            'positions_count': self.positions_count
        }


@dataclass
class PortfolioSummary:
    """Complete portfolio summary with P&L and risk metrics."""
    account_id: str
    timestamp: datetime
    total_value: float
    total_cash: float
    buying_power: float
    maintenance_margin: float
    positions: List[Dict[str, Any]]
    realized_pnl_today: float
    unrealized_pnl: float
    total_pnl: float
    portfolio_greeks: Optional[PortfolioGreeks]
    risk_metrics: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP response."""
        return {
            'account_id': self.account_id,
            'timestamp': self.timestamp.isoformat(),
            'total_value': round(self.total_value, 2),
            'total_cash': round(self.total_cash, 2),
            'buying_power': round(self.buying_power, 2),
            'maintenance_margin': round(self.maintenance_margin, 2),
            'positions_count': len(self.positions),
            'positions': self.positions,
            'realized_pnl_today': round(self.realized_pnl_today, 2),
            'unrealized_pnl': round(self.unrealized_pnl, 2),
            'total_pnl': round(self.total_pnl, 2),
            'portfolio_greeks': self.portfolio_greeks.to_dict() if self.portfolio_greeks else None,
            'risk_metrics': self.risk_metrics
        }


class PortfolioAnalyzer:
    """Analyzes portfolio-level metrics and aggregates data."""
    
    def __init__(self):
        self.tws = None
        self._cache = {}
        self._cache_ttl = 30  # seconds
        
    async def get_portfolio_summary(
        self,
        include_greeks: bool = True,
        beta_weight_symbol: Optional[str] = 'SPY',
        include_closed_today: bool = False
    ) -> PortfolioSummary:
        """
        Get comprehensive portfolio summary with P&L and Greeks.
        
        Args:
            include_greeks: Whether to calculate aggregate Greeks
            beta_weight_symbol: Symbol for beta-weighted delta (typically SPY)
            include_closed_today: Include positions closed today
            
        Returns:
            PortfolioSummary with all metrics
        """
        cache_key = f"portfolio_{include_greeks}_{beta_weight_symbol}_{include_closed_today}"
        
        # Check cache
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if (datetime.now() - cached_time).seconds < self._cache_ttl:
                logger.info("[PORTFOLIO] Returning cached portfolio summary")
                return cached_data
        
        try:
            # Get connection
            self.tws = await get_tws_connection()
            
            # Fetch account summary
            account_values = await self.tws.ib.accountValuesAsync()
            account_summary = await self.tws.ib.accountSummaryAsync()
            
            # Parse account metrics
            # Get account ID from IB wrapper or config
            if hasattr(self.tws, 'ib') and self.tws.ib.wrapper.accounts:
                account_id = self.tws.ib.wrapper.accounts[0]
            else:
                from src.config import config
                account_id = config.tws.account or 'UNKNOWN'
            total_value = 0.0
            total_cash = 0.0
            buying_power = 0.0
            maintenance_margin = 0.0
            realized_pnl = 0.0
            
            for item in account_summary:
                if item.tag == 'NetLiquidation':
                    total_value = float(item.value)
                elif item.tag == 'TotalCashValue':
                    total_cash = float(item.value)
                elif item.tag == 'BuyingPower':
                    buying_power = float(item.value)
                elif item.tag == 'MaintMarginReq':
                    maintenance_margin = float(item.value)
                elif item.tag == 'RealizedPnL':
                    realized_pnl = float(item.value)
            
            # Get positions
            positions = await self.tws.ib.positionsAsync()
            position_data = []
            unrealized_pnl = 0.0
            portfolio_greeks = PortfolioGreeks() if include_greeks else None
            
            for pos in positions:
                # pos already in correct format
                
                # Get current market value
                contract = pos.contract
                ticker = await self.tws.ib.reqTickersAsync(contract)
                
                if ticker:
                    market_price = ticker[0].marketPrice()
                    if market_price and market_price != -1:
                        market_value = market_price * pos.position * 100  # Options multiplier
                        position_pnl = market_value - (pos.avgCost * pos.position)
                        unrealized_pnl += position_pnl
                    else:
                        market_price = pos.avgCost
                        market_value = pos.avgCost * pos.position
                        position_pnl = 0
                else:
                    market_price = pos.avgCost
                    market_value = pos.avgCost * pos.position
                    position_pnl = 0
                
                # Build position dict
                pos_dict = {
                    'symbol': contract.symbol,
                    'position': pos.position,
                    'avg_cost': round(pos.avgCost, 2),
                    'market_price': round(market_price, 2) if market_price else None,
                    'market_value': round(market_value, 2),
                    'unrealized_pnl': round(position_pnl, 2),
                    'contract_type': contract.secType
                }
                
                # Add option-specific data
                if contract.secType == 'OPT':
                    pos_dict.update({
                        'strike': contract.strike,
                        'expiry': contract.lastTradeDateOrContractMonth,
                        'right': contract.right
                    })
                    
                    # Get Greeks if requested
                    if include_greeks and ticker and ticker[0].modelGreeks:
                        greeks = ticker[0].modelGreeks
                        pos_dict['greeks'] = {
                            'delta': round(greeks.delta, 4) if greeks.delta else 0,
                            'gamma': round(greeks.gamma, 4) if greeks.gamma else 0,
                            'theta': round(greeks.theta, 4) if greeks.theta else 0,
                            'vega': round(greeks.vega, 4) if greeks.vega else 0
                        }
                        
                        # Aggregate Greeks (multiply by position size and contract multiplier)
                        multiplier = pos.position * 100
                        portfolio_greeks.total_delta += (greeks.delta or 0) * multiplier
                        portfolio_greeks.total_gamma += (greeks.gamma or 0) * multiplier
                        portfolio_greeks.total_theta += (greeks.theta or 0) * multiplier
                        portfolio_greeks.total_vega += (greeks.vega or 0) * multiplier
                        portfolio_greeks.positions_count += 1
                
                position_data.append(pos_dict)
            
            # Calculate beta-weighted delta if requested
            if portfolio_greeks and beta_weight_symbol:
                try:
                    # Get SPY (or specified symbol) price for beta weighting
                    spy_contract = Stock(beta_weight_symbol, 'SMART', 'USD')
                    spy_ticker = await self.tws.ib.reqTickersAsync(spy_contract)
                    if spy_ticker and spy_ticker[0].marketPrice():
                        spy_price = spy_ticker[0].marketPrice()
                        # Simple beta weighting (can be enhanced with actual beta calculation)
                        portfolio_greeks.beta_weighted_delta = portfolio_greeks.total_delta * (100 / spy_price)
                except Exception as e:
                    logger.warning(f"[PORTFOLIO] Could not calculate beta-weighted delta: {e}")
            
            # Calculate risk metrics
            risk_metrics = {
                'margin_usage': round((maintenance_margin / total_value * 100) if total_value > 0 else 0, 2),
                'cash_percentage': round((total_cash / total_value * 100) if total_value > 0 else 0, 2),
                'positions_percentage': round(((total_value - total_cash) / total_value * 100) if total_value > 0 else 0, 2),
                'max_position_concentration': 0.0
            }
            
            # Find max position concentration
            if position_data and total_value > 0:
                max_value = max([abs(p['market_value']) for p in position_data])
                risk_metrics['max_position_concentration'] = round((max_value / total_value * 100), 2)
            
            # Build summary
            summary = PortfolioSummary(
                account_id=account_id,
                timestamp=datetime.now(),
                total_value=total_value,
                total_cash=total_cash,
                buying_power=buying_power,
                maintenance_margin=maintenance_margin,
                positions=position_data,
                realized_pnl_today=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_pnl=realized_pnl + unrealized_pnl,
                portfolio_greeks=portfolio_greeks,
                risk_metrics=risk_metrics
            )
            
            # Cache result
            self._cache[cache_key] = (datetime.now(), summary)
            
            logger.info(f"[PORTFOLIO] Generated summary - {len(position_data)} positions, "
                       f"Total P&L: ${summary.total_pnl:.2f}")
            
            return summary
            
        except Exception as e:
            logger.error(f"[PORTFOLIO] Error getting portfolio summary: {e}")
            raise
    
    async def get_trade_history(
        self,
        days_back: int = 30,
        symbol: Optional[str] = None,
        include_executions: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get historical trades and executions.
        
        Args:
            days_back: Number of days to look back
            symbol: Filter by symbol (optional)
            include_executions: Include execution details
            
        Returns:
            List of trade records
        """
        try:
            self.tws = await get_tws_connection()
            
            # Get filled orders from the past N days
            filled_orders = await self.tws.ib.fillsAsync()
            
            # Filter by date range
            cutoff_date = datetime.now() - timedelta(days=days_back)
            trades = []
            
            for fill in filled_orders:
                if fill.time >= cutoff_date:
                    contract = fill.contract
                    
                    # Filter by symbol if specified
                    if symbol and contract.symbol != symbol:
                        continue
                    
                    trade_dict = {
                        'time': fill.time.isoformat(),
                        'symbol': contract.symbol,
                        'action': fill.execution.side,
                        'quantity': fill.execution.shares,
                        'price': fill.execution.price,
                        'commission': fill.commissionReport.commission if fill.commissionReport else 0,
                        'realized_pnl': fill.commissionReport.realizedPNL if fill.commissionReport else 0,
                        'contract_type': contract.secType
                    }
                    
                    # Add option details
                    if contract.secType == 'OPT':
                        trade_dict.update({
                            'strike': contract.strike,
                            'expiry': contract.lastTradeDateOrContractMonth,
                            'right': contract.right
                        })
                    
                    # Add execution details if requested
                    if include_executions:
                        trade_dict['execution'] = {
                            'exec_id': fill.execution.execId,
                            'cum_qty': fill.execution.cumQty,
                            'avg_price': fill.execution.avgPrice,
                            'order_id': fill.execution.orderId,
                            'exchange': fill.execution.exchange
                        }
                    
                    trades.append(trade_dict)
            
            # Sort by time (most recent first)
            trades.sort(key=lambda x: x['time'], reverse=True)
            
            logger.info(f"[PORTFOLIO] Retrieved {len(trades)} trades from past {days_back} days")
            return trades
            
        except Exception as e:
            logger.error(f"[PORTFOLIO] Error getting trade history: {e}")
            raise
    
    async def analyze_portfolio_greeks(
        self,
        scenario_moves: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Analyze portfolio-wide Greeks with scenario analysis.
        
        Args:
            scenario_moves: List of underlying price moves to test (e.g., [-10, -5, 0, 5, 10])
            
        Returns:
            Greeks analysis with scenario P&L
        """
        if scenario_moves is None:
            scenario_moves = [-10, -5, -2, 0, 2, 5, 10]
        
        try:
            # Get current portfolio summary with Greeks
            summary = await self.get_portfolio_summary(include_greeks=True)
            
            if not summary.portfolio_greeks:
                return {
                    'status': 'NO_OPTIONS',
                    'message': 'No options positions found in portfolio'
                }
            
            greeks = summary.portfolio_greeks
            
            # Calculate scenario analysis
            scenarios = []
            for move in scenario_moves:
                # Simple P&L approximation using Greeks
                # P&L = delta * move + 0.5 * gamma * move^2
                pnl_from_delta = greeks.total_delta * move
                pnl_from_gamma = 0.5 * greeks.total_gamma * (move ** 2)
                total_scenario_pnl = pnl_from_delta + pnl_from_gamma
                
                scenarios.append({
                    'price_move': move,
                    'pnl_from_delta': round(pnl_from_delta, 2),
                    'pnl_from_gamma': round(pnl_from_gamma, 2),
                    'total_pnl': round(total_scenario_pnl, 2)
                })
            
            # Calculate daily theta decay
            daily_theta = greeks.total_theta
            weekly_theta = daily_theta * 5  # Trading days
            monthly_theta = daily_theta * 21  # Approximate trading days
            
            return {
                'status': 'SUCCESS',
                'portfolio_greeks': greeks.to_dict(),
                'theta_analysis': {
                    'daily_decay': round(daily_theta, 2),
                    'weekly_decay': round(weekly_theta, 2),
                    'monthly_decay': round(monthly_theta, 2)
                },
                'scenario_analysis': scenarios,
                'risk_assessment': {
                    'delta_neutral': abs(greeks.total_delta) < 10,
                    'gamma_risk': 'HIGH' if abs(greeks.total_gamma) > 50 else 'MODERATE' if abs(greeks.total_gamma) > 20 else 'LOW',
                    'theta_collection': 'POSITIVE' if greeks.total_theta > 0 else 'NEGATIVE',
                    'vega_exposure': 'HIGH' if abs(greeks.total_vega) > 100 else 'MODERATE' if abs(greeks.total_vega) > 50 else 'LOW'
                }
            }
            
        except Exception as e:
            logger.error(f"[PORTFOLIO] Error analyzing portfolio Greeks: {e}")
            raise