"""
IBKR Level 2 Compliant Strategies Module.
Only includes strategies allowed with Level 2 permissions.

ALLOWED (Included):
- Long options (calls/puts)
- Debit spreads (bull call, bear put)
- Long straddles/strangles
- Covered calls/protective puts (require stock position)
- Collars

NOT ALLOWED (Excluded):
- Credit spreads (bull put, bear call) - Need Level 3
- Cash-secured puts - Need Level 3
- Calendar/diagonal spreads - Need Level 3
- Butterflies - Need Level 3
- Short straddles/strangles - Need Level 4
"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from src.modules.strategies.base import BaseStrategy
from src.models import (
    OptionLeg, OptionContract, StrategyType, OrderAction, 
    OptionRight, Strategy
)


class Level2StrategyError(Exception):
    """Raised when attempting to create Level 3+ strategies."""
    pass


class SingleOption(BaseStrategy):
    """
    Single option position (long only for Level 2).
    Can be long call or long put.
    """
    
    def __init__(self, option_leg: OptionLeg):
        """
        Initialize single option position.
        
        Args:
            option_leg: Single option leg (must be BUY for Level 2)
        """
        if option_leg.action != OrderAction.BUY:
            raise Level2StrategyError(
                "Level 2 only allows LONG options. Cannot sell naked options."
            )
        
        if option_leg.contract.right == OptionRight.CALL:
            name = "Long Call"
            strategy_type = StrategyType.LONG_CALL
        else:
            name = "Long Put"
            strategy_type = StrategyType.LONG_PUT
        
        super().__init__(name, strategy_type, [option_leg])
        self.strike = option_leg.contract.strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at given underlying price."""
        option_value = self._option_value_at_expiry(self.legs[0].contract, underlying_price)
        premium_paid = abs(await self.calculate_net_debit_credit())
        return (option_value * 100) - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Calculate maximum profit (unlimited for long options)."""
        if self.legs[0].contract.right == OptionRight.CALL:
            return float('inf')  # Unlimited upside for long calls
        else:
            # Max profit for long put = strike - premium
            premium = abs(await self.calculate_net_debit_credit())
            return (self.strike * 100) - premium
    
    async def calculate_max_loss(self) -> float:
        """Calculate maximum loss (premium paid)."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Calculate breakeven points."""
        premium_per_share = abs(await self.calculate_net_debit_credit()) / 100
        
        if self.legs[0].contract.right == OptionRight.CALL:
            # Breakeven for long call = strike + premium
            return [self.strike + premium_per_share]
        else:
            # Breakeven for long put = strike - premium
            return [self.strike - premium_per_share]


class BullCallSpread(BaseStrategy):
    """
    Bull Call Spread (DEBIT spread - Level 2 allowed).
    Buy lower strike call, sell higher strike call.
    """
    
    def __init__(self, long_call: OptionLeg, short_call: OptionLeg):
        """
        Initialize Bull Call Spread.
        
        Args:
            long_call: Long call leg (lower strike)
            short_call: Short call leg (higher strike)
        """
        # Validate this is a debit spread
        if long_call.contract.strike >= short_call.contract.strike:
            raise ValueError("Long call strike must be lower than short call strike")
        
        # Check net debit
        net_cost = long_call.cost + short_call.cost
        if net_cost >= 0:  # Cost is negative for debits in our model
            raise Level2StrategyError(
                "Bull call spread must be a DEBIT spread for Level 2. "
                "Net premium must be paid upfront."
            )
        
        super().__init__(
            "Bull Call Spread (Debit)",
            StrategyType.BULL_CALL_SPREAD,
            [long_call, short_call]
        )
        
        self.long_strike = long_call.contract.strike
        self.short_strike = short_call.contract.strike
        self.strike_width = self.short_strike - self.long_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Long call value
        long_value = max(0, underlying_price - self.long_strike)
        # Short call value (negative because we sold it)
        short_value = -max(0, underlying_price - self.short_strike)
        # Total value at expiration
        total_value = (long_value + short_value) * 100
        # Subtract net premium paid
        premium_paid = abs(await self.calculate_net_debit_credit())
        return total_value - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Strike width - Net debit."""
        return (self.strike_width * 100) - abs(await self.calculate_net_debit_credit())
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Net debit paid."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Breakeven = Long strike + Net debit."""
        return [self.long_strike + (abs(await self.calculate_net_debit_credit()) / 100)]


