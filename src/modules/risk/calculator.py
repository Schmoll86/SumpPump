"""
Risk calculation module for SumpPump.
Handles position sizing, max risk calculations, margin requirements, and stop loss recommendations.
"""

import asyncio
from typing import Dict, Any, Optional, Tuple
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
import numpy as np

from src.models import Strategy, StrategyType, OptionContract
from src.config import config


class RiskCalculator:
    """
    Risk calculator for options trading strategies.
    Provides methods for position sizing, risk calculations, and Kelly criterion.
    """

    def __init__(self):
        """Initialize risk calculator with configuration."""
        self.max_position_percent = config.risk.max_position_size_percent
        self.default_stop_loss_percent = config.risk.default_stop_loss_percent

    async def calculate_position_size(
        self, 
        account_value: float, 
        risk_percent: Optional[float] = None
    ) -> float:
        """
        Calculate appropriate position size based on account value and risk tolerance.
        
        Args:
            account_value: Total account value
            risk_percent: Risk percentage (defaults to config value)
            
        Returns:
            Maximum position size in dollars
            
        Raises:
            ValueError: If account_value is invalid
        """
        if account_value <= 0:
            raise ValueError("Account value must be positive")
            
        if risk_percent is None:
            risk_percent = self.max_position_percent
            
        if not 0 < risk_percent <= 100:
            raise ValueError("Risk percent must be between 0 and 100")
            
        position_size = account_value * (risk_percent / 100)
        
        logger.info(
            f"Calculated position size: ${position_size:,.2f} "
            f"({risk_percent}% of ${account_value:,.2f})"
        )
        
        return position_size

    async def calculate_max_risk(self, strategy: Strategy) -> Dict[str, float]:
        """
        Calculate maximum risk for a strategy including various scenarios.
        
        Args:
            strategy: Options strategy to analyze
            
        Returns:
            Dictionary containing max loss, required capital, and risk metrics
        """
        try:
            max_loss = abs(strategy.max_loss)  # Ensure positive value
            required_capital = strategy.required_capital
            net_debit_credit = strategy.net_debit_credit
            
            # Calculate additional risk metrics
            risk_reward_ratio = 0.0
            if strategy.max_profit > 0 and max_loss > 0:
                risk_reward_ratio = strategy.max_profit / max_loss
                
            # Calculate probability-adjusted risk
            prob_profit = strategy.probability_profit or 0.5
            expected_value = (strategy.max_profit * prob_profit) - (max_loss * (1 - prob_profit))
            
            risk_metrics = {
                'max_loss': max_loss,
                'max_profit': strategy.max_profit,
                'required_capital': required_capital,
                'net_debit_credit': net_debit_credit,
                'risk_reward_ratio': risk_reward_ratio,
                'probability_profit': prob_profit,
                'expected_value': expected_value,
                'breakeven_points': strategy.breakeven
            }
            
            logger.info(f"Risk analysis for {strategy.name}: Max loss ${max_loss:,.2f}")
            
            return risk_metrics
            
        except Exception as e:
            logger.error(f"Error calculating max risk: {e}")
            raise ValueError(f"Risk calculation failed: {e}")

    async def calculate_margin_requirement(
        self, 
        strategy: Strategy, 
        account_type: str = "margin"
    ) -> Dict[str, float]:
        """
        Calculate margin requirements for different account types.
        
        Args:
            strategy: Options strategy
            account_type: Account type ("cash", "margin", "portfolio_margin")
            
        Returns:
            Dictionary with margin requirements and buying power usage
        """
        try:
            margin_req = 0.0
            buying_power_used = 0.0
            
            if account_type.lower() == "cash":
                # Cash account: Full premium required for purchases
                margin_req = await self._calculate_cash_margin(strategy)
                buying_power_used = margin_req
                
            elif account_type.lower() == "margin":
                # Standard margin account: Use IBKR margin requirements
                margin_req = await self._calculate_standard_margin(strategy)
                buying_power_used = margin_req * 2  # 50% margin requirement
                
            elif account_type.lower() == "portfolio_margin":
                # Portfolio margin: Risk-based calculations
                margin_req = await self._calculate_portfolio_margin(strategy)
                buying_power_used = margin_req
                
            else:
                raise ValueError(f"Unknown account type: {account_type}")
                
            return {
                'margin_requirement': margin_req,
                'buying_power_used': buying_power_used,
                'account_type': account_type,
                'strategy_type': strategy.type.value
            }
            
        except Exception as e:
            logger.error(f"Error calculating margin requirement: {e}")
            raise ValueError(f"Margin calculation failed: {e}")

    async def _calculate_cash_margin(self, strategy: Strategy) -> float:
        """Calculate margin for cash account."""
        # In cash account, must have full premium for purchases
        total_debit = 0.0
        
        for leg in strategy.legs:
            if leg.action.value == "BUY":
                # Must have full premium
                premium = leg.contract.ask * leg.quantity * 100
                total_debit += premium
                
        return max(total_debit, abs(strategy.max_loss))

    async def _calculate_standard_margin(self, strategy: Strategy) -> float:
        """Calculate margin for standard margin account."""
        # Use max loss as conservative estimate
        # In practice, would query IBKR for exact requirements
        return abs(strategy.max_loss)

    async def _calculate_portfolio_margin(self, strategy: Strategy) -> float:
        """Calculate portfolio margin requirement."""
        # Simplified portfolio margin calculation
        # Would need more sophisticated risk modeling in practice
        max_loss = abs(strategy.max_loss)
        
        # Portfolio margin typically 15-20% of max loss
        margin_multiplier = 0.20  # 20% of max loss
        return max_loss * margin_multiplier

    async def suggest_stop_loss(
        self, 
        entry_price: float, 
        strategy_type: StrategyType,
        custom_percent: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Suggest stop loss levels based on strategy type and entry price.
        
        Args:
            entry_price: Entry price of the position
            strategy_type: Type of options strategy
            custom_percent: Custom stop loss percentage
            
        Returns:
            Dictionary with stop loss recommendations
        """
        try:
            stop_percent = custom_percent or self.default_stop_loss_percent
            
            # Adjust stop loss based on strategy type
            strategy_multipliers = {
                StrategyType.BULL_CALL_SPREAD: 1.0,
                StrategyType.BEAR_PUT_SPREAD: 1.0,
                StrategyType.BULL_PUT_SPREAD: 0.5,  # Credit strategies need tighter stops
                StrategyType.BEAR_CALL_SPREAD: 0.5,
                StrategyType.LONG_STRADDLE: 1.5,  # Volatility strategies need wider stops
                StrategyType.LONG_STRANGLE: 1.5,
                StrategyType.COVERED_CALL: 0.8,
                StrategyType.CASH_SECURED_PUT: 0.8
            }
            
            multiplier = strategy_multipliers.get(strategy_type, 1.0)
            adjusted_stop_percent = stop_percent * multiplier
            
            # Calculate stop levels
            if entry_price > 0:  # Debit strategy
                stop_loss_price = entry_price * (1 - adjusted_stop_percent / 100)
                stop_loss_amount = entry_price - stop_loss_price
            else:  # Credit strategy
                stop_loss_price = abs(entry_price) * (1 + adjusted_stop_percent / 100)
                stop_loss_amount = stop_loss_price - abs(entry_price)
                
            # Calculate trailing stop levels
            trailing_stop_percent = adjusted_stop_percent * 0.75  # Tighter trailing stop
            
            recommendations = {
                'fixed_stop_loss': {
                    'price': stop_loss_price,
                    'amount': stop_loss_amount,
                    'percent': adjusted_stop_percent
                },
                'trailing_stop': {
                    'percent': trailing_stop_percent,
                    'amount': entry_price * (trailing_stop_percent / 100)
                },
                'strategy_type': strategy_type.value,
                'entry_price': entry_price,
                'recommendation': self._get_stop_loss_recommendation(strategy_type)
            }
            
            logger.info(
                f"Stop loss suggestion for {strategy_type.value}: "
                f"{adjusted_stop_percent:.1f}% at ${stop_loss_price:.2f}"
            )
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error calculating stop loss: {e}")
            raise ValueError(f"Stop loss calculation failed: {e}")

    def _get_stop_loss_recommendation(self, strategy_type: StrategyType) -> str:
        """Get text recommendation for stop loss based on strategy type."""
        recommendations = {
            StrategyType.BULL_CALL_SPREAD: "Set stop at 25-50% of max loss to preserve capital",
            StrategyType.BEAR_PUT_SPREAD: "Set stop at 25-50% of max loss to preserve capital", 
            StrategyType.BULL_PUT_SPREAD: "Close early if underlying drops below put strike",
            StrategyType.BEAR_CALL_SPREAD: "Close early if underlying rises above call strike",
            StrategyType.LONG_STRADDLE: "Use wider stops due to volatility exposure",
            StrategyType.LONG_STRANGLE: "Use wider stops due to volatility exposure",
            StrategyType.COVERED_CALL: "Consider rolling call higher if underlying rises",
            StrategyType.CASH_SECURED_PUT: "Be prepared to take assignment or roll down"
        }
        
        return recommendations.get(
            strategy_type, 
            "Monitor position closely and exit if losses exceed risk tolerance"
        )

    async def calculate_kelly_criterion(
        self, 
        win_rate: float, 
        avg_win: float, 
        avg_loss: float
    ) -> Dict[str, float]:
        """
        Calculate Kelly Criterion for position sizing.
        
        Args:
            win_rate: Historical win rate (0.0 to 1.0)
            avg_win: Average winning trade amount
            avg_loss: Average losing trade amount (positive number)
            
        Returns:
            Dictionary with Kelly percentage and adjusted recommendations
        """
        try:
            if not 0 <= win_rate <= 1:
                raise ValueError("Win rate must be between 0 and 1")
                
            if avg_win <= 0 or avg_loss <= 0:
                raise ValueError("Average win and loss must be positive")
                
            # Kelly formula: f = (bp - q) / b
            # where: b = odds (avg_win/avg_loss), p = win_rate, q = loss_rate
            b = avg_win / avg_loss
            p = win_rate
            q = 1 - win_rate
            
            kelly_fraction = (b * p - q) / b
            kelly_percent = kelly_fraction * 100
            
            # Apply safety adjustments
            # Never bet more than 25% even if Kelly suggests it
            conservative_kelly = min(kelly_percent * 0.25, 25.0)  # Quarter Kelly
            safe_kelly = min(kelly_percent * 0.5, 15.0)  # Half Kelly
            
            # Calculate expected value
            expected_value = (avg_win * win_rate) - (avg_loss * (1 - win_rate))
            
            results = {
                'kelly_percent': kelly_percent,
                'conservative_kelly': conservative_kelly,
                'safe_kelly': safe_kelly,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'odds_ratio': b,
                'expected_value': expected_value,
                'recommendation': self._get_kelly_recommendation(kelly_percent)
            }
            
            logger.info(f"Kelly Criterion: {kelly_percent:.1f}%, Conservative: {conservative_kelly:.1f}%")
            
            return results
            
        except Exception as e:
            logger.error(f"Error calculating Kelly criterion: {e}")
            raise ValueError(f"Kelly calculation failed: {e}")

    def _get_kelly_recommendation(self, kelly_percent: float) -> str:
        """Get recommendation based on Kelly percentage."""
        if kelly_percent <= 0:
            return "Negative edge - avoid this strategy"
        elif kelly_percent <= 5:
            return "Small edge - use minimal position sizing"
        elif kelly_percent <= 15:
            return "Moderate edge - use conservative position sizing"
        elif kelly_percent <= 25:
            return "Good edge - use moderate position sizing with quarter-Kelly"
        else:
            return "Strong edge - use conservative sizing despite high Kelly (max 25%)"

    async def calculate_risk_adjusted_size(
        self,
        account_value: float,
        strategy: Strategy,
        confidence_level: float = 0.95
    ) -> Dict[str, Any]:
        """
        Calculate risk-adjusted position size considering multiple factors.
        
        Args:
            account_value: Total account value
            strategy: Options strategy
            confidence_level: Confidence level for risk calculations
            
        Returns:
            Dictionary with position sizing recommendations
        """
        try:
            # Base position size from account percentage
            base_size = await self.calculate_position_size(account_value)
            
            # Adjust for strategy risk
            max_loss = abs(strategy.max_loss)
            if max_loss > 0:
                risk_adjusted_size = min(base_size, max_loss)
            else:
                risk_adjusted_size = base_size * 0.5  # Conservative for undefined risk
                
            # Adjust for liquidity (simplified)
            liquidity_factor = 1.0
            for leg in strategy.legs:
                if leg.contract.volume < 50:
                    liquidity_factor *= 0.8  # Reduce size for low volume
                if leg.contract.open_interest < 100:
                    liquidity_factor *= 0.9  # Reduce size for low OI
                    
            liquidity_adjusted_size = risk_adjusted_size * liquidity_factor
            
            # Final recommended size
            recommended_size = min(liquidity_adjusted_size, base_size)
            
            # Calculate number of contracts
            cost_per_contract = abs(strategy.net_debit_credit)
            if cost_per_contract > 0:
                max_contracts = int(recommended_size / cost_per_contract)
            else:
                max_contracts = int(recommended_size / max_loss) if max_loss > 0 else 1
                
            return {
                'recommended_size': recommended_size,
                'max_contracts': max_contracts,
                'base_size': base_size,
                'risk_adjusted_size': risk_adjusted_size,
                'liquidity_factor': liquidity_factor,
                'account_percentage': (recommended_size / account_value) * 100,
                'confidence_level': confidence_level
            }
            
        except Exception as e:
            logger.error(f"Error calculating risk-adjusted size: {e}")
            raise ValueError(f"Risk-adjusted sizing failed: {e}")