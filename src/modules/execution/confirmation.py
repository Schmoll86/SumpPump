"""
Trade Confirmation and Safety Management System

This module provides mandatory confirmation workflows and safety checks for all trades.
No trade can be executed without explicit user confirmation via the "USER_CONFIRMED" token.

CRITICAL SAFETY FEATURES:
- Mandatory confirmation for ALL trades
- Prominent max loss display
- Stop loss prompts after EVERY fill
- Risk disclosure and warnings
- Audit trail for all confirmations
"""

import asyncio
import uuid
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from src.models import Strategy, ExecutionResult, StrategyType, OptionRight


class ConfirmationError(Exception):
    """Raised when confirmation process fails or is invalid."""
    pass


class StopLossRequiredError(Exception):
    """Raised when stop loss is required but not provided."""
    pass


@dataclass
class ConfirmationRequest:
    """Represents a trade confirmation request."""
    confirmation_id: str
    strategy: Strategy
    max_loss: float
    max_profit: float
    net_debit: float
    breakeven_points: List[float]
    timestamp: datetime
    expires_at: datetime
    risk_warnings: List[str]
    
    def is_expired(self) -> bool:
        """Check if confirmation request has expired."""
        return datetime.now() > self.expires_at


@dataclass
class PreExecutionSummary:
    """Summary displayed before trade execution."""
    strategy_name: str
    symbol: str
    strategy_type: str
    legs: List[Dict[str, Any]]
    net_debit: float
    max_loss: float
    max_profit: float
    breakeven: List[float]
    probability_profit: Optional[float]
    margin_requirement: float
    commission_estimate: float
    risk_warnings: List[str]
    level2_compliance: bool


@dataclass
class StopLossPrompt:
    """Stop loss prompt after trade execution."""
    execution_id: str
    strategy_name: str
    fill_price: float
    max_loss: float
    suggested_stops: List[Dict[str, Any]]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH'
    prompt_timestamp: datetime


