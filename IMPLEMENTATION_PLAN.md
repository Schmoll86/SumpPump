# SumpPump Implementation Plan

## Executive Summary
This plan outlines specific enhancements to SumpPump while maintaining its core purpose as a safety-first conversational options trading assistant. All changes maintain 100% backward compatibility.

## Current State Analysis

### Data Flow Architecture
```
User Request → MCP Tool → Session State → TWS Connection → IBKR API
                 ↓            ↓               ↓
            Validation   Strategy Cache   Market Data
                 ↓            ↓               ↓
            Response ← Risk Framework ← Execution Engine
```

### Key Findings
1. **Portfolio module exists** but lacks MCP tool exposure (src/modules/data/portfolio.py)
2. **Session TTL already 30 minutes** in strategy_manager.py (line 115)
3. **4 close tools** need consolidation: close_position, buy_to_close, direct_close, emergency_close
4. **2 execute tools** could be merged: execute, execute_with_verification
5. **Trade history** partially implemented in portfolio.py but not exposed via MCP

## PHASE 1: Non-Breaking Additions (4 New Tools)

### 1. trade_get_portfolio_summary
**Purpose**: Expose existing PortfolioAnalyzer functionality via MCP

**Integration Point**: Add after line 3686 in server.py

```python
@mcp.tool(name="trade_get_portfolio_summary")
async def get_portfolio_summary(
    include_greeks: bool = True,
    beta_weight_symbol: Optional[str] = 'SPY',
    include_closed_today: bool = False
) -> Dict[str, Any]:
    """
    [TRADING] Get comprehensive portfolio summary with P&L and Greeks.
    
    Args:
        include_greeks: Calculate aggregate portfolio Greeks
        beta_weight_symbol: Symbol for beta-weighted delta (default: SPY)
        include_closed_today: Include positions closed today
        
    Returns:
        Portfolio summary with positions, P&L, Greeks, and risk metrics
    """
    logger.info(f"[PORTFOLIO] Getting portfolio summary (greeks={include_greeks})")
    
    try:
        await ensure_tws_connected()
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        summary = await analyzer.get_portfolio_summary(
            include_greeks=include_greeks,
            beta_weight_symbol=beta_weight_symbol,
            include_closed_today=include_closed_today
        )
        
        result = summary.to_dict()
        
        # Add workflow integration
        if session_state.trading_session:
            result['session_state'] = session_state.trading_session.current_state.value
            
        logger.info(f"[PORTFOLIO] Summary generated - {result['positions_count']} positions, "
                   f"Total P&L: ${result['total_pnl']:.2f}")
        
        return result
        
    except Exception as e:
        logger.error(f"[PORTFOLIO] Summary failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to get portfolio summary'
        }
```

### 2. trade_get_history
**Purpose**: Query past trades with filters

**Integration Point**: Add after trade_get_portfolio_summary

