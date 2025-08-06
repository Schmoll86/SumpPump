"""
Vertical spread strategies implementation.
Includes Bull Call Spread, Bear Put Spread, Bull Put Spread (Credit), and Bear Call Spread (Credit).
"""

import asyncio
from typing import List, Optional
from datetime import datetime
from loguru import logger

from .base import BaseStrategy
from src.models import (
    OptionLeg, OptionContract, StrategyType, OrderAction, OptionRight
)


class BullCallSpread(BaseStrategy):
    """
    Bull Call Spread (Debit Spread).
    Buy lower strike call, sell higher strike call.
    Bullish strategy with limited profit and limited loss.
    """
    
    def __init__(self, long_call: OptionLeg, short_call: OptionLeg):
        """
        Initialize Bull Call Spread.
        
        Args:
            long_call: Long call leg (lower strike)
            short_call: Short call leg (higher strike)
        """
        # Validate legs
        if long_call.contract.right != OptionRight.CALL or short_call.contract.right != OptionRight.CALL:
            raise ValueError("Both legs must be calls")
        
        if long_call.action != OrderAction.BUY or short_call.action != OrderAction.SELL:
            raise ValueError("Long call must be BUY, short call must be SELL")
        
        if long_call.contract.strike >= short_call.contract.strike:
            raise ValueError("Long call strike must be lower than short call strike")
        
        if long_call.contract.expiry != short_call.contract.expiry:
            raise ValueError("Both legs must have the same expiration")
        
        legs = [long_call, short_call]
        super().__init__("Bull Call Spread", StrategyType.BULL_CALL_SPREAD, legs)
        
        self.long_strike = long_call.contract.strike
        self.short_strike = short_call.contract.strike
        self.strike_width = self.short_strike - self.long_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """
        Calculate P&L at expiration for given underlying price.
        
        Args:
            underlying_price: Price of underlying asset
            
        Returns:
            P&L value at expiration
        """
        # Long call value
        long_call_value = max(0, underlying_price - self.long_strike)
        
        # Short call value (negative because we sold it)
        short_call_value = -max(0, underlying_price - self.short_strike)
        
        # Total value at expiration
        total_value = (long_call_value + short_call_value) * 100  # $100 per contract
        
        # Subtract net premium paid
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        
        return total_value - net_premium_paid
    
    async def get_breakeven_points(self) -> List[float]:
        """
        Calculate breakeven point.
        For bull call spread: Long Strike + Net Premium Paid
        
        Returns:
            List with single breakeven price
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit()) / 100  # Per share
        breakeven = self.long_strike + net_premium_paid
        
        return [breakeven]
    
    async def calculate_max_profit(self) -> float:
        """
        Calculate maximum profit.
        Max Profit = Strike Width - Net Premium Paid
        
        Returns:
            Maximum profit amount
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        max_profit = (self.strike_width * 100) - net_premium_paid
        
        return max_profit
    
    async def calculate_max_loss(self) -> float:
        """
        Calculate maximum loss.
        Max Loss = Net Premium Paid (when both options expire worthless)
        
        Returns:
            Maximum loss amount (negative value)
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        return -net_premium_paid


class BearPutSpread(BaseStrategy):
    """
    Bear Put Spread (Debit Spread).
    Buy higher strike put, sell lower strike put.
    Bearish strategy with limited profit and limited loss.
    """
    
    def __init__(self, long_put: OptionLeg, short_put: OptionLeg):
        """
        Initialize Bear Put Spread.
        
        Args:
            long_put: Long put leg (higher strike)
            short_put: Short put leg (lower strike)
        """
        # Validate legs
        if long_put.contract.right != OptionRight.PUT or short_put.contract.right != OptionRight.PUT:
            raise ValueError("Both legs must be puts")
        
        if long_put.action != OrderAction.BUY or short_put.action != OrderAction.SELL:
            raise ValueError("Long put must be BUY, short put must be SELL")
        
        if long_put.contract.strike <= short_put.contract.strike:
            raise ValueError("Long put strike must be higher than short put strike")
        
        if long_put.contract.expiry != short_put.contract.expiry:
            raise ValueError("Both legs must have the same expiration")
        
        legs = [long_put, short_put]
        super().__init__("Bear Put Spread", StrategyType.BEAR_PUT_SPREAD, legs)
        
        self.long_strike = long_put.contract.strike
        self.short_strike = short_put.contract.strike
        self.strike_width = self.long_strike - self.short_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """
        Calculate P&L at expiration for given underlying price.
        
        Args:
            underlying_price: Price of underlying asset
            
        Returns:
            P&L value at expiration
        """
        # Long put value
        long_put_value = max(0, self.long_strike - underlying_price)
        
        # Short put value (negative because we sold it)
        short_put_value = -max(0, self.short_strike - underlying_price)
        
        # Total value at expiration
        total_value = (long_put_value + short_put_value) * 100  # $100 per contract
        
        # Subtract net premium paid
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        
        return total_value - net_premium_paid
    
    async def get_breakeven_points(self) -> List[float]:
        """
        Calculate breakeven point.
        For bear put spread: Long Strike - Net Premium Paid
        
        Returns:
            List with single breakeven price
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit()) / 100  # Per share
        breakeven = self.long_strike - net_premium_paid
        
        return [breakeven]
    
    async def calculate_max_profit(self) -> float:
        """
        Calculate maximum profit.
        Max Profit = Strike Width - Net Premium Paid
        
        Returns:
            Maximum profit amount
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        max_profit = (self.strike_width * 100) - net_premium_paid
        
        return max_profit
    
    async def calculate_max_loss(self) -> float:
        """
        Calculate maximum loss.
        Max Loss = Net Premium Paid (when both options expire worthless)
        
        Returns:
            Maximum loss amount (negative value)
        """
        net_premium_paid = abs(await self.calculate_net_debit_credit())
        return -net_premium_paid


class BullPutSpread(BaseStrategy):
    """
    Bull Put Spread (Credit Spread).
    Sell higher strike put, buy lower strike put.
    Bullish strategy with limited profit and limited loss.
    """
    
    def __init__(self, short_put: OptionLeg, long_put: OptionLeg):
        """
        Initialize Bull Put Spread.
        
        Args:
            short_put: Short put leg (higher strike) 
            long_put: Long put leg (lower strike)
        """
        # Validate legs
        if short_put.contract.right != OptionRight.PUT or long_put.contract.right != OptionRight.PUT:
            raise ValueError("Both legs must be puts")
        
        if short_put.action != OrderAction.SELL or long_put.action != OrderAction.BUY:
            raise ValueError("Short put must be SELL, long put must be BUY")
        
        if short_put.contract.strike <= long_put.contract.strike:
            raise ValueError("Short put strike must be higher than long put strike")
        
        if short_put.contract.expiry != long_put.contract.expiry:
            raise ValueError("Both legs must have the same expiration")
        
        legs = [short_put, long_put]
        super().__init__("Bull Put Spread", StrategyType.BULL_PUT_SPREAD, legs)
        
        self.short_strike = short_put.contract.strike
        self.long_strike = long_put.contract.strike
        self.strike_width = self.short_strike - self.long_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """
        Calculate P&L at expiration for given underlying price.
        
        Args:
            underlying_price: Price of underlying asset
            
        Returns:
            P&L value at expiration
        """
        # Short put value (negative because we sold it)
        short_put_value = -max(0, self.short_strike - underlying_price)
        
        # Long put value  
        long_put_value = max(0, self.long_strike - underlying_price)
        
        # Total value at expiration
        total_value = (short_put_value + long_put_value) * 100  # $100 per contract
        
        # Add net premium received
        net_premium_received = await self.calculate_net_debit_credit()
        
        return total_value + net_premium_received
    
    async def get_breakeven_points(self) -> List[float]:
        """
        Calculate breakeven point.
        For bull put spread: Short Strike - Net Premium Received
        
        Returns:
            List with single breakeven price
        """
        net_premium_received = await self.calculate_net_debit_credit() / 100  # Per share
        breakeven = self.short_strike - net_premium_received
        
        return [breakeven]
    
    async def calculate_max_profit(self) -> float:
        """
        Calculate maximum profit.
        Max Profit = Net Premium Received (when both options expire worthless)
        
        Returns:
            Maximum profit amount
        """
        net_premium_received = await self.calculate_net_debit_credit()
        return net_premium_received
    
    async def calculate_max_loss(self) -> float:
        """
        Calculate maximum loss.
        Max Loss = Strike Width - Net Premium Received
        
        Returns:
            Maximum loss amount (negative value)
        """
        net_premium_received = await self.calculate_net_debit_credit()
        max_loss = net_premium_received - (self.strike_width * 100)
        
        return max_loss


class BearCallSpread(BaseStrategy):
    """
    Bear Call Spread (Credit Spread).
    Sell lower strike call, buy higher strike call.
    Bearish strategy with limited profit and limited loss.
    """
    
    def __init__(self, short_call: OptionLeg, long_call: OptionLeg):
        """
        Initialize Bear Call Spread.
        
        Args:
            short_call: Short call leg (lower strike)
            long_call: Long call leg (higher strike)
        """
        # Validate legs
        if short_call.contract.right != OptionRight.CALL or long_call.contract.right != OptionRight.CALL:
            raise ValueError("Both legs must be calls")
        
        if short_call.action != OrderAction.SELL or long_call.action != OrderAction.BUY:
            raise ValueError("Short call must be SELL, long call must be BUY")
        
        if short_call.contract.strike >= long_call.contract.strike:
            raise ValueError("Short call strike must be lower than long call strike")
        
        if short_call.contract.expiry != long_call.contract.expiry:
            raise ValueError("Both legs must have the same expiration")
        
        legs = [short_call, long_call]
        super().__init__("Bear Call Spread", StrategyType.BEAR_CALL_SPREAD, legs)
        
        self.short_strike = short_call.contract.strike
        self.long_strike = long_call.contract.strike
        self.strike_width = self.long_strike - self.short_strike
    
    async def calculate_pnl(self, underlying_price: float) -> float:
        """
        Calculate P&L at expiration for given underlying price.
        
        Args:
            underlying_price: Price of underlying asset
            
        Returns:
            P&L value at expiration
        """
        # Short call value (negative because we sold it)
        short_call_value = -max(0, underlying_price - self.short_strike)
        
        # Long call value
        long_call_value = max(0, underlying_price - self.long_strike)
        
        # Total value at expiration
        total_value = (short_call_value + long_call_value) * 100  # $100 per contract
        
        # Add net premium received
        net_premium_received = await self.calculate_net_debit_credit()
        
        return total_value + net_premium_received
    
    async def get_breakeven_points(self) -> List[float]:
        """
        Calculate breakeven point.
        For bear call spread: Short Strike + Net Premium Received
        
        Returns:
            List with single breakeven price
        """
        net_premium_received = await self.calculate_net_debit_credit() / 100  # Per share
        breakeven = self.short_strike + net_premium_received
        
        return [breakeven]
    
    async def calculate_max_profit(self) -> float:
        """
        Calculate maximum profit.
        Max Profit = Net Premium Received (when both options expire worthless)
        
        Returns:
            Maximum profit amount
        """
        net_premium_received = await self.calculate_net_debit_credit()
        return net_premium_received
    
    async def calculate_max_loss(self) -> float:
        """
        Calculate maximum loss.
        Max Loss = Strike Width - Net Premium Received
        
        Returns:
            Maximum loss amount (negative value)
        """
        net_premium_received = await self.calculate_net_debit_credit()
        max_loss = net_premium_received - (self.strike_width * 100)
        
        return max_loss


# Convenience functions for creating strategies
async def create_bull_call_spread(
    symbol: str,
    long_strike: float,
    short_strike: float,
    expiry: datetime,
    long_call_contract: OptionContract,
    short_call_contract: OptionContract,
    quantity: int = 1
) -> BullCallSpread:
    """
    Create a Bull Call Spread strategy.
    
    Args:
        symbol: Underlying symbol
        long_strike: Strike of long call (lower)
        short_strike: Strike of short call (higher)  
        expiry: Expiration date
        long_call_contract: Long call option contract
        short_call_contract: Short call option contract
        quantity: Number of spreads (default 1)
        
    Returns:
        BullCallSpread strategy object
    """
    long_leg = OptionLeg(
        contract=long_call_contract,
        action=OrderAction.BUY,
        quantity=quantity
    )
    
    short_leg = OptionLeg(
        contract=short_call_contract,
        action=OrderAction.SELL,
        quantity=quantity
    )
    
    return BullCallSpread(long_leg, short_leg)


async def create_bear_put_spread(
    symbol: str,
    long_strike: float,
    short_strike: float,
    expiry: datetime,
    long_put_contract: OptionContract,
    short_put_contract: OptionContract,
    quantity: int = 1
) -> BearPutSpread:
    """
    Create a Bear Put Spread strategy.
    
    Args:
        symbol: Underlying symbol
        long_strike: Strike of long put (higher)
        short_strike: Strike of short put (lower)
        expiry: Expiration date
        long_put_contract: Long put option contract
        short_put_contract: Short put option contract
        quantity: Number of spreads (default 1)
        
    Returns:
        BearPutSpread strategy object
    """
    long_leg = OptionLeg(
        contract=long_put_contract,
        action=OrderAction.BUY,
        quantity=quantity
    )
    
    short_leg = OptionLeg(
        contract=short_put_contract,
        action=OrderAction.SELL,
        quantity=quantity
    )
    
    return BearPutSpread(long_leg, short_leg)


async def create_bull_put_spread(
    symbol: str,
    short_strike: float,
    long_strike: float,
    expiry: datetime,
    short_put_contract: OptionContract,
    long_put_contract: OptionContract,
    quantity: int = 1
) -> BullPutSpread:
    """
    Create a Bull Put Spread (credit spread) strategy.
    
    Args:
        symbol: Underlying symbol
        short_strike: Strike of short put (higher)
        long_strike: Strike of long put (lower)
        expiry: Expiration date
        short_put_contract: Short put option contract
        long_put_contract: Long put option contract
        quantity: Number of spreads (default 1)
        
    Returns:
        BullPutSpread strategy object
    """
    short_leg = OptionLeg(
        contract=short_put_contract,
        action=OrderAction.SELL,
        quantity=quantity
    )
    
    long_leg = OptionLeg(
        contract=long_put_contract,
        action=OrderAction.BUY,
        quantity=quantity
    )
    
    return BullPutSpread(short_leg, long_leg)


async def create_bear_call_spread(
    symbol: str,
    short_strike: float,
    long_strike: float,
    expiry: datetime,
    short_call_contract: OptionContract,
    long_call_contract: OptionContract,
    quantity: int = 1
) -> BearCallSpread:
    """
    Create a Bear Call Spread (credit spread) strategy.
    
    Args:
        symbol: Underlying symbol
        short_strike: Strike of short call (lower)
        long_strike: Strike of long call (higher)
        expiry: Expiration date
        short_call_contract: Short call option contract
        long_call_contract: Long call option contract
        quantity: Number of spreads (default 1)
        
    Returns:
        BearCallSpread strategy object
    """
    short_leg = OptionLeg(
        contract=short_call_contract,
        action=OrderAction.SELL,
        quantity=quantity
    )
    
    long_leg = OptionLeg(
        contract=long_call_contract,
        action=OrderAction.BUY,
        quantity=quantity
    )
    
    return BearCallSpread(short_leg, long_leg)