class BearPutSpread(BaseStrategy):
    """
    Bear Put Spread (DEBIT spread - Level 2 allowed).
    Buy higher strike put, sell lower strike put.
    """
    
    def __init__(self, long_put: OptionLeg, short_put: OptionLeg):
        """
        Initialize Bear Put Spread.
        
        Args:
            long_put: Long put leg (higher strike)
            short_put: Short put leg (lower strike)
        """
        # Validate this is a debit spread
        if long_put.contract.strike <= short_put.contract.strike:
            raise ValueError("Long put strike must be higher than short put strike")
        
        # Check net debit
        net_cost = long_put.cost + short_put.cost
        if net_cost >= 0:  # Cost is negative for debits
            raise Level2StrategyError(
                "Bear put spread must be a DEBIT spread for Level 2. "
                "Net premium must be paid upfront."
            )
        
        super().__init__(
            "Bear Put Spread (Debit)",
            StrategyType.BEAR_PUT_SPREAD,
            [long_put, short_put]
        )
        
        self.long_strike = long_put.contract.strike
        self.short_strike = short_put.contract.strike
        self.strike_width = self.long_strike - self.short_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Long put value
        long_value = max(0, self.long_strike - underlying_price)
        # Short put value (negative because we sold it)
        short_value = -max(0, self.short_strike - underlying_price)
        # Total value at expiration
        total_value = (long_value + short_value) * 100
        # Subtract net premium paid
        premium_paid = abs(await self.calculate_net_debit_credit())
        return total_value - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Strike width - Net debit."""
        return (self.strike_width * 100) - abs(await self.calculate_net_debit_credit())
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Net debit paid."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Breakeven = Long strike - Net debit."""
        return [self.long_strike - (abs(await self.calculate_net_debit_credit()) / 100)]


class LongStraddle(BaseStrategy):
    """
    Long Straddle (Level 2 allowed).
    Buy call and put at same strike.
    Expecting large move in either direction.
    """
    
    def __init__(self, call_leg: OptionLeg, put_leg: OptionLeg):
        """
        Initialize Long Straddle.
        
        Args:
            call_leg: Long call leg
            put_leg: Long put leg
        """
        # Validate both are buys
        if call_leg.action != OrderAction.BUY or put_leg.action != OrderAction.BUY:
            raise Level2StrategyError("Long straddle requires buying both options")
        
        # Validate same strike
        if call_leg.contract.strike != put_leg.contract.strike:
            raise ValueError("Straddle requires same strike for both legs")
        
        super().__init__(
            "Long Straddle",
            StrategyType.LONG_STRADDLE,
            [call_leg, put_leg]
        )
        
        self.strike = call_leg.contract.strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Call value
        call_value = max(0, underlying_price - self.strike)
        # Put value
        put_value = max(0, self.strike - underlying_price)
        # Total value at expiration
        total_value = (call_value + put_value) * 100
        # Subtract net premium paid
        premium_paid = abs(await self.calculate_net_debit_credit())
        return total_value - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Unlimited."""
        return float('inf')
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Total premium paid."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Two breakevens: Strike ± Total premium."""
        premium_per_share = abs(await self.calculate_net_debit_credit()) / 100
        return [
            self.strike - premium_per_share,  # Lower breakeven
            self.strike + premium_per_share   # Upper breakeven
        ]


class LongStrangle(BaseStrategy):
    """
    Long Strangle (Level 2 allowed).
    Buy OTM call and OTM put.
    Cheaper than straddle, expecting large move.
    """
    
    def __init__(self, call_leg: OptionLeg, put_leg: OptionLeg):
        """
        Initialize Long Strangle.
        
        Args:
            call_leg: Long call leg (higher strike)
            put_leg: Long put leg (lower strike)
        """
        # Validate both are buys
        if call_leg.action != OrderAction.BUY or put_leg.action != OrderAction.BUY:
            raise Level2StrategyError("Long strangle requires buying both options")
        
        # Validate strike relationship
        if call_leg.contract.strike <= put_leg.contract.strike:
            raise ValueError("Call strike must be higher than put strike for strangle")
        
        super().__init__(
            "Long Strangle",
            StrategyType.LONG_STRANGLE,
            [call_leg, put_leg]
        )
        
        self.call_strike = call_leg.contract.strike
        self.put_strike = put_leg.contract.strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Call value
        call_value = max(0, underlying_price - self.call_strike)
        # Put value
        put_value = max(0, self.put_strike - underlying_price)
        # Total value at expiration
        total_value = (call_value + put_value) * 100
        # Subtract net premium paid
        premium_paid = abs(await self.calculate_net_debit_credit())
        return total_value - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Unlimited."""
        return float('inf')
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Total premium paid."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Two breakevens: Put strike - premium, Call strike + premium."""
        premium_per_share = abs(await self.calculate_net_debit_credit()) / 100
        return [
            self.put_strike - premium_per_share,   # Lower breakeven
            self.call_strike + premium_per_share   # Upper breakeven
        ]