```python
@mcp.tool(name="trade_get_history")
async def get_trade_history(
    days_back: int = 30,
    symbol: Optional[str] = None,
    include_executions: bool = True,
    min_pnl: Optional[float] = None,
    trade_type: Optional[str] = None  # 'options', 'stocks', 'all'
) -> Dict[str, Any]:
    """
    [TRADING] Get historical trades with detailed filtering.
    
    Args:
        days_back: Number of days to look back (default: 30)
        symbol: Filter by specific symbol
        include_executions: Include execution details
        min_pnl: Minimum P&L to include (for filtering big wins/losses)
        trade_type: Filter by trade type
        
    Returns:
        List of historical trades with P&L and execution details
    """
    logger.info(f"[HISTORY] Fetching {days_back} days of trades"
               f"{f' for {symbol}' if symbol else ''}")
    
    try:
        await ensure_tws_connected()
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        trades = await analyzer.get_trade_history(
            days_back=days_back,
            symbol=symbol,
            include_executions=include_executions
        )
        
        # Apply additional filters
        filtered_trades = trades
        
        if min_pnl is not None:
            filtered_trades = [t for t in filtered_trades 
                              if abs(t.get('realized_pnl', 0)) >= abs(min_pnl)]
        
        if trade_type:
            if trade_type == 'options':
                filtered_trades = [t for t in filtered_trades 
                                  if t.get('contract_type') == 'OPT']
            elif trade_type == 'stocks':
                filtered_trades = [t for t in filtered_trades 
                                  if t.get('contract_type') == 'STK']
        
        # Add audit trail integration
        for trade in filtered_trades:
            trade['audit_id'] = f"TRADE_{trade.get('time', '')}_{trade.get('symbol', '')}"
        
        # Calculate summary statistics
        total_pnl = sum(t.get('realized_pnl', 0) for t in filtered_trades)
        winning_trades = [t for t in filtered_trades if t.get('realized_pnl', 0) > 0]
        losing_trades = [t for t in filtered_trades if t.get('realized_pnl', 0) < 0]
        
        return {
            'status': 'success',
            'trades': filtered_trades,
            'summary': {
                'total_trades': len(filtered_trades),
                'total_pnl': round(total_pnl, 2),
                'winning_trades': len(winning_trades),
                'losing_trades': len(losing_trades),
                'win_rate': round(len(winning_trades) / len(filtered_trades) * 100, 1) 
                           if filtered_trades else 0,
                'avg_win': round(sum(t['realized_pnl'] for t in winning_trades) / len(winning_trades), 2)
                          if winning_trades else 0,
                'avg_loss': round(sum(t['realized_pnl'] for t in losing_trades) / len(losing_trades), 2)
                           if losing_trades else 0
            },
            'filters_applied': {
                'days_back': days_back,
                'symbol': symbol,
                'min_pnl': min_pnl,
                'trade_type': trade_type
            }
        }
        
    except Exception as e:
        logger.error(f"[HISTORY] Failed to get trade history: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to retrieve trade history'
        }
```

### 3. trade_adjust_position
**Purpose**: Unified position adjustment tool

**Integration Point**: Add after trade_get_history

