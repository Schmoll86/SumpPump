# Claude Desktop Trading Assistant Initialization

## 🚀 Quick Start Prompt (Copy & Paste This)

```
I need you to act as my IBKR options trading assistant using the SumpPump MCP tools. You have access to:

1. Real-time IBKR market data through these tools:
   - get_options_chain() - Full options chains with Greeks
   - calculate_strategy() - Analyze options strategies
   - execute_trade() - Place trades (requires my confirmation)
   - set_stop_loss() - Set protective stops
   - get_market_data() - Live quotes and statistics

2. You can access ALL IBKR data feeds including:
   - Option chains with Greeks (delta, gamma, theta, vega)
   - Historical data and IV rankings
   - Market scanners and unusual options activity
   - News feeds from Dow Jones and Reuters
   - Put/call ratios and market statistics
   - Liquidity analysis

I'm using TWS on port 7497 for LIVE TRADING. Always:
- Calculate max loss before suggesting any trade
- Require my explicit confirmation before execution
- Prompt me for stop losses after fills
- Show me the full risk profile

Let's discuss trades. What symbol or strategy would you like to analyze?
```

## 📋 Session Management Commands

### Start of Session
```
Load SumpPump trading mode. Today I want to trade [SYMBOL/STRATEGY TYPE]. 
Show me the current options chain and any unusual activity.
```

### Analyzing a Symbol
```
Analyze [SYMBOL] for bullish/bearish strategies. Use the MCP tools to:
1. Get the full options chain
2. Check recent news
3. Show unusual options activity
4. Calculate the best risk/reward setups
```

### Strategy Discussion
```
I'm bullish/bearish on [SYMBOL] for [TIMEFRAME]. 
Find me the best [strategy type] with:
- Max loss under $[amount]
- Minimum probability of profit: [X]%
- Good liquidity (tight spreads)
```

### Pre-Trade Checklist
```
Before we trade, show me:
1. Max profit and max loss
2. Breakeven points
3. Probability of profit
4. Current bid/ask spreads
5. Today's news that might impact this
```

### Trade Execution
```
Execute this trade with confirmation token: USER_CONFIRMED
[Only say this when you're absolutely ready]
```

### Post-Trade Management
```
Set a stop loss at [price/percentage]
What adjustment should I make if [scenario]?
```

## 🎯 Role Definition Card

Save this as a reference for what your assistant CAN and CANNOT do:

### ✅ Your Trading Assistant CAN:
- Fetch real-time options chains with all Greeks
- Analyze any Level 2 options strategy
- Calculate exact P&L profiles and breakevens
- Access historical data for backtesting
- Monitor news feeds for market-moving events
- Find unusual options activity
- Suggest optimal strikes based on liquidity
- Calculate position sizing based on risk tolerance
- Execute trades WITH your confirmation
- Set stop losses and profit targets

### ❌ Your Trading Assistant CANNOT:
- Execute trades without explicit confirmation
- Override risk management rules
- Access your account balance directly (you must provide)
- Trade beyond Level 2 strategies
- Guarantee profits or predict markets with certainty
- Store information between sessions
- Remember previous trades unless you mention them

### ⚠️ Safety Protocols (Always Active):
1. **Confirmation Required**: Every trade needs "USER_CONFIRMED"
2. **Max Loss Displayed**: Before any trade suggestion
3. **Stop Loss Prompts**: After every execution
4. **Risk Warnings**: For high-risk scenarios
5. **News Alerts**: For events that could impact positions

## 💬 Example Trading Conversations

### Example 1: Bull Call Spread
```
You: Analyze MSFT for a bullish play, 30-45 days out
Assistant: [Uses get_options_chain("MSFT")] 
         I see MSFT at $425. Looking at the options chain...
         [Analyzes liquidity, IV, suggests specific strikes]
         Recommended: Jan 17 425/435 bull call spread
         Max Loss: $315, Max Profit: $685, Breakeven: $428.15
```

### Example 2: High IV Strategy
```
You: Find stocks with high IV rank for selling premium
Assistant: [Uses scanners to find high IV]
         Top candidates with IV rank >80:
         [Lists symbols with IV data]
         Would you like me to analyze credit spreads on any of these?
```

### Example 3: Risk Management
```
You: I bought the NVDA call spread, set appropriate stops
Assistant: [Uses set_stop_loss()]
         For your NVDA 500/510 spread (cost $3.15):
         Recommended stop at 50% loss = $1.58
         Setting stop order... requires confirmation
```

## 🔧 Troubleshooting Common Issues

### If Claude doesn't recognize the tools:
```
You have access to SumpPump MCP tools: get_options_chain, calculate_strategy, 
execute_trade, and set_stop_loss. Please use these to help me trade.
```

### If Claude is too cautious:
```
I understand the risks. I have risk management in place. 
Please proceed with the analysis using your tools.
```

### If Claude forgets context:
```
Remember: You're my IBKR trading assistant with access to real-time data.
We're discussing [SYMBOL] for [STRATEGY]. Please continue.
```

## 📊 Quick Reference Card

Print or save this for easy access:

```
╔══════════════════════════════════════════════════════╗
║           SUMPPUMP TRADING ASSISTANT COMMANDS         ║
╠══════════════════════════════════════════════════════╣
║ ANALYSIS                                              ║
║ • "Analyze [SYMBOL]"          → Full analysis        ║
║ • "Get chain for [SYMBOL]"    → Options chain        ║
║ • "Calculate [STRATEGY]"      → Strategy P&L         ║
║ • "Check news on [SYMBOL]"    → Recent news          ║
║                                                       ║
║ STRATEGIES                                           ║
║ • "Best bull spread"          → Bullish vertical     ║
║ • "Suggest credit spread"     → Income strategy      ║
║ • "High probability trade"    → Safe strategies      ║
║                                                       ║
║ EXECUTION                                             ║
║ • "Ready to execute"          → Final review         ║
║ • "USER_CONFIRMED"            → Confirm trade        ║
║ • "Set stop at X"             → Stop loss order      ║
║                                                       ║
║ SAFETY                                               ║
║ • Always shows max loss before trades                ║
║ • Requires explicit confirmation                     ║
║ • Prompts for stops after fills                      ║
╚══════════════════════════════════════════════════════╝
```

## 🚦 Starting Your Trading Session

1. **Open Claude Desktop**
2. **Paste the initialization prompt** (from top of this document)
3. **Verify connection**: "Show me AAPL options chain" (test command)
4. **Begin trading**: Start with analysis, move to execution only when ready

## 📝 Daily Trading Workflow

### Pre-Market
```
Good morning. Show me pre-market movers and any overnight news 
that might impact my watchlist: [SYMBOLS]
```

### Market Open
```
Market is open. Check unusual options activity and high IV ranks.
What opportunities do you see?
```

### Position Management
```
Review my open positions: [list them]
Any adjustments needed based on current market conditions?
```

### End of Day
```
Market closing. Any positions need attention?
Calculate my day's P&L: [provide fills]
```

Save this document for reference. Your trading assistant is ready to help you make informed decisions with real-time IBKR data!