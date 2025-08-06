"""
Data models for SumpPump.
Defines structures for options, strategies, and trading data.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from enum import Enum


class OptionRight(Enum):
    """Option type."""
    CALL = "C"
    PUT = "P"


class OrderAction(Enum):
    """Order action type."""
    BUY = "BUY"
    SELL = "SELL"


class StrategyType(Enum):
    """Supported strategy types for IBKR Level 2."""
    # Single Options
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    
    # Debit Spreads (Level 2 Allowed)
    BULL_CALL_SPREAD = "bull_call_spread"  # Debit spread
    BEAR_PUT_SPREAD = "bear_put_spread"    # Debit spread
    
    # Covered Strategies
    COVERED_CALL = "covered_call"
    PROTECTIVE_PUT = "protective_put"
    PROTECTIVE_CALL = "protective_call"
    COLLAR = "collar"
    SHORT_COLLAR = "short_collar"
    
    # Volatility (Level 2 Allowed)
    LONG_STRADDLE = "long_straddle"
    LONG_STRANGLE = "long_strangle"
    LONG_IRON_CONDOR = "long_iron_condor"  # Debit version
    
    # Complex (Level 2 Allowed)
    CONVERSION = "conversion"
    LONG_BOX_SPREAD = "long_box_spread"
    
    # NOT AVAILABLE - Level 3+ Required
    # BEAR_CALL_SPREAD = "bear_call_spread"  # Credit - NEED L3
    # BULL_PUT_SPREAD = "bull_put_spread"    # Credit - NEED L3
    # CASH_SECURED_PUT = "cash_secured_put"  # NEED L3
    # SHORT_PUT = "short_put"                # NEED L3
    # CALENDAR_SPREAD = "calendar_spread"    # NEED L3
    # DIAGONAL_SPREAD = "diagonal_spread"    # NEED L3
    # BUTTERFLY = "butterfly"                # NEED L3
    # SHORT_STRADDLE = "short_straddle"      # NEED L4
    # SHORT_STRANGLE = "short_strangle"      # NEED L4


@dataclass
class Greeks:
    """Option Greeks."""
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: Optional[float] = None


@dataclass
class OptionContract:
    """Represents an option contract."""
    symbol: str
    strike: float
    expiry: datetime
    right: OptionRight
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    iv: float
    greeks: Greeks
    underlying_price: float


@dataclass
class OptionLeg:
    """Single leg of an options strategy."""
    contract: OptionContract
    action: OrderAction
    quantity: int
    
    @property
    def cost(self) -> float:
        """Calculate leg cost/credit."""
        price = self.contract.ask if self.action == OrderAction.BUY else self.contract.bid
        multiplier = -1 if self.action == OrderAction.BUY else 1
        return price * self.quantity * 100 * multiplier


@dataclass
class Strategy:
    """Options strategy with analysis."""
    name: str
    type: StrategyType
    legs: List[OptionLeg]
    max_profit: float
    max_loss: float
    breakeven: List[float]
    current_value: float
    probability_profit: Optional[float] = None
    required_capital: float = 0.0
    
    @property
    def net_debit_credit(self) -> float:
        """Calculate net debit (negative) or credit (positive)."""
        return sum(leg.cost for leg in self.legs)


@dataclass
class ExecutionResult:
    """Result of trade execution."""
    strategy: Strategy
    order_id: str
    status: str
    fill_prices: Dict[str, float]
    commission: float
    timestamp: datetime
    confirmation_token: str


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"
    TRAILING_STOP = "TRAIL"


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING_SUBMIT = "PendingSubmit"
    PENDING_CANCEL = "PendingCancel"
    PRE_SUBMITTED = "PreSubmitted"
    SUBMITTED = "Submitted"
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    INACTIVE = "Inactive"


@dataclass
class PositionDetails:
    """Details about an open position."""
    position_id: str
    symbol: str
    position_type: str  # 'option', 'stock', 'spread'
    quantity: int
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    market_value: float
    option_details: Optional[Dict[str, Any]] = None


@dataclass
class OrderDetails:
    """Details about an order."""
    order_id: int
    symbol: str
    action: str
    quantity: int
    order_type: OrderType
    status: OrderStatus
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_quantity: int = 0
    remaining_quantity: int = 0
    avg_fill_price: Optional[float] = None
    parent_id: Optional[int] = None
    oca_group: Optional[str] = None