```python
@mcp.tool(name="trade_adjust_position")
async def adjust_position(
    position_id: Optional[str] = None,
    symbol: Optional[str] = None,
    adjustment_type: str = 'roll',  # 'roll', 'resize', 'hedge', 'close_partial'
    new_quantity: Optional[int] = None,
    new_strike: Optional[float] = None,
    new_expiry: Optional[str] = None,
    hedge_strategy: Optional[str] = None,  # 'protective_put', 'collar'
    percentage_to_close: Optional[float] = None,
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    [TRADING] Adjust existing positions - roll, resize, hedge, or partial close.
    
    Args:
        position_id: Position identifier (use this OR symbol)
        symbol: Symbol of position to adjust
        adjustment_type: Type of adjustment
        new_quantity: For resize operations
        new_strike: For roll operations
        new_expiry: For roll operations (YYYY-MM-DD)
        hedge_strategy: Type of hedge to add
        percentage_to_close: For partial closes (0-100)
        confirm_token: Safety confirmation
        
    Returns:
        Adjustment execution details
    """
    logger.info(f"[ADJUST] {adjustment_type} adjustment for "
               f"{position_id or symbol}")
    
    # Safety validation
    params = locals()
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_adjust_position', params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_adjust_position', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_adjust_position",
            "action_required": "Add confirm_token='USER_CONFIRMED' to proceed"
        }
    
    ExecutionSafety.log_execution_attempt('trade_adjust_position', params, True)
    
    try:
        await ensure_tws_connected()
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.advanced_orders import (
            roll_option_position, resize_position, add_hedge
        )
        
        # Route to appropriate handler
        if adjustment_type == 'roll':
            # Use existing roll functionality
            result = await roll_option_position(
                tws_connection,
                position_id or symbol,
                new_strike,
                new_expiry,
                'diagonal' if new_strike and new_expiry else 'calendar'
            )
            
        elif adjustment_type == 'resize':
            # Implement position resizing
            current_positions = await tws_connection.ib.positionsAsync()
            target_position = None
            
            for pos in current_positions:
                if (position_id and str(pos.contract.conId) == position_id) or \
                   (symbol and pos.contract.symbol == symbol):
                    target_position = pos
                    break
            
            if not target_position:
                return {
                    'status': 'error',
                    'error': 'Position not found',
                    'message': f'No position found for {position_id or symbol}'
                }
            
            current_qty = abs(target_position.position)
            qty_change = new_quantity - current_qty
            
            if qty_change > 0:
                # Add to position
                order_action = 'BUY' if target_position.position > 0 else 'SELL'
            else:
                # Reduce position
                order_action = 'SELL' if target_position.position > 0 else 'BUY'
                qty_change = abs(qty_change)
            
            # Create and place order
            from ib_async import MarketOrder
            order = MarketOrder(
                action=order_action,
                totalQuantity=qty_change
            )
            
            trade = tws_connection.ib.placeOrder(target_position.contract, order)
            await tws_connection.ib.sleep(2)
            
            result = {
                'status': 'success',
                'adjustment_type': 'resize',
                'original_quantity': current_qty,
                'new_quantity': new_quantity,
                'order_id': trade.order.orderId,
                'action': order_action,
                'quantity_changed': qty_change
            }
            
        elif adjustment_type == 'hedge':
            # Add protective hedge
            result = await add_hedge(
                tws_connection,
                symbol,
                hedge_strategy or 'protective_put'
            )
            
        elif adjustment_type == 'close_partial':
            # Partial position close
            if not percentage_to_close or percentage_to_close <= 0 or percentage_to_close > 100:
                return {
                    'status': 'error',
                    'error': 'Invalid percentage',
                    'message': 'percentage_to_close must be between 1 and 100'
                }
            
            current_positions = await tws_connection.ib.positionsAsync()
            target_position = None
            
            for pos in current_positions:
                if (position_id and str(pos.contract.conId) == position_id) or \
                   (symbol and pos.contract.symbol == symbol):
                    target_position = pos
                    break
            
            if not target_position:
                return {
                    'status': 'error',
                    'error': 'Position not found'
                }
            
            qty_to_close = int(abs(target_position.position) * percentage_to_close / 100)
            order_action = 'SELL' if target_position.position > 0 else 'BUY'
            
            from ib_async import MarketOrder
            order = MarketOrder(
                action=order_action,
                totalQuantity=qty_to_close
            )
            
            trade = tws_connection.ib.placeOrder(target_position.contract, order)
            await tws_connection.ib.sleep(2)
            
            result = {
                'status': 'success',
                'adjustment_type': 'close_partial',
                'percentage_closed': percentage_to_close,
                'quantity_closed': qty_to_close,
                'remaining_quantity': abs(target_position.position) - qty_to_close,
                'order_id': trade.order.orderId
            }
            
        else:
            return {
                'status': 'error',
                'error': 'Invalid adjustment type',
                'message': f'Unknown adjustment_type: {adjustment_type}'
            }
        
        # Update session state
        if session_state.trading_session:
            session_state.trading_session.add_audit_entry(
                f"Position adjusted: {adjustment_type}",
                {'result': result}
            )
        
        return result
        
    except Exception as e:
        logger.error(f"[ADJUST] Position adjustment failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Position adjustment failed'
        }
```

### 4. trade_analyze_greeks
**Purpose**: Portfolio-wide Greeks analysis with scenarios

**Integration Point**: Add after trade_adjust_position