class ConfirmationManager:
    """
    Manages trade confirmations and safety workflows.
    
    SAFETY PRINCIPLES:
    1. No trade without explicit "USER_CONFIRMED" token
    2. All risks clearly displayed
    3. Stop loss prompted after every fill
    4. Complete audit trail maintained
    5. Time-limited confirmations (prevent stale orders)
    """
    
    # Confirmation validity period
    CONFIRMATION_TIMEOUT_MINUTES = 10
    
    # Required confirmation token
    REQUIRED_TOKEN = "USER_CONFIRMED"
    
    # Risk level thresholds (as percentage of account)
    RISK_LEVELS = {
        'LOW': 0.02,      # < 2% of account
        'MEDIUM': 0.05,   # 2-5% of account
        'HIGH': 0.05,     # > 5% of account
    }
    
    def __init__(self):
        """Initialize confirmation manager."""
        self._active_confirmations: Dict[str, ConfirmationRequest] = {}
        self._confirmation_history: List[ConfirmationRequest] = []
        self._stop_loss_prompts: List[StopLossPrompt] = []
    
    def generate_confirmation_id(self) -> str:
        """
        Generate unique confirmation ID for audit trail.
        
        Returns:
            Unique confirmation ID
        """
        # Use timestamp + UUID for uniqueness and traceability
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        return f"CONFIRM_{timestamp}_{unique_id}"
    
    def request_confirmation(
        self, 
        strategy: Strategy, 
        account_balance: float = 100000.0  # Default for margin calculation
    ) -> Dict[str, Any]:
        """
        Request user confirmation for strategy execution.
        
        Args:
            strategy: Strategy to confirm
            account_balance: Account balance for risk calculation
            
        Returns:
            Confirmation request with all safety information
            
        Note:
            This returns the confirmation UI data. User must respond with
            "USER_CONFIRMED" token to proceed.
        """
        # Generate unique confirmation ID
        confirmation_id = self.generate_confirmation_id()
        
        # Calculate risk metrics
        max_loss = abs(strategy.max_loss)
        risk_percentage = (max_loss / account_balance) * 100
        
        # Generate risk warnings
        risk_warnings = self._generate_risk_warnings(strategy, risk_percentage)
        
        # Create confirmation request
        confirmation_request = ConfirmationRequest(
            confirmation_id=confirmation_id,
            strategy=strategy,
            max_loss=max_loss,
            max_profit=strategy.max_profit,
            net_debit=abs(strategy.net_debit_credit),
            breakeven_points=strategy.breakeven,
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=self.CONFIRMATION_TIMEOUT_MINUTES),
            risk_warnings=risk_warnings
        )
        
        # Store active confirmation
        self._active_confirmations[confirmation_id] = confirmation_request
        
        # Log confirmation request
        logger.info(
            f"Confirmation requested for {strategy.name} "
            f"(ID: {confirmation_id}, Max Loss: ${max_loss:.2f})"
        )
        
        # Return confirmation UI data
        return {
            'confirmation_id': confirmation_id,
            'requires_token': self.REQUIRED_TOKEN,
            'summary': self.display_pre_execution_summary(strategy),
            'expires_in_minutes': self.CONFIRMATION_TIMEOUT_MINUTES,
            'risk_warnings': risk_warnings,
            'max_loss_prominent': f"⚠️  MAX LOSS: ${max_loss:.2f} ({risk_percentage:.1f}% of account) ⚠️",
            'confirmation_instructions': [
                "1. Review all strategy details carefully",
                "2. Verify the MAX LOSS amount is acceptable",
                "3. Confirm you understand all risks",
                f"4. Respond with confirmation token: '{self.REQUIRED_TOKEN}'",
                "5. Be prepared to set stop loss after execution"
            ]
        }
    
    def validate_confirmation_token(self, confirmation_id: str, token: str) -> bool:
        """
        Validate confirmation token and process confirmation.
        
        Args:
            confirmation_id: Confirmation request ID
            token: User-provided confirmation token
            
        Returns:
            True if token is valid and confirmation processed
            
        Raises:
            ConfirmationError: If token invalid or confirmation expired
        """
        # Check if confirmation exists
        if confirmation_id not in self._active_confirmations:
            raise ConfirmationError(
                f"Invalid confirmation ID: {confirmation_id}. "
                f"Request may have expired or does not exist."
            )
        
        confirmation_request = self._active_confirmations[confirmation_id]
        
        # Check if confirmation expired
        if confirmation_request.is_expired():
            # Remove expired confirmation
            del self._active_confirmations[confirmation_id]
            raise ConfirmationError(
                f"Confirmation expired. Please request new confirmation. "
                f"Confirmations expire after {self.CONFIRMATION_TIMEOUT_MINUTES} minutes."
            )
        
        # Validate token (CRITICAL SAFETY CHECK)
        if token != self.REQUIRED_TOKEN:
            logger.warning(
                f"Invalid confirmation token provided: '{token}' "
                f"(Expected: '{self.REQUIRED_TOKEN}')"
            )
            raise ConfirmationError(
                f"Invalid confirmation token. Required: '{self.REQUIRED_TOKEN}', "
                f"provided: '{token}'"
            )
        
        # Move to confirmation history
        self._confirmation_history.append(confirmation_request)
        del self._active_confirmations[confirmation_id]
        
        logger.info(
            f"Confirmation validated for {confirmation_request.strategy.name} "
            f"(ID: {confirmation_id})"
        )
        
        return True
    
    def display_pre_execution_summary(self, strategy: Strategy) -> PreExecutionSummary:
        """
        Generate detailed pre-execution summary.
        
        Args:
            strategy: Strategy to summarize
            
        Returns:
            Comprehensive execution summary
        """
        # Build leg details
        leg_details = []
        for i, leg in enumerate(strategy.legs):
            leg_info = {
                'leg_number': i + 1,
                'action': leg.action.value,
                'contract': f"{leg.contract.symbol} {leg.contract.expiry.strftime('%m/%d/%Y')} "
                          f"${leg.contract.strike} {leg.contract.right.value}",
                'quantity': leg.quantity,
                'price': leg.contract.ask if leg.action.value == 'BUY' else leg.contract.bid,
                'cost': abs(leg.cost),
                'direction': 'Debit' if leg.action.value == 'BUY' else 'Credit'
            }
            leg_details.append(leg_info)
        
        # Estimate commission (rough estimate)
        commission_estimate = len(strategy.legs) * 1.0  # $1 per leg
        
        # Check Level 2 compliance
        level2_compliant = self._check_level2_compliance(strategy)
        
        # Generate risk warnings
        risk_warnings = self._generate_strategy_specific_warnings(strategy)
        
        return PreExecutionSummary(
            strategy_name=strategy.name,
            symbol=strategy.legs[0].contract.symbol,
            strategy_type=strategy.type.value,
            legs=leg_details,
            net_debit=abs(strategy.net_debit_credit),
            max_loss=abs(strategy.max_loss),
            max_profit=strategy.max_profit,
            breakeven=strategy.breakeven,
            probability_profit=strategy.probability_profit,
            margin_requirement=abs(strategy.net_debit_credit),  # For Level 2, margin = net debit
            commission_estimate=commission_estimate,
            risk_warnings=risk_warnings,
            level2_compliance=level2_compliant
        )
    
    def prompt_for_stop_loss(self, execution_result: ExecutionResult) -> StopLossPrompt:
        """
        MANDATORY: Prompt for stop loss after trade execution.
        
        Args:
            execution_result: Result of trade execution
            
        Returns:
            Stop loss prompt with suggestions
            
        Note:
            This MUST be called after every successful fill.
        """
        strategy = execution_result.strategy
        fill_price = sum(execution_result.fill_prices.values()) / len(execution_result.fill_prices)
        max_loss = abs(strategy.max_loss)
        
        # Calculate risk level
        risk_level = self._calculate_risk_level(max_loss, 100000.0)  # Assume $100k account
        
        # Generate stop loss suggestions
        suggested_stops = self._generate_stop_loss_suggestions(strategy, fill_price)
        
        # Create stop loss prompt
        stop_prompt = StopLossPrompt(
            execution_id=execution_result.order_id,
            strategy_name=strategy.name,
            fill_price=fill_price,
            max_loss=max_loss,
            suggested_stops=suggested_stops,
            risk_level=risk_level,
            prompt_timestamp=datetime.now()
        )
        
        # Store prompt for tracking
        self._stop_loss_prompts.append(stop_prompt)
        
        logger.critical(
            f"STOP LOSS REQUIRED: Trade executed for {strategy.name} "
            f"(Execution ID: {execution_result.order_id}). "
            f"Set stop loss to manage risk!"
        )
        
        return stop_prompt
    
    def _generate_risk_warnings(self, strategy: Strategy, risk_percentage: float) -> List[str]:
        """Generate comprehensive risk warnings for strategy."""
        warnings = [
            f"⚠️  MAXIMUM LOSS: ${abs(strategy.max_loss):.2f} ({risk_percentage:.1f}% of account)",
            f"💰 NET DEBIT: ${abs(strategy.net_debit_credit):.2f} (paid upfront)",
            "📊 This is a DEBIT strategy - you pay premium upfront",
        ]
        
        # Add risk level warnings
        if risk_percentage > 5:
            warnings.append("🔴 HIGH RISK: This trade represents >5% of account value")
        elif risk_percentage > 2:
            warnings.append("🟡 MEDIUM RISK: This trade represents 2-5% of account value")
        else:
            warnings.append("🟢 LOW RISK: This trade represents <2% of account value")
        
        # Add strategy-specific warnings
        strategy_warnings = self._generate_strategy_specific_warnings(strategy)
        warnings.extend(strategy_warnings)
        
        return warnings
    
    def _generate_strategy_specific_warnings(self, strategy: Strategy) -> List[str]:
        """Generate warnings specific to strategy type."""
        warnings = []
        
        if strategy.type == StrategyType.LONG_CALL:
            warnings.extend([
                "📈 Requires significant upward move to profit",
                "⏰ Time decay works against this position",
                "📉 Can lose 100% of premium paid"
            ])
        
        elif strategy.type == StrategyType.LONG_PUT:
            warnings.extend([
                "📉 Requires significant downward move to profit",
                "⏰ Time decay works against this position",
                "📈 Can lose 100% of premium paid"
            ])
        
        elif strategy.type == StrategyType.BULL_CALL_SPREAD:
            warnings.extend([
                "📈 Requires upward move above breakeven by expiration",
                "🎯 Limited profit potential - capped at spread width",
                "⏰ Best managed at 50% profit or 21 DTE"
            ])
        
        elif strategy.type == StrategyType.BEAR_PUT_SPREAD:
            warnings.extend([
                "📉 Requires downward move below breakeven by expiration",
                "🎯 Limited profit potential - capped at spread width",
                "⏰ Best managed at 50% profit or 21 DTE"
            ])
        
        elif strategy.type == StrategyType.LONG_STRADDLE:
            warnings.extend([
                "💥 Requires significant move in EITHER direction",
                "⏰ High time decay - needs quick movement",
                "💰 High premium cost for both call and put"
            ])
        
        elif strategy.type == StrategyType.LONG_STRANGLE:
            warnings.extend([
                "💥 Requires significant move beyond both strikes",
                "⏰ Time decay works against position",
                "📊 Lower cost than straddle but wider breakeven range"
            ])
        
        elif strategy.type == StrategyType.COVERED_CALL:
            warnings.extend([
                "📊 Requires stock ownership (100 shares per contract)",
                "🎯 Caps upside potential at strike price",
                "📉 Still exposed to downside risk on stock"
            ])
        
        elif strategy.type == StrategyType.PROTECTIVE_PUT:
            warnings.extend([
                "📊 Requires stock ownership (100 shares per contract)",
                "💰 Insurance premium reduces potential profits",
                "⏰ Put will lose value if stock stays flat"
            ])
        
        return warnings
    
    def _check_level2_compliance(self, strategy: Strategy) -> bool:
        """Check if strategy complies with Level 2 restrictions."""
        # Level 2 allowed strategies
        level2_allowed = {
            StrategyType.LONG_CALL,
            StrategyType.LONG_PUT,
            StrategyType.BULL_CALL_SPREAD,
            StrategyType.BEAR_PUT_SPREAD,
            StrategyType.COVERED_CALL,
            StrategyType.PROTECTIVE_PUT,
            StrategyType.PROTECTIVE_CALL,
            StrategyType.COLLAR,
            StrategyType.LONG_STRADDLE,
            StrategyType.LONG_STRANGLE,
            StrategyType.LONG_IRON_CONDOR,
        }
        
        # Check strategy type
        if strategy.type not in level2_allowed:
            return False
        
        # Check net debit requirement
        if strategy.net_debit_credit >= 0:  # Must be net debit
            return False
        
        return True
    
    def _calculate_risk_level(self, max_loss: float, account_balance: float) -> str:
        """Calculate risk level based on max loss vs account balance."""
        risk_percentage = max_loss / account_balance
        
        if risk_percentage > self.RISK_LEVELS['HIGH']:
            return 'HIGH'
        elif risk_percentage > self.RISK_LEVELS['MEDIUM']:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _generate_stop_loss_suggestions(
        self, 
        strategy: Strategy, 
        fill_price: float
    ) -> List[Dict[str, Any]]:
        """Generate stop loss suggestions based on strategy and fill price."""
        suggestions = []
        max_loss = abs(strategy.max_loss)
        
        # Conservative stop (50% of max loss)
        conservative_stop = max_loss * 0.5
        suggestions.append({
            'type': 'Conservative',
            'stop_loss': conservative_stop,
            'percentage_of_max': 50,
            'description': 'Limit loss to 50% of maximum risk',
            'when_to_use': 'When you want to limit losses early'
        })
        
        # Moderate stop (75% of max loss)
        moderate_stop = max_loss * 0.75
        suggestions.append({
            'type': 'Moderate',
            'stop_loss': moderate_stop,
            'percentage_of_max': 75,
            'description': 'Allow more room for the trade to work',
            'when_to_use': 'Balanced approach between risk and opportunity'
        })
        
        # Time-based stop
        suggestions.append({
            'type': 'Time-based',
            'stop_loss': None,
            'percentage_of_max': None,
            'description': 'Close at 50% profit or 21 DTE, whichever comes first',
            'when_to_use': 'For spread strategies with defined risk'
        })
        
        # Technical stop (if applicable)
        if strategy.type in [StrategyType.LONG_CALL, StrategyType.LONG_PUT]:
            suggestions.append({
                'type': 'Technical',
                'stop_loss': None,
                'percentage_of_max': None,
                'description': 'Set stop based on underlying support/resistance levels',
                'when_to_use': 'When using technical analysis for entries/exits'
            })
        
        return suggestions
    
    def get_confirmation_history(self) -> List[Dict[str, Any]]:
        """
        Get history of all confirmations for audit purposes.
        
        Returns:
            List of confirmation history records
        """
        history = []
        for confirmation in self._confirmation_history:
            history.append({
                'confirmation_id': confirmation.confirmation_id,
                'strategy_name': confirmation.strategy.name,
                'timestamp': confirmation.timestamp.isoformat(),
                'max_loss': confirmation.max_loss,
                'net_debit': confirmation.net_debit,
                'status': 'CONFIRMED'
            })
        
        return history
    
    def cleanup_expired_confirmations(self) -> int:
        """
        Remove expired confirmation requests.
        
        Returns:
            Number of confirmations cleaned up
        """
        expired_ids = [
            conf_id for conf_id, confirmation in self._active_confirmations.items()
            if confirmation.is_expired()
        ]
        
        for conf_id in expired_ids:
            del self._active_confirmations[conf_id]
            logger.info(f"Cleaned up expired confirmation: {conf_id}")
        
        return len(expired_ids)
    
    def get_pending_stop_loss_prompts(self) -> List[StopLossPrompt]:
        """
        Get all pending stop loss prompts.
        
        Returns:
            List of pending stop loss prompts
        """
        # Return prompts from last 24 hours
        cutoff = datetime.now() - timedelta(hours=24)
        return [
            prompt for prompt in self._stop_loss_prompts
            if prompt.prompt_timestamp > cutoff
        ]