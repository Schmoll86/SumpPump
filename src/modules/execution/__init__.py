"""
Execution Module - Safe Options Trading with IBKR Level 2 Restrictions

This module handles order execution with mandatory safety controls and confirmation workflows.
All strategies are validated for IBKR Level 2 compliance before execution.

CRITICAL SAFETY FEATURES:
- No credit strategies (Level 3+ required)
- Mandatory confirmation token "USER_CONFIRMED"
- Max loss calculation and display
- Stop loss prompts after every fill
- Level 2 compliance validation

ALLOWED STRATEGIES (Level 2):
- Long options (calls/puts)
- Debit spreads (bull call, bear put)
- Covered calls (with stock)
- Protective puts/calls
- Long straddles/strangles
- Long iron condor (debit version)
- Collar strategies
"""

from .orders import OrderBuilder, Level2ComplianceError
from .confirmation import ConfirmationManager, ConfirmationError

__all__ = [
    'OrderBuilder',
    'ConfirmationManager',
    'Level2ComplianceError',
    'ConfirmationError',
]