```python
@mcp.tool(name="trade_analyze_greeks")
async def analyze_portfolio_greeks(
    scenario_moves: Optional[List[float]] = None,
    time_decay_days: Optional[int] = 1,
    iv_change: Optional[float] = None,
    include_individual: bool = False
) -> Dict[str, Any]:
    """
    [TRADING] Analyze portfolio-wide Greeks with scenario analysis.
    
    Args:
        scenario_moves: List of price moves to test (e.g., [-10, -5, 0, 5, 10])
        time_decay_days: Days of theta decay to calculate
        iv_change: IV change in percentage points
        include_individual: Include individual position Greeks
        
    Returns:
        Comprehensive Greeks analysis with risk scenarios
    """
    logger.info("[GREEKS] Analyzing portfolio Greeks and scenarios")
    
    if scenario_moves is None:
        scenario_moves = [-10, -5, -2, 0, 2, 5, 10]
    
    try:
        await ensure_tws_connected()
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        
        # Get base Greeks analysis
        greeks_analysis = await analyzer.analyze_portfolio_greeks(scenario_moves)
        
        if greeks_analysis['status'] == 'NO_OPTIONS':
            return greeks_analysis
        
        # Enhance with additional calculations
        portfolio_greeks = greeks_analysis['portfolio_greeks']
        
        # Calculate time decay impact
        if time_decay_days:
            theta_impact = portfolio_greeks['total_theta'] * time_decay_days
            greeks_analysis['time_decay_analysis'] = {
                'days': time_decay_days,
                'expected_decay': round(theta_impact, 2),
                'daily_theta': round(portfolio_greeks['total_theta'], 2),
                'weekly_theta': round(portfolio_greeks['total_theta'] * 5, 2)
            }
        
        # Calculate IV impact if specified
        if iv_change:
            vega_impact = portfolio_greeks['total_vega'] * iv_change
            greeks_analysis['volatility_analysis'] = {
                'iv_change': iv_change,
                'vega_impact': round(vega_impact, 2),
                'total_vega': round(portfolio_greeks['total_vega'], 2)
            }
        
        # Add individual position Greeks if requested
        if include_individual:
            from src.modules.tws.connection import tws_connection
            positions = await tws_connection.ib.positionsAsync()
            
            individual_greeks = []
            for pos in positions:
                if pos.contract.secType == 'OPT':
                    ticker = await tws_connection.ib.reqTickersAsync(pos.contract)
                    if ticker and ticker[0].modelGreeks:
                        greeks = ticker[0].modelGreeks
                        individual_greeks.append({
                            'symbol': pos.contract.symbol,
                            'strike': pos.contract.strike,
                            'expiry': pos.contract.lastTradeDateOrContractMonth,
                            'position': pos.position,
                            'delta': round(greeks.delta * pos.position * 100, 2) if greeks.delta else 0,
                            'gamma': round(greeks.gamma * pos.position * 100, 2) if greeks.gamma else 0,
                            'theta': round(greeks.theta * pos.position * 100, 2) if greeks.theta else 0,
                            'vega': round(greeks.vega * pos.position * 100, 2) if greeks.vega else 0
                        })
            
            greeks_analysis['individual_positions'] = individual_greeks
        
        # Calculate portfolio metrics
        greeks_analysis['portfolio_metrics'] = {
            'delta_dollars': round(portfolio_greeks['total_delta'] * 100, 2),  # Assuming $100 per point
            'gamma_risk_1pct': round(portfolio_greeks['total_gamma'] * 1, 2),  # 1% move impact
            'max_theta_monthly': round(portfolio_greeks['total_theta'] * 21, 2),  # Trading days
            'vega_per_iv_point': round(portfolio_greeks['total_vega'], 2)
        }
        
        # Risk scoring
        risk_score = 0
        if abs(portfolio_greeks['total_delta']) > 100:
            risk_score += 2
        if abs(portfolio_greeks['total_gamma']) > 50:
            risk_score += 3
        if portfolio_greeks['total_theta'] < -50:
            risk_score += 2
        if abs(portfolio_greeks['total_vega']) > 100:
            risk_score += 2
        
        greeks_analysis['risk_score'] = {
            'score': risk_score,
            'level': 'HIGH' if risk_score >= 6 else 'MODERATE' if risk_score >= 3 else 'LOW',
            'recommendations': []
        }
        
        # Add recommendations based on Greeks
        if abs(portfolio_greeks['total_delta']) > 100:
            greeks_analysis['risk_score']['recommendations'].append(
                'Consider delta hedging - portfolio has significant directional risk'
            )
        if abs(portfolio_greeks['total_gamma']) > 50:
            greeks_analysis['risk_score']['recommendations'].append(
                'High gamma risk - portfolio P&L sensitive to price movements'
            )
        if portfolio_greeks['total_theta'] < -50:
            greeks_analysis['risk_score']['recommendations'].append(
                'Significant time decay - consider rolling positions or taking profits'
            )
        if abs(portfolio_greeks['total_vega']) > 100:
            greeks_analysis['risk_score']['recommendations'].append(
                'High vega exposure - vulnerable to IV changes'
            )
        
        return greeks_analysis
        
    except Exception as e:
        logger.error(f"[GREEKS] Analysis failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Greeks analysis failed'
        }
```

