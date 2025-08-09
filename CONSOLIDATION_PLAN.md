# SumpPump MCP Tools - Safe Consolidation Plan v1.0

## Executive Summary
This plan consolidates 43 MCP tools down to 25-30 tools while maintaining 100% backward compatibility. Each consolidation includes rollback procedures and safety checks.

## Current Tool Inventory (43 Tools)

### Market Data Tools (12)
1. `trade_get_quote` - Single stock/ETF quotes
2. `trade_get_options_chain` - Options chain with Greeks
3. `trade_get_price_history` - Historical OHLCV data
4. `trade_get_positions` - Current portfolio positions
5. `trade_get_open_orders` - Pending orders
6. `trade_get_account_summary` - Account balances
7. `trade_get_news` - News feed
8. `trade_get_watchlist_quotes` - Multiple symbol quotes
9. `trade_get_market_depth` - Level 2 order book
10. `trade_get_depth_analytics` - Price impact analysis
11. `trade_scan_market` - Market scanner
12. `trade_check_market_data` - Verify market data feed

### Strategy & Risk Tools (8)
1. `trade_calculate_strategy` - Analyze options strategies
2. `trade_check_margin_risk` - Margin call risk assessment
3. `trade_get_volatility_analysis` - IV rank and volatility
4. `trade_get_index_quote` - Index quotes (SPX, NDX, VIX)
5. `trade_get_index_options` - Index options chains
6. `trade_get_vix_term_structure` - VIX term structure
7. `trade_analyze_opportunity` - Comprehensive trade analysis
8. `trade_get_session_status` - Trading session state

### Execution Tools (11)
1. `trade_execute` - Execute trades with confirmation
2. `trade_execute_with_verification` - Execute with enhanced verification
3. `trade_close_position` - Close existing positions
4. `trade_set_stop_loss` - Set protective stops
5. `trade_modify_order` - Modify pending orders
6. `trade_cancel_order` - Cancel pending orders
7. `trade_create_conditional_order` - Create conditional/bracket orders
8. `trade_buy_to_close` - Buy to close options positions
9. `trade_direct_close` - Direct position closing
10. `trade_emergency_close` - Emergency close all positions
11. `trade_set_price_alert` - Set price alerts

### Extended Hours Tools (3)
1. `trade_place_extended_order` - Place extended hours orders
2. `trade_get_extended_schedule` - Get extended trading schedule
3. `trade_modify_for_extended` - Modify order for extended hours

### Advanced Tools (5)
1. `trade_roll_option` - Roll options forward
2. `trade_get_crypto_quote` - Crypto quotes
3. `trade_analyze_crypto` - Crypto analysis
4. `trade_get_fx_quote` - Forex quotes
5. `trade_analyze_fx_pair` - FX analysis

### New Portfolio Tools (4)
1. `trade_get_portfolio_summary` - Comprehensive portfolio summary with Greeks
2. `trade_get_history` - Historical trades and P&L
3. `trade_adjust_position` - Adjust existing positions
4. `trade_analyze_greeks` - Analyze portfolio Greeks

---

## SAFE Consolidation Groups

### Group 1: Quote Tools (LOW RISK)
**Current Tools (5):**
- `trade_get_quote`
- `trade_get_watchlist_quotes`
- `trade_get_index_quote`
- `trade_get_crypto_quote`
- `trade_get_fx_quote`

**New Consolidated Tool:**
```python
@mcp.tool(name="trade_get_market_data")
async def get_market_data(
    symbols: Union[str, List[str]],  # Single or multiple symbols
    asset_type: str = 'STK',  # 'STK', 'IND', 'CRYPTO', 'FX', 'OPT'
    include_depth: bool = False,  # Include Level 2 data
    include_analytics: bool = False  # Include analytics
) -> Dict[str, Any]:
    """
    Universal market data tool for all asset types.
    Backward compatible with all quote tools.
    """
```

**Backward Compatibility:**
```python
# Alias definitions
@mcp.tool(name="trade_get_quote")
async def get_quote(symbol: str, asset_type: str = 'STK'):
    return await get_market_data(symbols=symbol, asset_type=asset_type)

@mcp.tool(name="trade_get_watchlist_quotes")
async def get_watchlist_quotes(symbols: List[str]):
    return await get_market_data(symbols=symbols, asset_type='STK')

# Continue for all legacy tools...
```

**Risk Assessment:** LOW
- Simple parameter mapping
- No logic changes
- Easy to test
- Instant rollback via aliases

---

### Group 2: Position Close Tools (MEDIUM RISK)
**Current Tools (4):**
- `trade_close_position`
- `trade_buy_to_close`
- `trade_direct_close`
- `trade_emergency_close`

