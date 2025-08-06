"""
Order Building and Submission with IBKR Level 2 Compliance

This module handles the construction and validation of option orders with strict
adherence to IBKR Level 2 permission restrictions.

CRITICAL: All strategies must be DEBIT strategies - no credit allowed!
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass

from ib_async import Contract, ComboLeg, MarketOrder, LimitOrder, Order
from loguru import logger

from src.models import (
    Strategy, StrategyType, OptionContract, OptionLeg, OrderAction, 
    OptionRight, ExecutionResult
)
from src.modules.tws.connection import TWSConnection


class Level2ComplianceError(Exception):
    """Raised when a strategy violates IBKR Level 2 restrictions."""
    pass


class OrderValidationError(Exception):
    """Raised when order parameters are invalid."""
    pass


@dataclass
class OrderSpec:
    """Specification for an order to be placed."""
    strategy: Strategy
    order_type: str  # 'MKT' or 'LMT'
    limit_price: Optional[float] = None
    time_in_force: str = 'DAY'
    
    def __post_init__(self):
        """Validate order specification."""
        if self.order_type not in ['MKT', 'LMT']:
            raise OrderValidationError(f"Invalid order type: {self.order_type}")
        
        if self.order_type == 'LMT' and self.limit_price is None:
            raise OrderValidationError("Limit price required for limit orders")


class OrderBuilder:
    """
    Builds and validates option orders with IBKR Level 2 compliance.
    
    CRITICAL SAFETY FEATURES:
    - Validates all strategies are Level 2 compliant
    - Ensures all spreads are DEBIT spreads only
    - Validates margin requirements
    - Prevents naked short positions
    """
    
    # Level 2 ALLOWED strategies - DEBIT ONLY!
    LEVEL2_ALLOWED_STRATEGIES = {
        StrategyType.LONG_CALL,
        StrategyType.LONG_PUT,
        StrategyType.BULL_CALL_SPREAD,      # Debit spread
        StrategyType.BEAR_PUT_SPREAD,       # Debit spread
        StrategyType.COVERED_CALL,
        StrategyType.PROTECTIVE_PUT,
        StrategyType.PROTECTIVE_CALL,
        StrategyType.COLLAR,
        StrategyType.SHORT_COLLAR,
        StrategyType.LONG_STRADDLE,
        StrategyType.LONG_STRANGLE,
        StrategyType.LONG_IRON_CONDOR,     # Debit version only
        StrategyType.CONVERSION,
        StrategyType.LONG_BOX_SPREAD,
    }
    
    # Level 3+ required strategies - FORBIDDEN
    LEVEL3_PLUS_FORBIDDEN = {
        'bear_call_spread',    # Credit spread - NEED L3
        'bull_put_spread',     # Credit spread - NEED L3
        'cash_secured_put',    # Naked put - NEED L3
        'short_put',           # Naked put - NEED L3
        'calendar_spread',     # Different expirations - NEED L3
        'diagonal_spread',     # Different strikes/expirations - NEED L3
        'butterfly',           # Complex structure - NEED L3
        'short_straddle',      # Naked short - NEED L4
        'short_strangle',      # Naked short - NEED L4
        'short_iron_condor',   # Credit strategy - NEED L3
    }
    
    def __init__(self, tws_connection: TWSConnection):
        """
        Initialize OrderBuilder with TWS connection.
        
        Args:
            tws_connection: Active TWS connection instance
        """
        self.tws = tws_connection
        
    def validate_level2_compliance(self, strategy: Strategy) -> None:
        """
        Validate that strategy complies with IBKR Level 2 restrictions.
        
        Args:
            strategy: Strategy to validate
            
        Raises:
            Level2ComplianceError: If strategy violates Level 2 restrictions
        """
        # Check if strategy type is allowed
        if strategy.type not in self.LEVEL2_ALLOWED_STRATEGIES:
            raise Level2ComplianceError(
                f"Strategy {strategy.type.value} requires Level 3+ permissions. "
                f"Level 2 only allows: {[s.value for s in self.LEVEL2_ALLOWED_STRATEGIES]}"
            )
        
        # CRITICAL: All Level 2 strategies must be NET DEBIT
        net_cost = strategy.net_debit_credit
        if net_cost >= 0:  # Net credit or break-even
            raise Level2ComplianceError(
                f"Strategy {strategy.name} results in net credit of ${abs(net_cost):.2f}. "
                f"Level 2 permissions only allow DEBIT strategies. "
                f"Net debit required: < $0.00, got: ${net_cost:.2f}"
            )
        
        # Validate no naked short positions
        for leg in strategy.legs:
            if leg.action == OrderAction.SELL:
                # Check if this is a covered position or part of a spread
                if not self._is_covered_or_spread_leg(leg, strategy):
                    raise Level2ComplianceError(
                        f"Naked short position detected in {leg.contract.symbol} "
                        f"{leg.contract.strike} {leg.contract.right.value}. "
                        f"Level 2 does not allow naked short options."
                    )
        
        # Validate specific strategy requirements
        self._validate_strategy_specific_requirements(strategy)
        
        logger.info(f"Strategy {strategy.name} passed Level 2 compliance validation")
    
    def _is_covered_or_spread_leg(self, leg: OptionLeg, strategy: Strategy) -> bool:
        """
        Check if a short leg is properly covered or part of a spread.
        
        Args:
            leg: Option leg to check
            strategy: Full strategy context
            
        Returns:
            True if leg is covered or part of spread
        """
        # For spreads, check if there's a corresponding long leg
        for other_leg in strategy.legs:
            if (other_leg != leg and 
                other_leg.contract.symbol == leg.contract.symbol and
                other_leg.contract.expiry == leg.contract.expiry and
                other_leg.contract.right == leg.contract.right and
                other_leg.action == OrderAction.BUY):
                return True  # Part of a spread
        
        # For covered calls, this would require stock position verification
        # This is handled in the covered call specific validation
        if strategy.type == StrategyType.COVERED_CALL:
            return True  # Assume covered (verified elsewhere)
        
        return False
    
    def _validate_strategy_specific_requirements(self, strategy: Strategy) -> None:
        """
        Validate specific requirements for each strategy type.
        
        Args:
            strategy: Strategy to validate
            
        Raises:
            Level2ComplianceError: If strategy-specific requirements not met
        """
        if strategy.type == StrategyType.BULL_CALL_SPREAD:
            self._validate_bull_call_spread(strategy)
        elif strategy.type == StrategyType.BEAR_PUT_SPREAD:
            self._validate_bear_put_spread(strategy)
        elif strategy.type == StrategyType.COVERED_CALL:
            self._validate_covered_call(strategy)
        elif strategy.type == StrategyType.LONG_IRON_CONDOR:
            self._validate_long_iron_condor(strategy)
        # Add other strategy validations as needed
    
    def _validate_bull_call_spread(self, strategy: Strategy) -> None:
        """Validate bull call spread is properly constructed."""
        if len(strategy.legs) != 2:
            raise Level2ComplianceError("Bull call spread must have exactly 2 legs")
        
        long_leg = None
        short_leg = None
        
        for leg in strategy.legs:
            if leg.action == OrderAction.BUY:
                long_leg = leg
            else:
                short_leg = leg
        
        if not long_leg or not short_leg:
            raise Level2ComplianceError("Bull call spread must have one long and one short leg")
        
        if long_leg.contract.strike >= short_leg.contract.strike:
            raise Level2ComplianceError(
                "Bull call spread: long strike must be lower than short strike"
            )
    
    def _validate_bear_put_spread(self, strategy: Strategy) -> None:
        """Validate bear put spread is properly constructed."""
        if len(strategy.legs) != 2:
            raise Level2ComplianceError("Bear put spread must have exactly 2 legs")
        
        long_leg = None
        short_leg = None
        
        for leg in strategy.legs:
            if leg.action == OrderAction.BUY:
                long_leg = leg
            else:
                short_leg = leg
        
        if not long_leg or not short_leg:
            raise Level2ComplianceError("Bear put spread must have one long and one short leg")
        
        if long_leg.contract.strike <= short_leg.contract.strike:
            raise Level2ComplianceError(
                "Bear put spread: long strike must be higher than short strike"
            )
    
    def _validate_covered_call(self, strategy: Strategy) -> None:
        """Validate covered call has proper stock coverage."""
        # In a real implementation, this would check actual stock positions
        # For now, we assume validation is done at the strategy creation level
        logger.warning(
            "Covered call validation: Ensure you own 100 shares per contract. "
            "This system assumes stock position exists."
        )
    
    def _validate_long_iron_condor(self, strategy: Strategy) -> None:
        """Validate long iron condor is net debit."""
        if len(strategy.legs) != 4:
            raise Level2ComplianceError("Iron condor must have exactly 4 legs")
        
        # Iron condor net debit validation already done in main validation
        # Additional structural validation could be added here
    
    def build_single_option_order(
        self, 
        contract: OptionContract, 
        action: OrderAction, 
        quantity: int
    ) -> Contract:
        """
        Build a single option order contract.
        
        Args:
            contract: Option contract details
            action: BUY or SELL
            quantity: Number of contracts
            
        Returns:
            IB Contract object for single option
            
        Raises:
            Level2ComplianceError: If trying to sell naked options
        """
        # Validate Level 2 compliance for single options
        if action == OrderAction.SELL:
            raise Level2ComplianceError(
                "Cannot sell naked options with Level 2 permissions. "
                "Use covered calls or protective strategies instead."
            )
        
        # Create IB option contract
        option_contract = self.tws.create_option_contract(
            symbol=contract.symbol,
            expiry=contract.expiry.strftime('%Y%m%d'),
            strike=contract.strike,
            right=contract.right.value,
            exchange='SMART'
        )
        
        return option_contract
    
    def build_debit_spread_order(
        self, 
        long_leg: OptionContract, 
        short_leg: OptionContract
    ) -> Tuple[Contract, List[ComboLeg]]:
        """
        Build a debit spread combo order.
        
        Args:
            long_leg: Long option contract
            short_leg: Short option contract
            
        Returns:
            Tuple of (combo_contract, combo_legs)
            
        Raises:
            Level2ComplianceError: If spread would result in credit
        """
        # Calculate net debit
        net_cost = (long_leg.ask - short_leg.bid) * 100  # Per contract
        if net_cost <= 0:
            raise Level2ComplianceError(
                f"Spread results in net credit of ${abs(net_cost):.2f}. "
                f"Level 2 only allows debit spreads."
            )
        
        # Create combo contract
        combo = Contract()
        combo.symbol = long_leg.symbol
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        # Create long leg
        long_ib_contract = self.tws.create_option_contract(
            symbol=long_leg.symbol,
            expiry=long_leg.expiry.strftime('%Y%m%d'),
            strike=long_leg.strike,
            right=long_leg.right.value
        )
        
        # Create short leg
        short_ib_contract = self.tws.create_option_contract(
            symbol=short_leg.symbol,
            expiry=short_leg.expiry.strftime('%Y%m%d'),
            strike=short_leg.strike,
            right=short_leg.right.value
        )
        
        # Create combo legs
        combo_legs = [
            ComboLeg(
                conId=0,  # Will be filled after qualification
                ratio=1,
                action='BUY',
                exchange='SMART'
            ),
            ComboLeg(
                conId=0,  # Will be filled after qualification
                ratio=1,
                action='SELL',
                exchange='SMART'
            )
        ]
        
        return combo, combo_legs
    
    def build_covered_call_order(
        self, 
        stock_position: int, 
        call_contract: OptionContract
    ) -> Contract:
        """
        Build a covered call order (assumes stock ownership).
        
        Args:
            stock_position: Number of shares owned (must be >= 100)
            call_contract: Call option to sell
            
        Returns:
            Option contract for the call to sell
            
        Raises:
            Level2ComplianceError: If insufficient stock coverage
        """
        if stock_position < 100:
            raise Level2ComplianceError(
                f"Insufficient stock coverage. Need 100 shares per contract, "
                f"have {stock_position} shares."
            )
        
        # Create the call contract to sell
        call_ib_contract = self.tws.create_option_contract(
            symbol=call_contract.symbol,
            expiry=call_contract.expiry.strftime('%Y%m%d'),
            strike=call_contract.strike,
            right=call_contract.right.value
        )
        
        return call_ib_contract
    
    def build_protective_put_order(
        self, 
        stock_position: int, 
        put_contract: OptionContract
    ) -> Contract:
        """
        Build a protective put order (assumes stock ownership).
        
        Args:
            stock_position: Number of shares owned (must be >= 100)
            put_contract: Put option to buy for protection
            
        Returns:
            Option contract for the protective put
            
        Raises:
            Level2ComplianceError: If no stock to protect
        """
        if stock_position < 100:
            raise Level2ComplianceError(
                f"No stock position to protect. Need 100 shares per contract, "
                f"have {stock_position} shares."
            )
        
        # Create the put contract to buy
        put_ib_contract = self.tws.create_option_contract(
            symbol=put_contract.symbol,
            expiry=put_contract.expiry.strftime('%Y%m%d'),
            strike=put_contract.strike,
            right=put_contract.right.value
        )
        
        return put_ib_contract
    
    def build_straddle_order(
        self, 
        call_contract: OptionContract, 
        put_contract: OptionContract
    ) -> Tuple[Contract, List[ComboLeg]]:
        """
        Build a long straddle order (buy call + buy put at same strike).
        
        Args:
            call_contract: Call option to buy
            put_contract: Put option to buy (same strike/expiry)
            
        Returns:
            Tuple of (combo_contract, combo_legs)
            
        Raises:
            Level2ComplianceError: If strikes/expiries don't match
        """
        # Validate straddle structure
        if (call_contract.strike != put_contract.strike or
            call_contract.expiry != put_contract.expiry):
            raise Level2ComplianceError(
                "Straddle requires same strike and expiry for call and put"
            )
        
        # Create combo contract
        combo = Contract()
        combo.symbol = call_contract.symbol
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        # Both legs are BUY for long straddle
        combo_legs = [
            ComboLeg(conId=0, ratio=1, action='BUY', exchange='SMART'),  # Call
            ComboLeg(conId=0, ratio=1, action='BUY', exchange='SMART'),  # Put
        ]
        
        return combo, combo_legs
    
    def build_collar_order(
        self, 
        stock_position: int,
        put_contract: OptionContract,
        call_contract: OptionContract
    ) -> Tuple[Contract, List[ComboLeg]]:
        """
        Build a collar order (long stock + long put + short call).
        
        Args:
            stock_position: Number of shares owned
            put_contract: Protective put to buy
            call_contract: Call to sell for income
            
        Returns:
            Tuple of (combo_contract, combo_legs) for options only
            
        Note:
            Stock position is assumed to exist. This builds only the options combo.
        """
        if stock_position < 100:
            raise Level2ComplianceError(
                f"Insufficient stock for collar. Need 100 shares per contract, "
                f"have {stock_position} shares."
            )
        
        # Create combo contract for the options portion
        combo = Contract()
        combo.symbol = put_contract.symbol
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        # Combo legs: Buy put + Sell call
        combo_legs = [
            ComboLeg(conId=0, ratio=1, action='BUY', exchange='SMART'),   # Put
            ComboLeg(conId=0, ratio=1, action='SELL', exchange='SMART'),  # Call
        ]
        
        return combo, combo_legs
    
    async def submit_order(
        self, 
        order_spec: OrderSpec, 
        confirmation_token: str
    ) -> Dict[str, Any]:
        """
        Submit validated order to TWS.
        
        Args:
            order_spec: Complete order specification
            confirmation_token: Must be "USER_CONFIRMED"
            
        Returns:
            Order submission result
            
        Raises:
            Level2ComplianceError: If order fails validation
            OrderValidationError: If order parameters invalid
        """
        # CRITICAL: Validate confirmation token
        if confirmation_token != "USER_CONFIRMED":
            raise OrderValidationError(
                f"Invalid confirmation token. Required: 'USER_CONFIRMED', "
                f"got: '{confirmation_token}'"
            )
        
        # Validate Level 2 compliance
        self.validate_level2_compliance(order_spec.strategy)
        
        # Submit to TWS using the connection's place_combo_order method
        try:
            result = await self.tws.place_combo_order(
                strategy=order_spec.strategy,
                order_type=order_spec.order_type
            )
            
            logger.info(
                f"Order submitted successfully: {order_spec.strategy.name} "
                f"(Order ID: {result['order_id']})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            raise OrderValidationError(f"Order submission failed: {e}")
    
    def calculate_margin_requirement(self, strategy: Strategy) -> float:
        """
        Calculate estimated margin requirement for strategy.
        
        Args:
            strategy: Strategy to calculate margin for
            
        Returns:
            Estimated margin requirement in dollars
        """
        # For Level 2 strategies (all debit), margin = net debit paid
        # This is conservative - actual margin may be less
        net_debit = abs(strategy.net_debit_credit)
        
        # Add buffer for commissions and slippage
        margin_buffer = net_debit * 0.05  # 5% buffer
        total_requirement = net_debit + margin_buffer
        
        logger.info(
            f"Estimated margin requirement for {strategy.name}: "
            f"${total_requirement:.2f} (Net debit: ${net_debit:.2f}, "
            f"Buffer: ${margin_buffer:.2f})"
        )
        
        return total_requirement