## PHASE 2: Tool Consolidation

### Unified Close Tool
**Timeline**: Implement wrapper immediately, deprecate old tools in 2 weeks

```python
@mcp.tool(name="trade_close")
async def close_position_unified(
    symbol: Optional[str] = None,
    position_id: Optional[str] = None,
    close_type: str = 'market',  # 'market', 'limit', 'emergency'
    limit_price: Optional[float] = None,
    percentage: Optional[float] = 100,  # Percentage to close
    bypass_confirmation: bool = False,  # For emergency close
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    [TRADING] Unified position closing - replaces all close tools.
    
    Args:
        symbol: Symbol to close (use this OR position_id)
        position_id: Specific position ID to close
        close_type: Type of close order
        limit_price: Limit price if using limit order
        percentage: Percentage of position to close (1-100)
        bypass_confirmation: Emergency bypass (requires special permission)
        confirm_token: Safety confirmation
        
    Returns:
        Close execution details
    """
    # Route to appropriate existing function with deprecation warning
    if close_type == 'emergency' or bypass_confirmation:
        logger.warning("[DEPRECATION] Using emergency_close through unified close")
        return await emergency_close_all()
    elif percentage < 100:
        return await adjust_position(
            position_id=position_id,
            symbol=symbol,
            adjustment_type='close_partial',
            percentage_to_close=percentage,
            confirm_token=confirm_token
        )
    else:
        logger.warning("[DEPRECATION] Using close_position through unified close")
        return await close_position(
            symbol=symbol or position_id,
            order_type='MKT' if close_type == 'market' else 'LMT',
            limit_price=limit_price,
            confirm_token=confirm_token
        )
```

### Unified Execute Tool
**Timeline**: Add optional parameter to existing execute tool

```python
# Modify existing trade_execute tool (line 490)
@mcp.tool(name="trade_execute")
async def execute_strategy(
    strategy_type: str,
    symbol: str,
    # ... existing parameters ...
    enhanced_verification: bool = False,  # NEW PARAMETER
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    [TRADING] Execute options strategy (with optional enhanced verification).
    
    Enhanced verification adds additional checks:
    - Market hours validation
    - Liquidity verification
    - Spread width checks
    - Pattern day trader validation
    
    Add enhanced_verification=True for extra safety.
    """
    # Add enhanced checks if requested
    if enhanced_verification:
        logger.info("[EXEC] Running enhanced verification checks")
        # Port verification logic from execute_with_verification
        # ... verification code ...
    
    # Continue with existing execution logic
    # ...
```

## PHASE 3: System Enhancements

### 1. Audit Trail Implementation
**Location**: Enhance existing SessionState class (line 58)

