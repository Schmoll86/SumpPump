"""
Risk validation module for SumpPump.
Provides safety checks, confirmation validation, and trading constraints enforcement.
"""

import asyncio
from typing import Dict, Any, Optional, List
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from src.models import Strategy, OptionContract
from src.config import config


# Custom Exception Classes
class ConfirmationRequiredError(Exception):
    """Raised when mandatory confirmation is missing or invalid."""
    pass


class PositionTooLargeError(Exception):
    """Raised when position size exceeds account limits."""
    pass


class InsufficientMarginError(Exception):
    """Raised when account lacks sufficient margin for trade."""
    pass


class LiquidityError(Exception):
    """Raised when option contracts have insufficient liquidity."""
    pass


class RiskLimitExceededError(Exception):
    """Raised when trade would exceed risk limits."""
    pass


class InvalidStrategyError(Exception):
    """Raised when strategy parameters are invalid."""
    pass


class RiskValidator:
    """
    Risk validator for options trading operations.
    Enforces safety checks and validates all trading constraints.
    """

    def __init__(self):
        """Initialize risk validator with configuration."""
        self.max_position_percent = config.risk.max_position_size_percent
        self.require_confirmation = config.risk.require_confirmation
        self.min_option_volume = config.risk.min_option_volume
        self.min_open_interest = config.risk.min_open_interest

    async def validate_confirmation(self, confirm_token: str) -> bool:
        """
        Validate mandatory confirmation token.
        
        Args:
            confirm_token: Confirmation token from user
            
        Returns:
            True if valid confirmation
            
        Raises:
            ConfirmationRequiredError: If confirmation is missing or invalid
        """
        if not self.require_confirmation:
            logger.warning("Confirmation requirement is disabled - this is dangerous!")
            return True
            
        if not confirm_token:
            raise ConfirmationRequiredError(
                "Confirmation token is required for all trades. "
                "User must explicitly confirm with token 'USER_CONFIRMED'"
            )
            
        if confirm_token != "USER_CONFIRMED":
            raise ConfirmationRequiredError(
                f"Invalid confirmation token: '{confirm_token}'. "
                "Must be exactly 'USER_CONFIRMED' to proceed with trade."
            )
            
        logger.info("Trade confirmation validated successfully")
        return True

    async def validate_position_size(
        self, 
        position_value: float, 
        account_value: float, 
        max_percent: Optional[float] = None
    ) -> bool:
        """
        Validate position size against account limits.
        
        Args:
            position_value: Value of the position in dollars
            account_value: Total account value
            max_percent: Maximum percentage allowed (defaults to config)
            
        Returns:
            True if position size is valid
            
        Raises:
            PositionTooLargeError: If position exceeds limits
            ValueError: If inputs are invalid
        """
        if account_value <= 0:
            raise ValueError("Account value must be positive")
            
        if position_value < 0:
            raise ValueError("Position value cannot be negative")
            
        max_allowed_percent = max_percent or self.max_position_percent
        max_allowed_value = account_value * (max_allowed_percent / 100)
        position_percent = (position_value / account_value) * 100
        
        if position_value > max_allowed_value:
            raise PositionTooLargeError(
                f"Position size ${position_value:,.2f} ({position_percent:.1f}%) "
                f"exceeds maximum allowed ${max_allowed_value:,.2f} ({max_allowed_percent:.1f}%). "
                f"Reduce position size or increase risk tolerance."
            )
            
        # Warning for positions over 2%
        if position_percent > 2.0:
            logger.warning(
                f"Large position size: {position_percent:.1f}% of account. "
                f"Consider risk management implications."
            )
            
        logger.info(f"Position size validated: ${position_value:,.2f} ({position_percent:.1f}%)")
        return True

    async def validate_strategy_risk(
        self, 
        strategy: Strategy, 
        account_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Comprehensive strategy risk validation.
        
        Args:
            strategy: Options strategy to validate
            account_info: Account information including balance, margin, etc.
            
        Returns:
            Validation results with warnings and recommendations
            
        Raises:
            InvalidStrategyError: If strategy has critical issues
            RiskLimitExceededError: If strategy exceeds risk limits
        """
        validation_result = {
            'is_valid': True,
            'warnings': [],
            'errors': [],
            'recommendations': []
        }
        
        try:
            account_value = account_info.get('total_value', 0)
            available_margin = account_info.get('available_margin', 0)
            
            if account_value <= 0:
                raise InvalidStrategyError("Invalid account value for risk validation")
                
            # Validate max loss
            max_loss = abs(strategy.max_loss)
            if max_loss <= 0:
                validation_result['errors'].append("Strategy has no defined maximum loss")
                validation_result['is_valid'] = False
                
            # Check position size
            try:
                await self.validate_position_size(max_loss, account_value)
            except PositionTooLargeError as e:
                validation_result['errors'].append(str(e))
                validation_result['is_valid'] = False
                
            # Validate required capital
            required_capital = strategy.required_capital
            if required_capital > account_value:
                validation_result['errors'].append(
                    f"Required capital ${required_capital:,.2f} exceeds account value"
                )
                validation_result['is_valid'] = False
                
            # Check margin requirements
            if required_capital > available_margin:
                validation_result['warnings'].append(
                    f"Required capital ${required_capital:,.2f} may exceed available margin"
                )
                
            # Validate breakeven points
            if not strategy.breakeven or len(strategy.breakeven) == 0:
                validation_result['warnings'].append("No breakeven points calculated")
                
            # Check risk-reward ratio
            if strategy.max_profit > 0 and max_loss > 0:
                risk_reward = strategy.max_profit / max_loss
                if risk_reward < 0.5:
                    validation_result['warnings'].append(
                        f"Poor risk-reward ratio: {risk_reward:.2f} (prefer > 1.0)"
                    )
                elif risk_reward >= 2.0:
                    validation_result['recommendations'].append(
                        f"Excellent risk-reward ratio: {risk_reward:.2f}"
                    )
                    
            # Check probability of profit
            if strategy.probability_profit:
                if strategy.probability_profit < 0.4:
                    validation_result['warnings'].append(
                        f"Low probability of profit: {strategy.probability_profit:.1%}"
                    )
                elif strategy.probability_profit > 0.7:
                    validation_result['recommendations'].append(
                        f"High probability of profit: {strategy.probability_profit:.1%}"
                    )
                    
            # Validate expiration dates
            for i, leg in enumerate(strategy.legs):
                days_to_expiry = (leg.contract.expiry.date() - 
                                 leg.contract.expiry.now().date()).days
                
                if days_to_expiry <= 0:
                    validation_result['errors'].append(f"Leg {i+1} is expired")
                    validation_result['is_valid'] = False
                elif days_to_expiry <= 7:
                    validation_result['warnings'].append(
                        f"Leg {i+1} expires in {days_to_expiry} days (high time decay)"
                    )
                    
        except Exception as e:
            logger.error(f"Error in strategy risk validation: {e}")
            validation_result['errors'].append(f"Validation error: {e}")
            validation_result['is_valid'] = False
            
        return validation_result

    async def validate_liquidity(self, option_contract: OptionContract) -> bool:
        """
        Validate option contract liquidity requirements.
        
        Args:
            option_contract: Option contract to validate
            
        Returns:
            True if liquidity is adequate
            
        Raises:
            LiquidityError: If liquidity is insufficient
        """
        issues = []
        
        # Check volume
        if option_contract.volume < self.min_option_volume:
            issues.append(
                f"Low volume: {option_contract.volume} "
                f"(minimum {self.min_option_volume})"
            )
            
        # Check open interest
        if option_contract.open_interest < self.min_open_interest:
            issues.append(
                f"Low open interest: {option_contract.open_interest} "
                f"(minimum {self.min_open_interest})"
            )
            
        # Check bid-ask spread
        if option_contract.bid > 0 and option_contract.ask > 0:
            spread = option_contract.ask - option_contract.bid
            mid_price = (option_contract.bid + option_contract.ask) / 2
            
            if mid_price > 0:
                spread_percent = spread / mid_price
                if spread_percent > 0.15:  # 15% spread threshold
                    issues.append(
                        f"Wide bid-ask spread: {spread_percent:.1%} "
                        f"(${spread:.2f})"
                    )
                    
        # Check for zero bid/ask
        if option_contract.bid <= 0 or option_contract.ask <= 0:
            issues.append("Option has zero bid or ask price")
            
        if issues:
            error_msg = (
                f"Liquidity issues for {option_contract.symbol} "
                f"{option_contract.strike}{option_contract.right.value}: "
                f"{', '.join(issues)}"
            )
            raise LiquidityError(error_msg)
            
        logger.info(
            f"Liquidity validated for {option_contract.symbol} "
            f"{option_contract.strike}{option_contract.right.value}"
        )
        return True

    async def check_margin_requirements(
        self, 
        strategy: Strategy, 
        available_margin: float,
        account_type: str = "margin"
    ) -> bool:
        """
        Check if sufficient margin is available for strategy.
        
        Args:
            strategy: Options strategy
            available_margin: Available margin in account
            account_type: Type of account (cash, margin, portfolio_margin)
            
        Returns:
            True if sufficient margin
            
        Raises:
            InsufficientMarginError: If margin is insufficient
        """
        required_margin = strategy.required_capital
        
        # Add buffer for margin requirements
        margin_buffer = 1.2  # 20% buffer
        required_with_buffer = required_margin * margin_buffer
        
        if account_type.lower() == "cash":
            # Cash accounts need full premium for purchases
            cash_requirement = 0.0
            for leg in strategy.legs:
                if leg.action.value == "BUY":
                    premium = leg.contract.ask * leg.quantity * 100
                    cash_requirement += premium
                    
            if cash_requirement > available_margin:
                raise InsufficientMarginError(
                    f"Insufficient cash: ${cash_requirement:,.2f} required, "
                    f"${available_margin:,.2f} available"
                )
                
        elif required_with_buffer > available_margin:
            raise InsufficientMarginError(
                f"Insufficient margin: ${required_with_buffer:,.2f} required "
                f"(including 20% buffer), ${available_margin:,.2f} available"
            )
            
        logger.info(
            f"Margin check passed: ${required_margin:,.2f} required, "
            f"${available_margin:,.2f} available"
        )
        return True

    async def validate_trade_execution(
        self,
        strategy: Strategy,
        account_info: Dict[str, Any],
        confirm_token: str,
        max_position_percent: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive pre-execution validation.
        
        Args:
            strategy: Strategy to execute
            account_info: Account information
            confirm_token: User confirmation token
            max_position_percent: Override max position percentage
            
        Returns:
            Validation results
            
        Raises:
            Various validation errors if checks fail
        """
        validation_start_time = asyncio.get_event_loop().time()
        
        try:
            # CRITICAL: Always validate confirmation first
            await self.validate_confirmation(confirm_token)
            
            # Extract account info
            account_value = account_info.get('total_value', 0)
            available_margin = account_info.get('available_margin', 0)
            account_type = account_info.get('account_type', 'margin')
            
            # Validate strategy risk
            strategy_validation = await self.validate_strategy_risk(strategy, account_info)
            if not strategy_validation['is_valid']:
                raise InvalidStrategyError(
                    f"Strategy validation failed: {strategy_validation['errors']}"
                )
                
            # Check position size
            position_value = abs(strategy.max_loss)
            await self.validate_position_size(
                position_value, 
                account_value, 
                max_position_percent
            )
            
            # Check margin requirements
            await self.check_margin_requirements(
                strategy, 
                available_margin, 
                account_type
            )
            
            # Validate liquidity for all legs
            liquidity_issues = []
            for i, leg in enumerate(strategy.legs):
                try:
                    await self.validate_liquidity(leg.contract)
                except LiquidityError as e:
                    liquidity_issues.append(f"Leg {i+1}: {str(e)}")
                    
            if liquidity_issues:
                logger.warning(f"Liquidity warnings: {liquidity_issues}")
                # Don't block trade for liquidity warnings, just log
                
            validation_time = asyncio.get_event_loop().time() - validation_start_time
            
            # MANDATORY: Display max loss
            max_loss = abs(strategy.max_loss)
            print(f"\n{'='*50}")
            print(f"MAX LOSS: ${max_loss:,.2f}")
            print(f"REQUIRED CAPITAL: ${strategy.required_capital:,.2f}")
            print(f"ACCOUNT IMPACT: {(position_value/account_value)*100:.1f}%")
            print(f"{'='*50}\n")
            
            return {
                'validation_passed': True,
                'max_loss_displayed': True,
                'confirmation_validated': True,
                'position_size_validated': True,
                'margin_validated': True,
                'liquidity_warnings': liquidity_issues,
                'strategy_warnings': strategy_validation.get('warnings', []),
                'validation_time_ms': validation_time * 1000
            }
            
        except Exception as e:
            logger.error(f"Trade execution validation failed: {e}")
            raise

    async def enforce_stop_loss_prompt(
        self, 
        strategy: Strategy, 
        execution_price: float
    ) -> Dict[str, Any]:
        """
        Enforce mandatory stop loss setup after trade execution.
        
        Args:
            strategy: Executed strategy
            execution_price: Actual execution price
            
        Returns:
            Stop loss recommendation and prompts
        """
        try:
            from .calculator import RiskCalculator
            calculator = RiskCalculator()
            
            # Calculate stop loss recommendation
            stop_recommendation = await calculator.suggest_stop_loss(
                execution_price, 
                strategy.type
            )
            
            # Mandatory display
            print(f"\n{'='*60}")
            print(f"MANDATORY STOP LOSS SETUP")
            print(f"{'='*60}")
            print(f"Strategy: {strategy.name}")
            print(f"Entry Price: ${execution_price:.2f}")
            print(f"Suggested Stop: ${stop_recommendation['fixed_stop_loss']['price']:.2f}")
            print(f"Stop Loss Amount: ${stop_recommendation['fixed_stop_loss']['amount']:.2f}")
            print(f"Stop Percentage: {stop_recommendation['fixed_stop_loss']['percent']:.1f}%")
            print(f"")
            print(f"RECOMMENDATION: {stop_recommendation['recommendation']}")
            print(f"{'='*60}")
            print(f"SET STOP LOSS NOW - DO NOT SKIP THIS STEP!")
            print(f"{'='*60}\n")
            
            return {
                'stop_loss_prompted': True,
                'stop_recommendation': stop_recommendation,
                'mandatory_setup': True,
                'entry_price': execution_price
            }
            
        except Exception as e:
            logger.error(f"Error in stop loss prompt: {e}")
            raise ValueError(f"Stop loss setup failed: {e}")

    async def validate_account_permissions(
        self, 
        account_info: Dict[str, Any], 
        strategy: Strategy
    ) -> bool:
        """
        Validate account has required permissions for strategy.
        
        Args:
            account_info: Account information
            strategy: Strategy requiring validation
            
        Returns:
            True if permissions are adequate
            
        Raises:
            InvalidStrategyError: If account lacks required permissions
        """
        account_type = account_info.get('account_type', 'cash')
        permissions = account_info.get('trading_permissions', [])
        
        required_permissions = []
        
        # Determine required permissions based on strategy
        if any(leg.action.value == "SELL" for leg in strategy.legs):
            if any(leg.contract.right.value == "C" for leg in strategy.legs 
                   if leg.action.value == "SELL"):
                required_permissions.append('sell_calls')
                
            if any(leg.contract.right.value == "P" for leg in strategy.legs 
                   if leg.action.value == "SELL"):
                required_permissions.append('sell_puts')
                
        if len(strategy.legs) > 1:
            required_permissions.append('spread_trading')
            
        # Check permissions
        missing_permissions = []
        for perm in required_permissions:
            if perm not in permissions:
                missing_permissions.append(perm)
                
        if missing_permissions:
            raise InvalidStrategyError(
                f"Account lacks required permissions: {missing_permissions}. "
                f"Contact broker to enable: {', '.join(missing_permissions)}"
            )
            
        logger.info(f"Account permissions validated for {strategy.name}")
        return True