class CoveredCall(BaseStrategy):
    """
    Covered Call (Level 2 allowed with stock ownership).
    Long stock + Short call.
    Income generation strategy.
    """
    
    def __init__(self, stock_shares: int, call_leg: OptionLeg):
        """
        Initialize Covered Call.
        
        Args:
            stock_shares: Number of shares owned (must be 100 per contract)
            call_leg: Short call leg
        """
        if call_leg.action != OrderAction.SELL:
            raise ValueError("Covered call requires selling the call")
        
        if stock_shares < call_leg.quantity * 100:
            raise Level2StrategyError(
                f"Need {call_leg.quantity * 100} shares to cover {call_leg.quantity} calls"
            )
        
        super().__init__(
            "Covered Call",
            StrategyType.COVERED_CALL,
            [call_leg]
        )
        
        self.stock_shares = stock_shares
        self.strike = call_leg.contract.strike
        self.premium_received = abs(call_leg.cost)  # Positive for credit
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Stock P&L (assumed bought at current underlying price)
        stock_price = self.legs[0].contract.underlying_price
        stock_pnl = (underlying_price - stock_price) * self.stock_shares
        
        # Call P&L (short call)
        call_value = -max(0, underlying_price - self.strike) * 100 * self.legs[0].quantity
        
        # Total P&L = Stock gain/loss + Call premium received + Call assignment cost
        return stock_pnl + call_value + self.premium_received
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Strike - Stock price + Premium (if assigned)."""
        # Assuming current stock price is underlying_price
        stock_price = self.legs[0].contract.underlying_price
        return ((self.strike - stock_price) * 100) + self.premium_received
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Stock price - Premium (if stock goes to 0)."""
        stock_price = self.legs[0].contract.underlying_price
        return -((stock_price * 100) - self.premium_received)
    
    async def get_breakeven_points(self) -> List[float]:
        """Breakeven = Stock price - Premium received."""
        stock_price = self.legs[0].contract.underlying_price
        return [stock_price - (self.premium_received / 100)]


class ProtectivePut(BaseStrategy):
    """
    Protective Put (Level 2 allowed with stock ownership).
    Long stock + Long put.
    Downside protection strategy.
    """
    
    def __init__(self, stock_shares: int, put_leg: OptionLeg):
        """
        Initialize Protective Put.
        
        Args:
            stock_shares: Number of shares owned
            put_leg: Long put leg
        """
        if put_leg.action != OrderAction.BUY:
            raise ValueError("Protective put requires buying the put")
        
        if stock_shares < put_leg.quantity * 100:
            raise ValueError(
                f"Need {put_leg.quantity * 100} shares for {put_leg.quantity} puts"
            )
        
        super().__init__(
            "Protective Put",
            StrategyType.PROTECTIVE_PUT,
            [put_leg]
        )
        
        self.stock_shares = stock_shares
        self.strike = put_leg.contract.strike
        self.premium_paid = abs(put_leg.cost)
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Stock P&L (assumed bought at current underlying price)
        stock_price = self.legs[0].contract.underlying_price
        stock_pnl = (underlying_price - stock_price) * self.stock_shares
        
        # Put P&L (long put)
        put_value = max(0, self.strike - underlying_price) * 100 * self.legs[0].quantity
        
        # Total P&L = Stock gain/loss + Put value - Put premium paid
        return stock_pnl + put_value - self.premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Unlimited (stock can go up infinitely)."""
        return float('inf')
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Stock price - Strike + Premium paid."""
        stock_price = self.legs[0].contract.underlying_price
        return -(((stock_price - self.strike) * 100) + self.premium_paid)
    
    async def get_breakeven_points(self) -> List[float]:
        """Breakeven = Stock price + Premium paid."""
        stock_price = self.legs[0].contract.underlying_price
        return [stock_price + (self.premium_paid / 100)]