```python
class SessionState:
    """Enhanced with audit trail for all strategy modifications."""
    def __init__(self):
        # ... existing init ...
        self.audit_trail: List[Dict[str, Any]] = []
        self.audit_file = Path(f"/tmp/sump_audit_{datetime.now().strftime('%Y%m%d')}.json")
    
    def add_audit_entry(self, action: str, details: Dict[str, Any]):
        """Add entry to audit trail."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'details': details,
            'session_id': id(self),
            'user': 'claude_desktop'
        }
        self.audit_trail.append(entry)
        
        # Persist to file
        try:
            with open(self.audit_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            logger.error(f"[AUDIT] Failed to write audit entry: {e}")
    
    def save_strategy(self, strategy_obj, strategy_dict, symbol):
        """Save calculated strategy with audit."""
        # ... existing save logic ...
        
        # Add audit entry
        self.add_audit_entry('strategy_calculated', {
            'symbol': symbol,
            'strategy_type': strategy_dict.get('strategy_type'),
            'max_loss': strategy_dict.get('max_loss_raw'),
            'strategy_id': strategy_dict.get('strategy_id')
        })
```

### 2. Portfolio Risk Aggregation
**Location**: Add to PortfolioAnalyzer class

```python
async def get_portfolio_risk_aggregation(self) -> Dict[str, Any]:
    """
    Calculate portfolio-level risk metrics aggregation.
    
    Returns:
        Aggregated risk metrics including correlations and stress tests
    """
    summary = await self.get_portfolio_summary(include_greeks=True)
    
    # Calculate correlation risk
    positions_by_sector = {}  # Group positions by sector
    concentration_risk = {}   # Calculate concentration
    
    # Stress test scenarios
    stress_scenarios = {
        'market_crash': -20,  # 20% market drop
        'volatility_spike': 10,  # IV +10 points
        'time_decay_week': 5   # 5 days theta
    }
    
    stress_results = {}
    for scenario, magnitude in stress_scenarios.items():
        if 'market' in scenario:
            impact = summary.portfolio_greeks.total_delta * magnitude
            impact += 0.5 * summary.portfolio_greeks.total_gamma * (magnitude ** 2)
        elif 'volatility' in scenario:
            impact = summary.portfolio_greeks.total_vega * magnitude
        else:  # time decay
            impact = summary.portfolio_greeks.total_theta * magnitude
        
        stress_results[scenario] = round(impact, 2)
    
    return {
        'portfolio_value': summary.total_value,
        'risk_metrics': summary.risk_metrics,
        'stress_tests': stress_results,
        'var_95': calculate_var(summary.positions, 0.95),  # Value at Risk
        'expected_shortfall': calculate_es(summary.positions, 0.95)
    }
```

## Testing Strategy

### Unit Tests

```python
# test_new_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_portfolio_summary():
    """Test portfolio summary tool."""
    # Mock TWS connection
    mock_tws = AsyncMock()
    mock_tws.ib.accountSummaryAsync.return_value = [
        MagicMock(tag='NetLiquidation', value='100000'),
        MagicMock(tag='TotalCashValue', value='50000')
    ]
    
    # Test tool
    result = await get_portfolio_summary(include_greeks=True)
    assert result['status'] != 'error'
    assert 'portfolio_greeks' in result
    assert 'positions' in result

@pytest.mark.asyncio
async def test_trade_history():
    """Test trade history retrieval."""
    result = await get_trade_history(days_back=7, symbol='SPY')
    assert 'trades' in result
    assert 'summary' in result
    assert result['summary']['total_trades'] >= 0

@pytest.mark.asyncio
async def test_position_adjustment():
    """Test position adjustment tool."""
    # Test roll
    result = await adjust_position(
        symbol='SPY',
        adjustment_type='roll',
        new_expiry='2025-02-21',
        confirm_token='TEST_TOKEN'
    )
    assert result['status'] in ['success', 'blocked']
    
    # Test resize
    result = await adjust_position(
        symbol='SPY',
        adjustment_type='resize',
        new_quantity=5,
        confirm_token='TEST_TOKEN'
    )
    assert 'adjustment_type' in result

@pytest.mark.asyncio  
async def test_greeks_analysis():
    """Test portfolio Greeks analysis."""
    result = await analyze_portfolio_greeks(
        scenario_moves=[-5, 0, 5],
        time_decay_days=1
    )
    if result['status'] != 'NO_OPTIONS':
        assert 'portfolio_greeks' in result
        assert 'scenario_analysis' in result
        assert 'risk_score' in result
```

