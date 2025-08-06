# Strategies Module Context

## Purpose
Implements all Level 2 options strategies with P&L calculations and analysis.

## Supported Strategies
### Vertical Spreads
- Bull Call Spread
- Bear Put Spread  
- Bull Put Spread (Credit)
- Bear Call Spread (Credit)

### Calendar Spreads
- Calendar Call
- Calendar Put
- Diagonal Spreads

### Multi-Leg
- Iron Condor
- Iron Butterfly
- Straddle/Strangle

## Key Calculations Required
1. **Max Profit**: Maximum possible gain
2. **Max Loss**: Maximum possible loss (CRITICAL for safety)
3. **Breakeven Points**: Price(s) where P&L = 0
4. **Probability of Profit**: Using Black-Scholes
5. **Required Capital**: Margin/cash needed

## Implementation Pattern
```python
class Strategy:
    def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at given price"""
        
    def get_breakeven_points(self) -> List[float]:
        """Find breakeven prices"""
        
    def calculate_probabilities(self) -> Dict[str, float]:
        """Calculate probability metrics"""
```

## Greeks Aggregation
- Sum deltas across legs
- Net gamma exposure
- Theta decay analysis
- Vega sensitivity

## Risk Checks
- Min volume: 10 contracts
- Min open interest: 50
- Bid-ask spread < 10% of mid
- Margin requirements met

## Libraries
- **py_vollib**: Black-Scholes calculations
- **scipy.stats**: Probability distributions
- **numpy**: Numerical operations