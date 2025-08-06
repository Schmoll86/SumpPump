# 💬 Sample Trading Session with SumpPump

## Session Start
```
You: [Paste TRADING_START.txt content]

Claude: I'm ready to assist with your IBKR options trading. I have access to real-time market data and can help you analyze and execute Level 2 options strategies. 

I'll always:
- Show you max loss before any trade
- Require your explicit confirmation 
- Prompt for stop losses after execution
- Alert you to any risks or upcoming events

What symbol would you like to analyze, or would you like me to scan for opportunities?
```

## Example 1: Analyzing a Specific Stock
```
You: I'm bullish on NVDA for the next 30 days. Show me good strategies.

Claude: Let me analyze NVDA options for you.

[Using get_options_chain("NVDA")]

NVDA current price: $895.50
IV Rank: 68th percentile (elevated but not extreme)
Upcoming events: Earnings in 42 days (outside your timeframe ✓)

Based on the options chain analysis, here are three bullish strategies:

1. **Bull Call Spread** (Recommended)
   - Buy: Feb 21 $900 Call @ $38.50
   - Sell: Feb 21 $920 Call @ $28.20
   - Net Debit: $10.30 ($1,030 per spread)
   - Max Profit: $9.70 ($970) at $920+
   - Max Loss: $10.30 ($1,030)
   - Breakeven: $910.30
   - Probability of Profit: 42%

2. **Long Call** (More aggressive)
   - Buy: Feb 21 $900 Call @ $38.50
   - Max Profit: Unlimited
   - Max Loss: $38.50 ($3,850)
   - Breakeven: $938.50

Would you like me to calculate a different strike or expiration?
```

## Example 2: Executing a Trade
```
You: I like the bull call spread. Let's do 2 contracts.

Claude: Let me prepare your order for review:

**ORDER CONFIRMATION REQUIRED**
Strategy: NVDA Bull Call Spread
Quantity: 2 spreads
- BUY 2x NVDA Feb 21 $900 Call
- SELL 2x NVDA Feb 21 $920 Call

Total Cost: $2,060 (net debit)
Max Profit: $1,940 (at $920+)
**MAX LOSS: $2,060** ⚠️
Breakeven: $910.30

Current bid/ask spreads:
- $900C: $38.20/$38.50 (tight ✓)
- $920C: $28.00/$28.20 (tight ✓)

To execute this trade, please confirm by typing: USER_CONFIRMED

Or type "cancel" to abort.
```

```
You: USER_CONFIRMED

Claude: [Using execute_trade() with confirmation token]

Trade executed successfully:
- Order ID: #1234567
- Fill prices: 
  * Bought $900C @ $38.45 (avg)
  * Sold $920C @ $28.15 (avg)
- Net debit: $10.30 per spread
- Total cost: $2,060

**STOP LOSS RECOMMENDED**
Would you like to set a stop loss? Suggested levels:
- 50% loss: Stop if spread value drops to $5.15
- 30% loss: Stop if spread value drops to $7.21

Which level would you prefer?
```

## Example 3: Market Scanning
```
You: Find me high probability credit spread opportunities

Claude: [Using market scanners and get_options_chain() for multiple symbols]

I've scanned for high IV rank stocks suitable for credit spreads:

**Top 3 Opportunities:**

1. **TSLA** - IV Rank: 82%
   Put Credit Spread: 250/245
   - Credit: $1.85
   - Max Loss: $3.15
   - Probability of Profit: 68%
   - News: No events for 3 weeks ✓

2. **AMD** - IV Rank: 75%
   Put Credit Spread: 135/130
   - Credit: $1.45
   - Max Loss: $3.55
   - Probability of Profit: 71%
   - News: Product launch Tuesday ⚠️

3. **META** - IV Rank: 71%
   Put Credit Spread: 480/475
   - Credit: $1.65
   - Max Loss: $3.35
   - Probability of Profit: 69%
   - News: Clear calendar ✓

Would you like detailed analysis on any of these?
```

## Example 4: Risk Alert
```
You: What about a call spread on AAPL?

Claude: ⚠️ **CAUTION** - Let me check AAPL:

[Using get_options_chain("AAPL") and news check]

AAPL current price: $195.50

**RISK ALERT**: 
- Earnings announcement in 3 days! 
- IV is extremely elevated (85th percentile)
- Options are pricing in a ±8% move

If you want to trade through earnings, consider:
- Smaller position size
- Wider spreads to accommodate the expected move
- Or wait until after earnings for cleaner setup

Would you like to see post-earnings expiration dates instead?
```

## Example 5: Position Management
```
You: I have that NVDA spread from earlier. Market dropped. What should I do?

Claude: Let me analyze your position:

[Using get_market_data() and calculate_strategy()]

Your NVDA Feb 21 900/920 Bull Call Spread:
- Entry: $10.30
- Current value: $7.20
- Current loss: -$3.10 (-30%)
- Days to expiration: 28
- NVDA price: $878 (down from $895.50)

**Analysis:**
- You still have 28 days for recovery
- Support level at $875 holding
- No concerning news

**Options:**
1. **Hold** - You have time, max loss is defined
2. **Adjust** - Roll down to 880/900 spread
3. **Cut losses** - Exit at 30% loss per your rules

The probabilities have shifted to 35% chance of profit, but significant time remains.

What's your preference?
```

## Session End
```
You: Thanks for today. Close the session.

Claude: Trading session summary:
- Executed: 1 trade (NVDA bull call spread)
- Max risk taken: $2,060
- Stop loss: Set at $7.21
- Remember to monitor: NVDA support at $875

Stay safe and trade well! 

Note: I won't remember this session next time, so please track your positions in TWS or your trading journal.
```

---

This is how your trading assistant should interact - professional, safety-focused, and data-driven!