"""
Strategies module for options trading.
IMPORTANT: Only Level 2 compliant strategies are exported.

Credit spreads and other Level 3+ strategies are NOT included.
"""

from .base import BaseStrategy, StrategyValidationError
from .level2_strategies import (
    # Single options (Level 2)
    SingleOption,
    
    # Debit spreads (Level 2)
    BullCallSpread,
    BearPutSpread,
    
    # Volatility strategies (Level 2)
    LongStraddle,
    LongStrangle,
    
    # Covered strategies (Level 2 with stock)
    CoveredCall,
    ProtectivePut,
    Collar,
    
    # Complex strategies (Level 2)
    LongIronCondor,
    
    # Validation
    Level2StrategyError,
    validate_level2_strategy,
    
    # Convenience functions
    create_bull_call_spread,
    create_bear_put_spread,
    create_long_straddle,
    create_covered_call
)

# NOTE: These strategies require Level 3+ and are NOT available:
# - BullPutSpread (credit spread)
# - BearCallSpread (credit spread)
# - CashSecuredPut
# - CalendarSpread
# - DiagonalSpread
# - Butterfly
# - ShortStraddle (Level 4)
# - ShortStrangle (Level 4)

__all__ = [
    # Base
    'BaseStrategy',
    'StrategyValidationError',
    
    # Level 2 strategies
    'SingleOption',
    'BullCallSpread',
    'BearPutSpread',
    'LongStraddle',
    'LongStrangle',
    'CoveredCall',
    'ProtectivePut',
    'Collar',
    'LongIronCondor',
    
    # Validation
    'Level2StrategyError',
    'validate_level2_strategy',
    
    # Helpers
    'create_bull_call_spread',
    'create_bear_put_spread',
    'create_long_straddle',
    'create_covered_call'
]