# Execution Module Context

## Purpose
Handles order execution with mandatory safety controls and confirmation workflows.

## Execution Flow
```
1. Strategy Validation
2. Risk Checks
3. USER CONFIRMATION REQUIRED ← CRITICAL
4. Build Combo Order
5. Submit to TWS
6. Monitor Fill
7. PROMPT FOR STOP LOSS ← CRITICAL
```

## Confirmation System
### Required Token
```python
def execute_trade(strategy, confirm_token):
    if confirm_token != "USER_CONFIRMED":
        return {"error": "Confirmation required"}
    # Only then proceed
```

### Pre-Execution Display
```
Strategy: Bull Call Spread
Symbol: AAPL
Legs: 
  - Buy 170C @ $5.50
  - Sell 175C @ $3.20
Net Debit: $230
MAX LOSS: $230  ← ALWAYS SHOW
Max Profit: $270
Breakeven: $172.30

Confirm? (TOKEN REQUIRED)
```

## Order Types
- **Market Orders**: For liquid options
- **Limit Orders**: Default for combos
- **Adaptive Orders**: IBKR smart routing

## Combo Order Construction
```python
combo = Contract()
combo.secType = 'BAG'
combo.comboLegs = [
    ComboLeg(conId=..., action='BUY', ratio=1),
    ComboLeg(conId=..., action='SELL', ratio=1)
]
```

## Fill Monitoring
- Track partial fills
- Update average price
- Calculate commissions
- Report slippage

## Post-Fill Actions
1. **Log execution details**
2. **PROMPT for stop loss** (mandatory)
3. **Set alerts** for price targets
4. **Update position tracking**

## Error Handling
- Order rejected: Check margin/permissions
- Partial fill: Decide to complete or cancel
- Connection lost: Save state and retry

## Testing
- Mock confirmations in dev
- Test with 1-lot orders first
- Verify stop loss prompts