class Collar(BaseStrategy):
    """
    Collar (Level 2 allowed with stock ownership).
    Long stock + Long put + Short call.
    Protected income strategy.
    """
    
    def __init__(self, stock_shares: int, put_leg: OptionLeg, call_leg: OptionLeg):
        """
        Initialize Collar.
        
        Args:
            stock_shares: Number of shares owned
            put_leg: Long put leg (protective)
            call_leg: Short call leg (income)
        """
        if put_leg.action != OrderAction.BUY:
            raise ValueError("Collar requires buying the put")
        
        if call_leg.action != OrderAction.SELL:
            raise ValueError("Collar requires selling the call")
        
        if stock_shares < max(put_leg.quantity, call_leg.quantity) * 100:
            raise Level2StrategyError("Need sufficient shares to cover the collar")
        
        super().__init__(
            "Collar",
            StrategyType.COLLAR,
            [put_leg, call_leg]
        )
        
        self.stock_shares = stock_shares
        self.put_strike = put_leg.contract.strike
        self.call_strike = call_leg.contract.strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Stock P&L (assumed bought at current underlying price)
        stock_price = self.legs[0].contract.underlying_price
        stock_pnl = (underlying_price - stock_price) * self.stock_shares
        
        # Put P&L (long put)
        put_value = max(0, self.put_strike - underlying_price) * 100 * self.legs[0].quantity
        
        # Call P&L (short call)
        call_value = -max(0, underlying_price - self.call_strike) * 100 * self.legs[1].quantity
        
        # Net option cost
        net_option_cost = await self.calculate_net_debit_credit()
        
        # Total P&L
        return stock_pnl + put_value + call_value - net_option_cost
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Call strike - Stock price + Net credit/debit."""
        stock_price = self.legs[0].contract.underlying_price
        net_option_cost = await self.calculate_net_debit_credit()
        return ((self.call_strike - stock_price) * 100) - net_option_cost
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Stock price - Put strike + Net debit."""
        stock_price = self.legs[0].contract.underlying_price
        net_option_cost_abs = abs(await self.calculate_net_debit_credit())
        net_option_cost = net_option_cost_abs if await self.calculate_net_debit_credit() < 0 else 0
        return -(((stock_price - self.put_strike) * 100) + net_option_cost)
    
    async def get_breakeven_points(self) -> List[float]:
        """Breakeven = Stock price + Net debit (or - Net credit)."""
        stock_price = self.legs[0].contract.underlying_price
        adjustment = (await self.calculate_net_debit_credit()) / 100
        return [stock_price - adjustment]