**New Consolidated Tool:**
```python
@mcp.tool(name="trade_close")
async def close_positions(
    symbol: str,
    close_type: str = 'standard',  # 'standard', 'buy_to_close', 'direct', 'emergency'
    position_type: Optional[str] = None,  # 'call', 'put', 'spread', 'stock'
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    right: Optional[str] = None,
    quantity: Optional[int] = None,
    order_type: str = 'MKT',
    limit_price: Optional[float] = None,
    confirm_token: Optional[str] = None,
    second_confirmation: Optional[str] = None  # For emergency only
) -> Dict[str, Any]:
    """
    Universal position closing tool.
    Routes to appropriate implementation based on close_type.
    """
```

**Backward Compatibility:**
```python
@mcp.tool(name="trade_close_position")
async def close_position(symbol, position_type, quantity, order_type='MKT', 
                         limit_price=None, position_id=None, confirm_token=None):
    return await close_positions(
        symbol=symbol,
        close_type='standard',
        position_type=position_type,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        confirm_token=confirm_token
    )

@mcp.tool(name="trade_buy_to_close")
async def buy_to_close_option(symbol, strike, expiry, right, quantity, 
                               order_type='MKT', limit_price=None, 
                               trigger_price=None, trigger_condition='immediate',
                               confirm_token=None):
    # Map parameters appropriately
    return await close_positions(
        symbol=symbol,
        close_type='buy_to_close',
        strike=strike,
        expiry=expiry,
        right=right,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        confirm_token=confirm_token
    )
```

**Risk Assessment:** MEDIUM
- Complex parameter mapping
- Different execution paths
- Requires comprehensive testing
- Rollback via feature flags

---

### Group 3: Execution Tools (HIGH RISK - SKIP)
**Current Tools:**
- `trade_execute`
- `trade_execute_with_verification`

**Recommendation:** DO NOT CONSOLIDATE
- These are critical paths with different safety validations
- Each has unique session state management
- Risk of breaking production trades
- Keep as separate tools

---

### Group 4: Portfolio Analysis Tools (LOW RISK)
**Current Tools (3):**
- `trade_get_positions`
- `trade_get_account_summary`
- `trade_get_portfolio_summary`

**New Consolidated Tool:**
```python
@mcp.tool(name="trade_get_portfolio")
async def get_portfolio(
    view: str = 'positions',  # 'positions', 'summary', 'account', 'complete'
    include_greeks: bool = False,
    include_history: bool = False,
    symbol_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Comprehensive portfolio information tool.
    """
```

**Backward Compatibility:**
```python
@mcp.tool(name="trade_get_positions")
async def get_positions():
    result = await get_portfolio(view='positions')
    # Transform to match legacy format
    return result

@mcp.tool(name="trade_get_account_summary")
async def get_account_summary():
    result = await get_portfolio(view='account')
    # Transform to match legacy format
    return result
```

**Risk Assessment:** LOW
- Read-only operations
- No execution risk
- Easy to validate output
- Simple rollback

---

### Group 5: Order Management Tools (MEDIUM RISK)
**Current Tools (3):**
- `trade_modify_order`
- `trade_cancel_order`
- `trade_create_conditional_order`

**New Consolidated Tool:**
```python
@mcp.tool(name="trade_manage_order")
async def manage_order(
    order_id: Optional[int] = None,
    action: str = 'create',  # 'create', 'modify', 'cancel'
    order_type: Optional[str] = None,
    conditions: Optional[List[Dict]] = None,
    modifications: Optional[Dict] = None,
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Universal order management tool.
    """
```

**Risk Assessment:** MEDIUM
- Different action paths
- State management required
- Needs careful testing

---

## Implementation Strategy

### Phase 1: Low-Risk Consolidations (Week 1)
1. **Quote Tools Consolidation**
   - Implement `trade_get_market_data`
   - Create all backward compatibility aliases
   - Test with paper account first
   - Deploy with feature flag

2. **Portfolio Tools Consolidation**
   - Implement `trade_get_portfolio`
   - Create legacy aliases
   - Validate output formats match exactly
   - Deploy with monitoring

### Phase 2: Medium-Risk Consolidations (Week 2-3)
1. **Position Close Tools**
   - Implement with extensive logging
   - Test each close type thoroughly
   - Deploy one close type at a time
   - Monitor for 48 hours before next

2. **Order Management Tools**
   - Implement with state tracking
   - Test all edge cases
   - Deploy with instant rollback capability

### Phase 3: Skip High-Risk (Do Not Implement)
- Keep `trade_execute` and `trade_execute_with_verification` separate
- Keep extended hours tools separate (low usage, high complexity)
- Keep specialized tools (roll, crypto, fx) separate

---

## Testing Checklist

### For Each Consolidation:
- [ ] Unit tests for new consolidated function
- [ ] Unit tests for all backward compatibility aliases
- [ ] Integration tests with TWS paper account
- [ ] Load testing for performance regression
- [ ] A/B testing with feature flags
- [ ] Rollback procedure tested
- [ ] Monitoring dashboards configured
- [ ] Error tracking configured
- [ ] Documentation updated

