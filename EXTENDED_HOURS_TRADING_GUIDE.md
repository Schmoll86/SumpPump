# Extended Hours Trading Implementation Guide

## Overview

SumpPump now has **comprehensive extended hours trading support** following IBKR best practices. The system supports pre-market, after-hours, and overnight trading sessions with proper safety controls.

## New MCP Tools (37 Total)

### Extended Hours Tools

1. **`trade_place_extended_order`** - Place orders with extended hours support
2. **`trade_get_extended_schedule`** - Get current session and schedule
3. **`trade_modify_for_extended`** - Modify existing orders for extended hours

## Trading Sessions

### Schedule (Eastern Time)

| Session | Start | End | Requirements |
|---------|-------|-----|-------------|
| **Pre-Market** | 4:00 AM | 9:30 AM | Standard permissions |
| **Regular** | 9:30 AM | 4:00 PM | Standard permissions |
| **After-Hours** | 4:00 PM | 8:00 PM | Standard permissions |
| **Overnight** | 8:00 PM | 3:50 AM | Special permission required |

## IBKR Best Practices Implemented

### 1. Order Type Restrictions
- **Extended Hours**: Limit orders only (market orders converted)
- **Regular Hours**: All order types allowed
- **Reason**: Limited liquidity in extended hours

### 2. Size Limits
- **Extended Hours**: Max 500 shares per order (configurable)
- **Regular Hours**: No special limits
- **Reason**: Manage risk in thin markets

### 3. Time In Force Options
```python
TimeInForce:
  DAY - Day order (expires at session end)
  GTC - Good Till Cancelled
  IOC - Immediate or Cancel
  GTD - Good Till Date/Time
  OPG - At the Opening
```

### 4. Venue Routing
- **Regular Hours**: SMART routing
- **Extended Hours**: ISLAND (NASDAQ) or specific exchange
- **Overnight**: IBEOS or OVERNIGHT venue (if enabled)

## Usage Examples

### Check Current Session
```python
# Get trading schedule and current session
schedule = await trade_get_extended_schedule()

# Returns:
{
  "current_session": "after_hours",
  "current_time": "2025-08-07T18:30:00",
  "sessions": {
    "pre_market": {"start": "04:00", "end": "09:30", "active": false},
    "regular": {"start": "09:30", "end": "16:00", "active": false},
    "after_hours": {"start": "16:00", "end": "20:00", "active": true},
    "overnight": {"start": "20:00", "end": "03:50", "active": false}
  },
  "recommendation": "Extended hours - use limit orders, expect wider spreads"
}
```

### Place After-Hours Order
```python
# Place limit order for after-hours trading
result = await trade_place_extended_order(
    symbol="AAPL",
    action="BUY",
    quantity=100,
    order_type="LMT",
    limit_price=185.50,
    time_in_force="GTC",  # Good till cancelled
    outside_rth=True,      # Enable extended hours
    confirm_token="USER_CONFIRMED"
)

# Returns:
{
  "status": "success",
  "order_id": 12345,
  "session": "after_hours",
  "warnings": [
    "Order placed during after_hours session",
    "Extended hours trading involves additional risks",
    "Liquidity may be limited",
    "Spreads may be wider than regular hours"
  ]
}
```

### Place GTD Order (Good Till Date)
```python
# Order valid until specific date/time
result = await trade_place_extended_order(
    symbol="TSLA",
    action="SELL",
    quantity=50,
    order_type="LMT",
    limit_price=245.00,
    time_in_force="GTD",
    good_till_date="20250810 20:00:00",  # Valid till Friday 8PM
    outside_rth=True,
    confirm_token="USER_CONFIRMED"
)
```

### Modify Existing Order for Extended Hours
```python
# Enable extended hours on existing order
result = await trade_modify_for_extended(
    order_id=12345,
    enable_extended=True,
    new_time_in_force="GTC",  # Change to GTC
    confirm_token="USER_CONFIRMED"
)
```

## Safety Features

### Automatic Validations
1. **Session Check** - Validates current trading session
2. **Order Type** - Enforces limit orders in extended hours
3. **Size Limits** - Restricts large orders in thin markets
4. **Time Restrictions** - No orders after 11 PM by default

### Risk Warnings
- Wider bid-ask spreads
- Lower liquidity
- Higher volatility
- Price gaps between sessions

## Configuration

### ExtendedHoursConfig Options
```python
config = ExtendedHoursConfig(
    allow_pre_market=True,      # Enable pre-market trading
    allow_after_hours=True,     # Enable after-hours trading
    allow_overnight=False,      # Overnight requires permission
    limit_order_only=True,      # Force limit orders
    max_order_size_extended=500,  # Max shares in extended hours
    no_orders_after=time(23, 0),  # No orders after 11 PM
    no_orders_before=time(4, 0)   # No orders before 4 AM
)
```

## Important Notes

### Market Orders in Extended Hours
- **Automatically converted** to limit orders at bid/ask
- Protects against extreme price movements
- Can override with `limit_order_only=False` (not recommended)

### Overnight Trading
- Requires special IBKR permission
- Different venues: IBEOS or OVERNIGHT
- Very limited liquidity
- Disabled by default

### Order Routing
- **Regular Hours**: SMART routing for best execution
- **Extended Hours**: Direct to exchange (ISLAND/NASDAQ)
- **Overnight**: Special overnight venues

## Troubleshooting

### Common Issues

**"Market orders not allowed"**
- Use limit orders in extended hours
- System will auto-convert if configured

**"Overnight trading not enabled"**
- Requires special IBKR permission
- Contact IBKR to enable

**"Order size exceeds limit"**
- Reduce order size for extended hours
- Default max: 500 shares

## Best Practices

1. **Always use limit orders** in extended hours
2. **Start small** - test with smaller positions
3. **Monitor spreads** - can be significantly wider
4. **Use GTC orders** for multi-day positions
5. **Check session status** before placing orders
6. **Set wider limits** to account for spreads

## API Compatibility

Fully compatible with:
- `ib_async` library
- IBKR TWS API v9.72+
- TWS version 1023+

## Summary

The extended hours trading implementation provides:
- ✅ Full pre-market and after-hours support
- ✅ IBKR best practices enforcement
- ✅ Automatic safety controls
- ✅ Session-aware order routing
- ✅ Time-in-force flexibility
- ✅ Risk warnings and validations

This gives you professional-grade extended hours trading capabilities with built-in safety features to protect against common pitfalls.