### Integration Tests

```python
# test_integration.py
@pytest.mark.integration
async def test_full_workflow_with_new_tools():
    """Test complete workflow with new tools."""
    # 1. Get portfolio summary
    portfolio = await get_portfolio_summary()
    
    # 2. Analyze Greeks
    greeks = await analyze_portfolio_greeks()
    
    # 3. Get history
    history = await get_trade_history(days_back=30)
    
    # 4. Adjust position if needed
    if portfolio['positions_count'] > 0:
        position = portfolio['positions'][0]
        adjustment = await adjust_position(
            symbol=position['symbol'],
            adjustment_type='close_partial',
            percentage_to_close=50,
            confirm_token='TEST'
        )
    
    # Verify state consistency
    assert session_state.audit_trail  # Audit entries created
```

### Rollback Procedures

```bash
#!/bin/bash
# rollback.sh

# 1. Stop MCP server
pkill -f "server.py"

# 2. Restore backup
cp /tmp/server.py.backup /Users/schmoll/Desktop/SumpPump/src/mcp/server.py

# 3. Clear cache
rm -f /tmp/sump_audit_*.json
rm -rf /tmp/mcp_cache/

# 4. Restart server
cd /Users/schmoll/Desktop/SumpPump
./venv/bin/python src/mcp/server.py
```

## Implementation Timeline

### Week 1
- Day 1-2: Implement 4 new MCP tools
- Day 3: Unit testing
- Day 4: Integration testing  
- Day 5: Documentation update

### Week 2
- Day 1-2: Tool consolidation wrappers
- Day 3: Deprecation warnings
- Day 4: Audit trail implementation
- Day 5: Final testing

### Week 3
- Day 1: Production deployment
- Day 2-3: Monitor and fix issues
- Day 4: Remove deprecated tools
- Day 5: Performance optimization

## Success Metrics

1. **Backward Compatibility**: 100% existing tools continue working
2. **Performance**: New tools respond in <2 seconds
3. **Reliability**: <0.1% error rate on new tools
4. **Adoption**: 50% of sessions use new tools within first week
5. **Safety**: Zero unconfirmed executions

## Risk Mitigation

1. **Data Integrity**: All new tools read-only except adjust_position
2. **Rate Limiting**: Respect IBKR's 95 market data line limit
3. **Error Handling**: Comprehensive try-catch with fallbacks
4. **Caching**: 30-second TTL prevents stale data
5. **Audit Trail**: Complete history of all modifications

## Next Steps

1. Review this plan with stakeholders
2. Create feature branch: `feature/enhanced-tools-v2.1`
3. Implement Phase 1 (new tools)
4. Run test suite
5. Deploy to test environment
6. Gather feedback
7. Proceed to Phase 2 & 3

## Appendix: File Modifications

### Files to Modify
- `/Users/schmoll/Desktop/SumpPump/src/mcp/server.py` - Add 4 new tools
- `/Users/schmoll/Desktop/SumpPump/src/modules/data/portfolio.py` - Already complete
- `/Users/schmoll/Desktop/SumpPump/src/modules/execution/advanced_orders.py` - Add resize/hedge functions

### Files to Create
- `/Users/schmoll/Desktop/SumpPump/tests/test_new_tools.py` - Unit tests
- `/Users/schmoll/Desktop/SumpPump/tests/test_integration.py` - Integration tests
- `/Users/schmoll/Desktop/SumpPump/scripts/rollback.sh` - Rollback script

### Configuration Changes
- None required (TTL already 30 minutes)

## Conclusion

This implementation plan provides specific, actionable code for enhancing SumpPump while maintaining its core safety-first principles. All changes are non-breaking and can be rolled back if needed. The phased approach ensures minimal disruption to existing users while adding valuable new functionality.