### Specific Test Cases:
1. **Quote Tools:**
   - Single symbol quote
   - Multiple symbol quotes
   - Index quotes
   - Invalid symbols
   - Market closed scenarios

2. **Close Tools:**
   - Close long call
   - Close short put
   - Close spread
   - Emergency close
   - Partial fills
   - Failed closes

3. **Portfolio Tools:**
   - Empty portfolio
   - Large portfolio (100+ positions)
   - Mixed asset types
   - Greeks calculation
   - P&L accuracy

---

## Rollback Procedures

### Level 1: Feature Flag Rollback (Instant)
```python
# In server.py
if FEATURE_FLAGS.get('use_consolidated_quotes', False):
    # Use new consolidated tool
    result = await get_market_data(...)
else:
    # Use legacy tool
    result = await get_quote(...)
```

### Level 2: Alias Rollback (5 minutes)
```python
# Comment out new implementation
# @mcp.tool(name="trade_get_market_data")
# async def get_market_data(...):
#     ...

# Restore original implementation
@mcp.tool(name="trade_get_quote")
async def get_quote(symbol: str, asset_type: str = 'STK'):
    # Original implementation
```

### Level 3: Git Rollback (10 minutes)
```bash
# Revert to previous version
git revert HEAD
git push origin main

# Restart MCP server
pkill -f "server.py"
/Users/schmoll/Desktop/SumpPump/venv/bin/python src/mcp/server.py
```

---

## Risk Matrix

| Consolidation | Risk Level | Rollback Time | Testing Required | Business Impact |
|--------------|------------|---------------|------------------|-----------------|
| Quote Tools | LOW | Instant | 2 days | Minimal |
| Portfolio Tools | LOW | Instant | 1 day | Minimal |
| Close Tools | MEDIUM | 5 min | 5 days | Moderate |
| Order Management | MEDIUM | 5 min | 5 days | Moderate |
| Execution Tools | HIGH | N/A | N/A | SKIP |
| Extended Hours | HIGH | N/A | N/A | SKIP |

---

## Success Metrics

### Target Outcomes:
- Reduce tool count from 43 to 28-30
- Maintain 100% backward compatibility
- Zero production incidents
- No increase in response time
- Improved code maintainability

### Monitoring:
- Tool usage frequency
- Error rates per tool
- Response times
- User feedback
- Claude interaction patterns

---

## Migration Code Example

### Safe Implementation Pattern:
```python
# src/mcp/consolidated_tools.py

class ConsolidatedTools:
    """Consolidated tool implementations with safety checks."""
    
    @staticmethod
    async def get_market_data(params: Dict) -> Dict:
        """Universal market data with routing."""
        # Validate parameters
        validator = ParameterValidator()
        if not validator.validate_market_data(params):
            return {'error': 'Invalid parameters'}
        
        # Route to appropriate implementation
        asset_type = params.get('asset_type', 'STK')
        
        if asset_type == 'STK':
            return await StockDataProvider.get_data(params)
        elif asset_type == 'IND':
            return await IndexDataProvider.get_data(params)
        elif asset_type == 'CRYPTO':
            return await CryptoDataProvider.get_data(params)
        else:
            return {'error': f'Unsupported asset type: {asset_type}'}

# src/mcp/server.py

# Import consolidated tools
from src.mcp.consolidated_tools import ConsolidatedTools

# Feature flag control
USE_CONSOLIDATED = os.getenv('USE_CONSOLIDATED_TOOLS', 'false').lower() == 'true'

if USE_CONSOLIDATED:
    @mcp.tool(name="trade_get_market_data")
    async def get_market_data(symbols, asset_type='STK', **kwargs):
        return await ConsolidatedTools.get_market_data({
            'symbols': symbols,
            'asset_type': asset_type,
            **kwargs
        })

# Always keep backward compatibility aliases
@mcp.tool(name="trade_get_quote")
async def get_quote(symbol: str, asset_type: str = 'STK'):
    if USE_CONSOLIDATED:
        return await get_market_data(symbols=symbol, asset_type=asset_type)
    else:
        # Original implementation
        return await _original_get_quote(symbol, asset_type)
```

---

## Conclusion

This consolidation plan reduces the MCP tool count by approximately 30% while maintaining complete backward compatibility. The phased approach with feature flags and comprehensive testing ensures zero disruption to production trading.

**Key Principles:**
1. Safety over consolidation
2. Complete backward compatibility
3. Instant rollback capability
4. Comprehensive testing
5. Skip high-risk consolidations

**Expected Timeline:**
- Phase 1: 1 week
- Phase 2: 2 weeks
- Total: 3 weeks with monitoring

**Final Tool Count:** 28-30 tools (from 43)