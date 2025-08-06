# Risk Management Module Context

## Purpose
Enforces safety controls and risk limits for all trading operations.

## Core Responsibilities
1. **Position Sizing**: Calculate appropriate size based on account
2. **Max Loss Validation**: Ensure losses don't exceed limits
3. **Margin Verification**: Check sufficient buying power
4. **Stop Loss Management**: Prompt and set protective orders

## Critical Safety Rules
### MANDATORY CHECKS
```python
# 1. Confirmation Required
if not confirm_token == "USER_CONFIRMED":
    raise ValueError("Explicit confirmation required")

# 2. Max Loss Display
print(f"MAX LOSS: ${strategy.max_loss:,.2f}")

# 3. Position Size Limit
if position_value > account_value * 0.05:
    raise ValueError("Position too large")
```

## Risk Parameters (Configurable)
- `MAX_POSITION_SIZE_PERCENT`: 5% default
- `DEFAULT_STOP_LOSS_PERCENT`: 10% default
- `MIN_OPTION_VOLUME`: 10 contracts
- `MIN_OPEN_INTEREST`: 50 contracts

## Validation Workflow
1. Check account balance/margin
2. Validate strategy parameters
3. Calculate max risk
4. Require user confirmation
5. Place order with stops

## Stop Loss Logic
- **After Fill**: Always prompt user
- **Suggested Stop**: 10% below entry
- **Order Type**: Stop-limit preferred
- **Trailing Stops**: For profitable positions

## Margin Calculations
- **Cash Account**: Full premium required
- **Margin Account**: Use IBKR requirements
- **Spreads**: Max loss as collateral

## Testing Scenarios
- Insufficient funds
- Position too large
- Missing confirmation
- Invalid strategy parameters