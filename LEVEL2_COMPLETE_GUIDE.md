# IBKR Level 2 Options Permissions - Complete Documentation

## Summary

With IBKR Level 2 options trading permissions, you have access to **17 specific strategies** that all require upfront payment (debit). You CANNOT do credit strategies, naked shorts, or time spreads.

## Files Updated for Level 2 Compliance

1. **IBKR_LEVEL2_PERMISSIONS.md** - Complete strategy reference
2. **LEVEL2_STRATEGY_CARD.txt** - Quick reference card (print this!)
3. **CLAUDE.md** - Updated architecture docs
4. **README.md** - Updated supported strategies
5. **TRADING_START.txt** - Updated Claude initialization prompt
6. **src/models.py** - Updated StrategyType enum

## Complete List of Available Strategies (Level 2)

### Basic (from Level 1)
1. **Covered Call** - Own 100 shares, sell call
2. **Covered Basket Call** - Multiple stocks, sell calls
3. **Buy-Write** - Buy stock + sell call simultaneously

### Single Options (Level 2)
4. **Long Call** - Bullish bet
5. **Long Put** - Bearish bet or hedge

### Protective Strategies (Level 2)
6. **Covered Put** - Short stock + short put
7. **Protective Call** - Short stock + long call
8. **Protective Put** - Long stock + long put

### Volatility Plays (Level 2)
9. **Long Straddle** - Buy ATM call + put
10. **Long Strangle** - Buy OTM call + put

### Debit Spreads (Level 2)
11. **Bull Call Spread** - Buy lower call, sell higher call
12. **Bear Put Spread** - Buy higher put, sell lower put

### Complex Strategies (Level 2)
13. **Long Iron Condor** - Bull put spread + bear call spread (debit version)
14. **Long Box Spread** - Synthetic loan
15. **Collar** - Stock + long put + short call
16. **Short Collar** - Short stock + short put + long call
17. **Conversion** - Arbitrage strategy

## Strategies You CANNOT Do

### Need Level 3
- Short (naked) puts
- Credit spreads (bear call, bull put)
- Calendar spreads
- Diagonal spreads
- All butterfly variations
- Short iron condor (credit version)

### Need Level 4
- Short (naked) calls
- Short straddles
- Short strangles

## Trading Assistant Configuration

When Claude Desktop acts as your trading assistant, it will:

1. **Only suggest Level 2 compatible strategies**
2. **Calculate debit requirements** for all trades
3. **Warn if you ask for credit strategies** (not available)
4. **Focus on covered calls** for income generation
5. **Use debit spreads** for directional plays

## Example Conversations

### Valid Request (Level 2)
```
You: "I want a bullish strategy on AAPL"
Assistant: "I can help with a bull call spread (debit) or long calls..."
```

### Invalid Request (Needs Level 3+)
```
You: "Set up a bull put spread for income"
Assistant: "Bull put spreads are credit strategies requiring Level 3. 
           With Level 2, consider a bull call spread instead..."
```

## Risk Management with Level 2

Since all strategies require upfront payment:
- **Max risk** = Premium paid (for single options)
- **Max risk** = Net debit (for spreads)
- **No margin calls** on debit strategies
- **Full payment required** at entry

## Best Practices for Level 2 Trading

1. **Master debit spreads first** - Your bread and butter
2. **Use covered calls** on existing stock for income
3. **Buy protective puts** for portfolio insurance
4. **Trade liquid options** - Tight bid/ask spreads
5. **Start small** - One contract at a time

## Quick Decision Tree

```
Want Income?
├─ Own stock? → Covered Calls
└─ No stock? → Can't do cash-secured puts (need L3)

Bullish?
├─ Aggressive → Long Calls
├─ Moderate → Bull Call Spread
└─ Own stock → Collar or Hold

Bearish?
├─ Aggressive → Long Puts
└─ Moderate → Bear Put Spread
└─ Short stock → Protective Call

Expecting Big Move?
├─ Any direction → Long Straddle
└─ Cheaper → Long Strangle

Range Bound?
└─ Long Iron Condor (debit only)
```

## Capital Requirements

- **Long Options**: Full premium upfront
- **Debit Spreads**: Net debit upfront
- **Covered Calls**: Must own 100 shares per contract
- **No margin benefit** for any Level 2 strategy

## Getting to Level 3

If you need credit strategies, you'll need:
- Age 21+
- Higher net worth/liquid assets
- More trading experience
- Pass options knowledge assessment
- Maintain $2,000+ account equity

## Safety Notes

- All Level 2 strategies have **defined risk**
- Maximum loss is known at entry
- No unlimited risk scenarios
- Perfect for learning options safely

---

**Remember**: When using SumpPump, Claude will only suggest and execute strategies compatible with Level 2 permissions. If you request something requiring Level 3+, it will explain the limitation and suggest alternatives.