class LongIronCondor(BaseStrategy):
    """
    Long Iron Condor (DEBIT version - Level 2 allowed).
    Buy OTM put, Sell closer OTM put, Sell closer OTM call, Buy OTM call.
    Must result in net DEBIT for Level 2.
    """
    
    def __init__(
        self,
        long_put: OptionLeg,
        short_put: OptionLeg,
        short_call: OptionLeg,
        long_call: OptionLeg
    ):
        """
        Initialize Long Iron Condor.
        
        Args:
            long_put: Long put (lowest strike)
            short_put: Short put (higher than long put)
            short_call: Short call (higher than short put)
            long_call: Long call (highest strike)
        """
        # Validate strike order
        strikes = [
            long_put.contract.strike,
            short_put.contract.strike,
            short_call.contract.strike,
            long_call.contract.strike
        ]
        if strikes != sorted(strikes):
            raise ValueError("Strikes must be in ascending order for iron condor")
        
        # Calculate net cost
        legs = [long_put, short_put, short_call, long_call]
        net_cost = sum(leg.cost for leg in legs)
        
        # CRITICAL: Must be net debit for Level 2
        if net_cost >= 0:  # Cost is negative for debits
            raise Level2StrategyError(
                "Iron condor must be LONG (net debit) for Level 2. "
                "Short iron condor (credit) requires Level 3."
            )
        
        super().__init__(
            "Long Iron Condor (Debit)",
            StrategyType.LONG_IRON_CONDOR,
            legs
        )
        
        self.put_spread_width = short_put.contract.strike - long_put.contract.strike
        self.call_spread_width = long_call.contract.strike - short_call.contract.strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at expiration."""
        # Long put value
        long_put_value = max(0, self.legs[0].contract.strike - underlying_price)
        # Short put value (negative because we sold it)
        short_put_value = -max(0, self.legs[1].contract.strike - underlying_price)
        # Short call value (negative because we sold it)
        short_call_value = -max(0, underlying_price - self.legs[2].contract.strike)
        # Long call value
        long_call_value = max(0, underlying_price - self.legs[3].contract.strike)
        
        # Total value at expiration
        total_value = (long_put_value + short_put_value + short_call_value + long_call_value) * 100
        
        # Subtract net premium paid
        premium_paid = abs(await self.calculate_net_debit_credit())
        return total_value - premium_paid
    
    async def calculate_max_profit(self) -> float:
        """Max profit = Spread width - Net debit."""
        max_spread_width = max(self.put_spread_width, self.call_spread_width)
        return (max_spread_width * 100) - abs(await self.calculate_net_debit_credit())
    
    async def calculate_max_loss(self) -> float:
        """Max loss = Net debit paid."""
        return -abs(await self.calculate_net_debit_credit())
    
    async def get_breakeven_points(self) -> List[float]:
        """Two breakevens based on the debit paid."""
        debit_per_share = abs(await self.calculate_net_debit_credit()) / 100
        return [
            self.legs[1].contract.strike - debit_per_share,  # Lower breakeven
            self.legs[2].contract.strike + debit_per_share   # Upper breakeven
        ]


# Strategy validation helper
def validate_level2_strategy(strategy: Strategy) -> bool:
    """
    Validate that a strategy is Level 2 compliant.
    
    Args:
        strategy: Strategy to validate
        
    Returns:
        True if Level 2 compliant
        
    Raises:
        Level2StrategyError: If strategy requires Level 3+
    """
    # Check strategy type
    forbidden_types = [
        # These would be in StrategyType if we supported them:
        # StrategyType.BULL_PUT_SPREAD,  # Credit spread - Level 3
        # StrategyType.BEAR_CALL_SPREAD,  # Credit spread - Level 3
        # StrategyType.CASH_SECURED_PUT,  # Level 3
        # StrategyType.CALENDAR_SPREAD,    # Level 3
        # StrategyType.DIAGONAL_SPREAD,    # Level 3
        # StrategyType.BUTTERFLY,          # Level 3
        # StrategyType.SHORT_STRADDLE,     # Level 4
        # StrategyType.SHORT_STRANGLE,     # Level 4
    ]
    
    # Check for net credit (not allowed for Level 2)
    if strategy.net_debit_credit > 0:  # Positive means credit received
        raise Level2StrategyError(
            f"Strategy '{strategy.name}' receives net credit. "
            "Level 2 only allows debit strategies where you pay premium upfront."
        )
    
    # Check for naked short options
    for leg in strategy.legs:
        if leg.action == OrderAction.SELL:
            # Short options are only allowed if covered
            if strategy.type not in [
                StrategyType.COVERED_CALL,
                StrategyType.COLLAR,
                StrategyType.BULL_CALL_SPREAD,
                StrategyType.BEAR_PUT_SPREAD,
                StrategyType.LONG_IRON_CONDOR
            ]:
                raise Level2StrategyError(
                    f"Strategy '{strategy.name}' contains naked short options. "
                    "Level 2 requires coverage for all short positions."
                )
    
    return True


# Convenience functions for creating Level 2 strategies
async def create_bull_call_spread(
    long_call_contract: OptionContract,
    short_call_contract: OptionContract,
    quantity: int = 1
) -> BullCallSpread:
    """Create a bull call spread (debit)."""
    long_leg = OptionLeg(long_call_contract, OrderAction.BUY, quantity)
    short_leg = OptionLeg(short_call_contract, OrderAction.SELL, quantity)
    return BullCallSpread(long_leg, short_leg)


async def create_bear_put_spread(
    long_put_contract: OptionContract,
    short_put_contract: OptionContract,
    quantity: int = 1
) -> BearPutSpread:
    """Create a bear put spread (debit)."""
    long_leg = OptionLeg(long_put_contract, OrderAction.BUY, quantity)
    short_leg = OptionLeg(short_put_contract, OrderAction.SELL, quantity)
    return BearPutSpread(long_leg, short_leg)


async def create_long_straddle(
    call_contract: OptionContract,
    put_contract: OptionContract,
    quantity: int = 1
) -> LongStraddle:
    """Create a long straddle."""
    call_leg = OptionLeg(call_contract, OrderAction.BUY, quantity)
    put_leg = OptionLeg(put_contract, OrderAction.BUY, quantity)
    return LongStraddle(call_leg, put_leg)


async def create_covered_call(
    stock_shares: int,
    call_contract: OptionContract,
    contracts_to_sell: int = 1
) -> CoveredCall:
    """Create a covered call position."""
    if stock_shares < contracts_to_sell * 100:
        raise Level2StrategyError(
            f"Need {contracts_to_sell * 100} shares to sell {contracts_to_sell} calls"
        )
    call_leg = OptionLeg(call_contract, OrderAction.SELL, contracts_to_sell)
    return CoveredCall(stock_shares, call_leg)