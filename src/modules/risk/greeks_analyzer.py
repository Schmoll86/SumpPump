"""
Portfolio Greeks analysis module.
Provides aggregate Greeks, scenario analysis, and risk metrics.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

from loguru import logger
from ib_async import Option, Stock

from src.modules.tws.connection import get_tws_connection
from src.modules.data.portfolio import PortfolioGreeks


@dataclass
class GreeksScenario:
    """Greeks under different market scenarios."""
    scenario_name: str
    market_move: float  # Percentage
    vol_change: float  # IV change
    time_decay: int  # Days
    portfolio_value: float
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_theta: float
    portfolio_vega: float
    pnl_change: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'scenario': self.scenario_name,
            'market_move': f"{self.market_move:+.1f}%",
            'vol_change': f"{self.vol_change:+.1f}%",
            'time_decay': f"{self.time_decay} days",
            'portfolio_value': round(self.portfolio_value, 2),
            'portfolio_delta': round(self.portfolio_delta, 2),
            'portfolio_gamma': round(self.portfolio_gamma, 4),
            'portfolio_theta': round(self.portfolio_theta, 2),
            'portfolio_vega': round(self.portfolio_vega, 2),
            'pnl_change': round(self.pnl_change, 2)
        }


class GreeksAnalyzer:
    """Analyzes portfolio Greeks and risk scenarios."""
    
    def __init__(self):
        """Initialize Greeks analyzer."""
        self.tws = None
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 30  # seconds
        
    async def _ensure_connection(self):
        """Ensure TWS connection is established."""
        if not self.tws:
            self.tws = await get_tws_connection()
    
    async def get_portfolio_greeks(self) -> PortfolioGreeks:
        """
        Get aggregate Greeks for entire portfolio.
        
        Returns:
            Portfolio Greeks summary
        """
        await self._ensure_connection()
        
        # Check cache
        if self._cache_time and (datetime.now() - self._cache_time).seconds < self._cache_ttl:
            if 'portfolio_greeks' in self._cache:
                logger.debug("[GREEKS] Using cached portfolio Greeks")
                return self._cache['portfolio_greeks']
        
        logger.info("[GREEKS] Calculating portfolio Greeks")
        
        ib = self.tws.ib
        positions = ib.positions()
        
        greeks = PortfolioGreeks()
        
        for position in positions:
            contract = position.contract
            
            # Only options have Greeks
            if contract.secType != 'OPT':
                # Stocks contribute to delta
                if contract.secType == 'STK':
                    greeks.total_delta += position.position
                continue
            
            # Get option ticker with Greeks
            ticker = ib.reqMktData(contract, genericTickList='106', snapshot=True)
            await asyncio.sleep(2)
            
            if ticker.modelGreeks:
                # Scale by position and multiplier
                multiplier = position.position * 100  # Options multiplier
                
                greeks.total_delta += ticker.modelGreeks.delta * multiplier
                greeks.total_gamma += ticker.modelGreeks.gamma * multiplier
                greeks.total_theta += ticker.modelGreeks.theta * multiplier
                greeks.total_vega += ticker.modelGreeks.vega * multiplier
                
                logger.debug(f"[GREEKS] {contract.symbol} {contract.strike} - Delta: {ticker.modelGreeks.delta:.3f}")
            
            greeks.positions_count += 1
        
        # Calculate beta-weighted delta (SPY-weighted)
        spy = Stock('SPY', 'SMART', 'USD')
        spy_ticker = ib.reqMktData(spy, snapshot=True)
        await asyncio.sleep(1)
        
        spy_price = spy_ticker.last or spy_ticker.close or 500  # Default if no data
        greeks.beta_weighted_delta = greeks.total_delta / spy_price
        
        logger.info(f"[GREEKS] Portfolio - Delta: {greeks.total_delta:.2f}, Theta: ${greeks.total_theta:.2f}/day")
        
        # Cache result
        self._cache['portfolio_greeks'] = greeks
        self._cache_time = datetime.now()
        
        return greeks
    
    async def get_greeks_by_underlying(self) -> Dict[str, Dict[str, float]]:
        """
        Get Greeks grouped by underlying symbol.
        
        Returns:
            Greeks by underlying
        """
        await self._ensure_connection()
        
        logger.info("[GREEKS] Calculating Greeks by underlying")
        
        ib = self.tws.ib
        positions = ib.positions()
        
        by_symbol = defaultdict(lambda: {
            'delta': 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'positions': 0
        })
        
        for position in positions:
            contract = position.contract
            symbol = contract.symbol
            
            if contract.secType == 'STK':
                by_symbol[symbol]['delta'] += position.position
                by_symbol[symbol]['positions'] += 1
                
            elif contract.secType == 'OPT':
                ticker = ib.reqMktData(contract, genericTickList='106', snapshot=True)
                await asyncio.sleep(1)
                
                if ticker.modelGreeks:
                    multiplier = position.position * 100
                    
                    by_symbol[symbol]['delta'] += ticker.modelGreeks.delta * multiplier
                    by_symbol[symbol]['gamma'] += ticker.modelGreeks.gamma * multiplier
                    by_symbol[symbol]['theta'] += ticker.modelGreeks.theta * multiplier
                    by_symbol[symbol]['vega'] += ticker.modelGreeks.vega * multiplier
                    by_symbol[symbol]['positions'] += 1
        
        # Round values
        result = {}
        for symbol, greeks in by_symbol.items():
            result[symbol] = {
                'delta': round(greeks['delta'], 2),
                'gamma': round(greeks['gamma'], 4),
                'theta': round(greeks['theta'], 2),
                'vega': round(greeks['vega'], 2),
                'positions': greeks['positions']
            }
            
        logger.info(f"[GREEKS] Analyzed {len(result)} underlyings")
        
        return result
    
    async def calculate_scenarios(self) -> List[Dict[str, Any]]:
        """
        Calculate portfolio value under different market scenarios.
        
        Returns:
            List of scenario results
        """
        await self._ensure_connection()
        
        logger.info("[GREEKS] Calculating market scenarios")
        
        # Get current Greeks
        current_greeks = await self.get_portfolio_greeks()
        
        # Get current portfolio value
        ib = self.tws.ib
        account_values = ib.accountValues()
        portfolio_value = 0
        for av in account_values:
            if av.tag == 'NetLiquidation':
                portfolio_value = float(av.value)
                break
        
        scenarios = []
        
        # Define scenarios
        scenario_params = [
            ("Bull +5%", 5.0, 0.0, 1),
            ("Bear -5%", -5.0, 0.0, 1),
            ("Crash -10%", -10.0, 5.0, 1),  # Vol spike
            ("Rally +10%", 10.0, -2.0, 1),  # Vol crush
            ("Theta Decay 5d", 0.0, 0.0, 5),
            ("Vol Spike +5%", 0.0, 5.0, 1),
            ("Vol Crush -5%", 0.0, -5.0, 1),
        ]
        
        for name, market_move, vol_change, days in scenario_params:
            # Estimate P&L from Greeks
            # Simplified calculation (first-order approximation)
            spy_price = 500  # Approximate SPY price
            
            price_change = spy_price * (market_move / 100)
            
            # Delta P&L
            delta_pnl = current_greeks.total_delta * price_change
            
            # Gamma P&L (second order)
            gamma_pnl = 0.5 * current_greeks.total_gamma * (price_change ** 2)
            
            # Theta P&L
            theta_pnl = current_greeks.total_theta * days
            
            # Vega P&L
            vega_pnl = current_greeks.total_vega * vol_change
            
            total_pnl = delta_pnl + gamma_pnl + theta_pnl + vega_pnl
            
            # Estimate new Greeks (simplified)
            new_delta = current_greeks.total_delta + (current_greeks.total_gamma * price_change)
            
            scenario = GreeksScenario(
                scenario_name=name,
                market_move=market_move,
                vol_change=vol_change,
                time_decay=days,
                portfolio_value=portfolio_value + total_pnl,
                portfolio_delta=new_delta,
                portfolio_gamma=current_greeks.total_gamma,  # Simplified
                portfolio_theta=current_greeks.total_theta,
                portfolio_vega=current_greeks.total_vega,
                pnl_change=total_pnl
            )
            
            scenarios.append(scenario.to_dict())
            
        logger.info(f"[GREEKS] Calculated {len(scenarios)} scenarios")
        
        return scenarios
    
    async def project_time_decay(self, days: int = 5) -> Dict[str, Any]:
        """
        Project time decay over specified days.
        
        Args:
            days: Number of days to project
            
        Returns:
            Time decay projection
        """
        await self._ensure_connection()
        
        logger.info(f"[GREEKS] Projecting time decay for {days} days")
        
        current_greeks = await self.get_portfolio_greeks()
        
        daily_decay = []
        cumulative_decay = 0
        
        for day in range(1, days + 1):
            # Simplified: assume constant theta
            day_decay = current_greeks.total_theta
            cumulative_decay += day_decay
            
            daily_decay.append({
                'day': day,
                'daily_decay': round(day_decay, 2),
                'cumulative_decay': round(cumulative_decay, 2)
            })
        
        logger.debug(f"[GREEKS] {days}-day decay: ${cumulative_decay:.2f}")
        
        return {
            'projection_days': days,
            'current_theta': round(current_greeks.total_theta, 2),
            'total_decay': round(cumulative_decay, 2),
            'daily_projection': daily_decay,
            'weekend_adjusted': False  # Could enhance to skip weekends
        }
    
    async def get_hedging_recommendations(self) -> List[Dict[str, Any]]:
        """
        Get hedging recommendations based on current Greeks.
        
        Returns:
            List of hedging suggestions
        """
        await self._ensure_connection()
        
        logger.info("[GREEKS] Generating hedging recommendations")
        
        current_greeks = await self.get_portfolio_greeks()
        recommendations = []
        
        # Delta hedging
        if abs(current_greeks.total_delta) > 100:
            direction = "long" if current_greeks.total_delta < 0 else "short"
            recommendations.append({
                'type': 'delta_hedge',
                'reason': f'High directional risk: {current_greeks.total_delta:.0f} delta',
                'action': f'Consider {direction} {abs(current_greeks.total_delta):.0f} shares of SPY',
                'priority': 'high' if abs(current_greeks.total_delta) > 500 else 'medium'
            })
        
        # Gamma risk
        if abs(current_greeks.total_gamma) > 10:
            recommendations.append({
                'type': 'gamma_hedge',
                'reason': f'High gamma exposure: {current_greeks.total_gamma:.2f}',
                'action': 'Consider adding long options to reduce gamma risk',
                'priority': 'medium'
            })
        
        # Theta decay
        if current_greeks.total_theta < -100:
            recommendations.append({
                'type': 'theta_warning',
                'reason': f'High time decay: ${abs(current_greeks.total_theta):.2f}/day',
                'action': 'Consider rolling short-dated options or reducing position',
                'priority': 'high' if current_greeks.total_theta < -500 else 'medium'
            })
        
        # Vega exposure
        if abs(current_greeks.total_vega) > 500:
            direction = "rise" if current_greeks.total_vega > 0 else "fall"
            recommendations.append({
                'type': 'vega_hedge',
                'reason': f'High volatility exposure: {current_greeks.total_vega:.0f} vega',
                'action': f'Portfolio will benefit from IV {direction}. Consider hedging if concerned',
                'priority': 'low'
            })
        
        if not recommendations:
            recommendations.append({
                'type': 'balanced',
                'reason': 'Portfolio Greeks are relatively balanced',
                'action': 'No immediate hedging required',
                'priority': 'info'
            })
        
        logger.info(f"[GREEKS] Generated {len(recommendations)} recommendations")
        
        return recommendations