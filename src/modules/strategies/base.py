"""
Base strategy class for options trading strategies.
Provides common functionality for P&L calculations, Greeks aggregation, and risk analysis.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import numpy as np
    from scipy.stats import norm
    from scipy.optimize import brentq
except ImportError:
    logger.warning("SciPy not installed, some probability calculations may be unavailable")
    np = None
    norm = None
    brentq = None

try:
    from py_vollib.black_scholes import black_scholes
    from py_vollib.black_scholes.greeks import delta, gamma, theta, vega
except ImportError:
    logger.warning("py_vollib not installed, using approximations for Black-Scholes calculations")
    black_scholes = None

from src.models import (
    Strategy, OptionLeg, OptionContract, StrategyType, 
    OrderAction, OptionRight, Greeks
)


class StrategyCalculationError(Exception):
    """Custom exception for strategy calculation errors."""
    pass


class StrategyValidationError(Exception):
    """Custom exception for strategy validation errors."""
    pass


class BaseStrategy(ABC):
    """
    Base class for all options strategies.
    Provides common functionality for P&L calculations and risk analysis.
    """
    
    def __init__(self, name: str, strategy_type: StrategyType, legs: List[OptionLeg]):
        """
        Initialize base strategy.
        
        Args:
            name: Strategy name
            strategy_type: Type of strategy
            legs: List of option legs
        """
        self.name = name
        self.strategy_type = strategy_type
        self.legs = legs
        
        # Validate legs
        if not legs:
            raise ValueError("Strategy must have at least one leg")
            
        # Extract common parameters
        self.underlying_symbol = legs[0].contract.symbol
        self.underlying_price = legs[0].contract.underlying_price
        
        # Ensure all legs are for the same underlying
        for leg in legs:
            if leg.contract.symbol != self.underlying_symbol:
                raise ValueError("All legs must be for the same underlying symbol")
    
    @abstractmethod
    async def calculate_pnl(self, underlying_price: float) -> float:
        """
        Calculate profit/loss at given underlying price.
        
        Args:
            underlying_price: Price of underlying asset
            
        Returns:
            P&L value at the given price
        """
        pass
    
    @abstractmethod
    async def get_breakeven_points(self) -> List[float]:
        """
        Find breakeven points where P&L equals zero.
        
        Returns:
            List of breakeven prices
        """
        pass
    
    @abstractmethod
    async def calculate_max_profit(self) -> float:
        """
        Calculate maximum possible profit.
        
        Returns:
            Maximum profit amount
        """
        pass
    
    @abstractmethod
    async def calculate_max_loss(self) -> float:
        """
        Calculate maximum possible loss.
        
        Returns:
            Maximum loss amount (negative value)
        """
        pass
    
    async def calculate_net_debit_credit(self) -> float:
        """
        Calculate net debit (negative) or credit (positive) for opening the strategy.
        
        Returns:
            Net debit/credit amount
        """
        return sum(leg.cost for leg in self.legs)
    
    async def calculate_required_capital(self) -> float:
        """
        Calculate required capital/margin for the strategy.
        
        Returns:
            Required capital amount
        """
        # For most strategies, required capital is the net debit or max loss
        max_loss = await self.calculate_max_loss()
        net_cost = await self.calculate_net_debit_credit()
        
        # For credit strategies, capital requirement is typically the max loss
        if net_cost > 0:  # Credit received
            return abs(max_loss)
        else:  # Debit paid
            return abs(net_cost)
    
    async def aggregate_greeks(self) -> Greeks:
        """
        Aggregate Greeks across all strategy legs.
        
        Returns:
            Combined Greeks for the entire strategy
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0
        
        for leg in self.legs:
            multiplier = leg.quantity
            if leg.action == OrderAction.SELL:
                multiplier *= -1
                
            total_delta += leg.contract.greeks.delta * multiplier
            total_gamma += leg.contract.greeks.gamma * multiplier
            total_theta += leg.contract.greeks.theta * multiplier
            total_vega += leg.contract.greeks.vega * multiplier
            
            if leg.contract.greeks.rho:
                total_rho += leg.contract.greeks.rho * multiplier
        
        return Greeks(
            delta=total_delta,
            gamma=total_gamma,
            theta=total_theta,
            vega=total_vega,
            rho=total_rho if total_rho != 0 else None
        )
    
    async def calculate_probability_of_profit(self, risk_free_rate: float = 0.05) -> float:
        """
        Calculate probability of profit using Black-Scholes model.
        
        Args:
            risk_free_rate: Risk-free interest rate (default 5%)
            
        Returns:
            Probability of profit as a decimal (0.0 to 1.0)
        """
        if not np or not norm:
            logger.warning("SciPy not available, cannot calculate probability of profit")
            return 0.0
            
        try:
            breakeven_points = await self.get_breakeven_points()
            
            if not breakeven_points:
                logger.warning("No breakeven points found for probability calculation")
                return 0.0
            
            # Get the shortest expiry date among all legs
            expiry_dates = [leg.contract.expiry for leg in self.legs]
            min_expiry = min(expiry_dates)
            
            # Calculate time to expiration in years
            now = datetime.now()
            time_to_expiry = (min_expiry - now).days / 365.0
            
            if time_to_expiry <= 0:
                logger.warning("Strategy has expired or expires today")
                return 0.0
            
            # Get average implied volatility across legs
            total_iv = sum(leg.contract.iv for leg in self.legs)
            avg_iv = total_iv / len(self.legs)
            
            if avg_iv <= 0:
                logger.warning("Invalid implied volatility for probability calculation")
                return 0.0
            
            # For strategies with one breakeven point
            if len(breakeven_points) == 1:
                breakeven = breakeven_points[0]
                
                # Calculate probability using Black-Scholes
                d1 = (np.log(self.underlying_price / breakeven) + 
                      (risk_free_rate + 0.5 * avg_iv**2) * time_to_expiry) / (avg_iv * np.sqrt(time_to_expiry))
                
                # Determine if we profit above or below breakeven
                # Test a point slightly above breakeven
                test_price = breakeven * 1.01
                test_pnl = await self.calculate_pnl(test_price)
                
                if test_pnl > 0:
                    # Profit above breakeven
                    prob = 1 - norm.cdf(d1)
                else:
                    # Profit below breakeven
                    prob = norm.cdf(d1)
                    
                return max(0.0, min(1.0, prob))
            
            # For strategies with two breakeven points (like straddles, iron condors)
            elif len(breakeven_points) == 2:
                lower_breakeven = min(breakeven_points)
                upper_breakeven = max(breakeven_points)
                
                # Test if we profit between breakevens or outside them
                mid_price = (lower_breakeven + upper_breakeven) / 2
                mid_pnl = await self.calculate_pnl(mid_price)
                
                if mid_pnl > 0:
                    # Profit between breakevens
                    d1_lower = (np.log(self.underlying_price / lower_breakeven) + 
                               (risk_free_rate + 0.5 * avg_iv**2) * time_to_expiry) / (avg_iv * np.sqrt(time_to_expiry))
                    d1_upper = (np.log(self.underlying_price / upper_breakeven) + 
                               (risk_free_rate + 0.5 * avg_iv**2) * time_to_expiry) / (avg_iv * np.sqrt(time_to_expiry))
                    
                    prob = norm.cdf(d1_upper) - norm.cdf(d1_lower)
                else:
                    # Profit outside breakevens
                    d1_lower = (np.log(self.underlying_price / lower_breakeven) + 
                               (risk_free_rate + 0.5 * avg_iv**2) * time_to_expiry) / (avg_iv * np.sqrt(time_to_expiry))
                    d1_upper = (np.log(self.underlying_price / upper_breakeven) + 
                               (risk_free_rate + 0.5 * avg_iv**2) * time_to_expiry) / (avg_iv * np.sqrt(time_to_expiry))
                    
                    prob = norm.cdf(d1_lower) + (1 - norm.cdf(d1_upper))
                    
                return max(0.0, min(1.0, prob))
            
            else:
                logger.warning(f"Unsupported number of breakeven points: {len(breakeven_points)}")
                return 0.0
                
        except Exception as e:
            logger.error(f"Error calculating probability of profit: {e}")
            return 0.0
    
    async def validate_strategy(self) -> Dict[str, Any]:
        """
        Validate strategy against risk checks and requirements.
        
        Returns:
            Validation results with warnings and errors
        """
        validation_result = {
            'is_valid': True,
            'warnings': [],
            'errors': []
        }
        
        try:
            # Check minimum volume
            for i, leg in enumerate(self.legs):
                if leg.contract.volume < 10:
                    validation_result['warnings'].append(
                        f"Leg {i+1} has low volume: {leg.contract.volume}"
                    )
                
                # Check minimum open interest
                if leg.contract.open_interest < 50:
                    validation_result['warnings'].append(
                        f"Leg {i+1} has low open interest: {leg.contract.open_interest}"
                    )
                
                # Check bid-ask spread
                if leg.contract.bid > 0 and leg.contract.ask > 0:
                    spread = leg.contract.ask - leg.contract.bid
                    mid_price = (leg.contract.bid + leg.contract.ask) / 2
                    spread_percent = spread / mid_price if mid_price > 0 else 0
                    
                    if spread_percent > 0.10:  # 10% spread threshold
                        validation_result['warnings'].append(
                            f"Leg {i+1} has wide bid-ask spread: {spread_percent:.1%}"
                        )
            
            # Check for expired options
            now = datetime.now()
            for i, leg in enumerate(self.legs):
                if leg.contract.expiry <= now:
                    validation_result['errors'].append(
                        f"Leg {i+1} is expired or expires today"
                    )
                    validation_result['is_valid'] = False
            
            # Check for reasonable strikes
            for i, leg in enumerate(self.legs):
                strike = leg.contract.strike
                if strike <= 0:
                    validation_result['errors'].append(
                        f"Leg {i+1} has invalid strike price: {strike}"
                    )
                    validation_result['is_valid'] = False
            
        except Exception as e:
            validation_result['errors'].append(f"Validation error: {e}")
            validation_result['is_valid'] = False
        
        return validation_result
    
    async def create_strategy_object(self) -> Strategy:
        """
        Create a Strategy object with all calculated values.
        
        Returns:
            Complete Strategy object
        """
        try:
            # Calculate all required values
            max_profit = await self.calculate_max_profit()
            max_loss = await self.calculate_max_loss()
            breakeven_points = await self.get_breakeven_points()
            current_value = await self.calculate_pnl(self.underlying_price)
            probability_profit = await self.calculate_probability_of_profit()
            required_capital = await self.calculate_required_capital()
            
            return Strategy(
                name=self.name,
                type=self.strategy_type,
                legs=self.legs,
                max_profit=max_profit,
                max_loss=max_loss,
                breakeven=breakeven_points,
                current_value=current_value,
                probability_profit=probability_profit,
                required_capital=required_capital
            )
            
        except Exception as e:
            logger.error(f"Error creating strategy object: {e}")
            raise StrategyCalculationError(f"Failed to create strategy: {e}")
    
    def _option_value_at_expiry(self, contract: OptionContract, underlying_price: float) -> float:
        """
        Calculate option value at expiration.
        
        Args:
            contract: Option contract
            underlying_price: Price of underlying at expiration
            
        Returns:
            Intrinsic value of option at expiration
        """
        if contract.right == OptionRight.CALL:
            return max(0, underlying_price - contract.strike)
        else:  # PUT
            return max(0, contract.strike - underlying_price)
    
    def _find_breakeven_in_range(self, price_range: Tuple[float, float], tolerance: float = 0.01) -> Optional[float]:
        """
        Find breakeven point in given price range using numerical methods.
        
        Args:
            price_range: Tuple of (min_price, max_price) to search
            tolerance: Tolerance for breakeven (default $0.01)
            
        Returns:
            Breakeven price if found, None otherwise
        """
        if not brentq:
            logger.warning("SciPy not available, cannot use numerical breakeven finding")
            return None
            
        try:
            min_price, max_price = price_range
            
            # Define function to find zero
            async def pnl_function(price):
                return await self.calculate_pnl(price)
            
            # Test endpoints
            min_pnl = asyncio.run(pnl_function(min_price))
            max_pnl = asyncio.run(pnl_function(max_price))
            
            # Check if there's a sign change (root exists)
            if min_pnl * max_pnl > 0:
                return None
            
            # Use Brent's method to find root
            def sync_pnl_function(price):
                return asyncio.run(pnl_function(price))
            
            breakeven = brentq(sync_pnl_function, min_price, max_price, xtol=tolerance)
            return breakeven
            
        except Exception as e:
            logger.debug(f"Could not find breakeven in range {price_range}: {e}")
            return None