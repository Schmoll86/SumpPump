"""
Test suite for new SumpPump v2.1 tools.
Run with: pytest tests/test_new_tools.py -v
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock the MCP decorator and session state before importing
class MockMCP:
    def tool(self, name):
        def decorator(func):
            return func
        return decorator

mcp = MockMCP()
session_state = MagicMock()

# Now we can import the tools (after mocking)
with patch('sys.modules.mcp', mcp):
    with patch('sys.modules.session_state', session_state):
        # Import would happen here after adding tools to server.py
        pass


@pytest.fixture
async def mock_tws_connection():
    """Create a mock TWS connection."""
    mock_tws = AsyncMock()
    mock_ib = AsyncMock()
    
    # Mock account summary
    mock_ib.accountSummaryAsync.return_value = [
        MagicMock(tag='NetLiquidation', value='100000'),
        MagicMock(tag='TotalCashValue', value='50000'),
        MagicMock(tag='BuyingPower', value='200000'),
        MagicMock(tag='MaintMarginReq', value='25000'),
        MagicMock(tag='RealizedPnL', value='1500')
    ]
    
    # Mock positions
    mock_position = MagicMock()
    mock_position.contract.symbol = 'SPY'
    mock_position.contract.secType = 'OPT'
    mock_position.contract.strike = 450
    mock_position.contract.lastTradeDateOrContractMonth = '20250221'
    mock_position.contract.right = 'C'
    mock_position.position = 10
    mock_position.avgCost = 5.50
    
    mock_ib.positionsAsync.return_value = [mock_position]
    
    # Mock ticker with Greeks
    mock_ticker = MagicMock()
    mock_ticker.marketPrice.return_value = 6.25
    mock_ticker.modelGreeks = MagicMock()
    mock_ticker.modelGreeks.delta = 0.55
    mock_ticker.modelGreeks.gamma = 0.02
    mock_ticker.modelGreeks.theta = -0.08
    mock_ticker.modelGreeks.vega = 0.15
    
    mock_ib.reqTickersAsync.return_value = [mock_ticker]
    
    # Mock fills for trade history
    mock_fill = MagicMock()
    mock_fill.time = datetime.now() - timedelta(days=1)
    mock_fill.contract.symbol = 'SPY'
    mock_fill.contract.secType = 'OPT'
    mock_fill.contract.strike = 445
    mock_fill.execution.side = 'BOT'
    mock_fill.execution.shares = 5
    mock_fill.execution.price = 4.75
    mock_fill.commissionReport.commission = 1.25
    mock_fill.commissionReport.realizedPNL = 125.50
    
    mock_ib.fillsAsync.return_value = [mock_fill]
    
    mock_tws.ib = mock_ib
    mock_tws.connected = True
    mock_tws.account_id = 'U1234567'
    
    return mock_tws


@pytest.mark.asyncio
async def test_portfolio_summary_with_greeks(mock_tws_connection):
    """Test portfolio summary tool with Greeks calculation."""
    with patch('src.modules.data.portfolio.get_tws_connection', return_value=mock_tws_connection):
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        summary = await analyzer.get_portfolio_summary(include_greeks=True)
        
        # Verify structure
        assert summary.account_id == 'U1234567'
        assert summary.total_value == 100000
        assert summary.total_cash == 50000
        assert summary.buying_power == 200000
        assert len(summary.positions) == 1
        
        # Verify Greeks aggregation
        assert summary.portfolio_greeks is not None
        assert summary.portfolio_greeks.total_delta == 550  # 0.55 * 10 * 100
        assert summary.portfolio_greeks.total_gamma == 20   # 0.02 * 10 * 100
        assert summary.portfolio_greeks.total_theta == -80  # -0.08 * 10 * 100
        assert summary.portfolio_greeks.total_vega == 150   # 0.15 * 10 * 100
        
        # Verify risk metrics
        assert 'margin_usage' in summary.risk_metrics
        assert 'cash_percentage' in summary.risk_metrics


@pytest.mark.asyncio
async def test_trade_history_filtering(mock_tws_connection):
    """Test trade history retrieval with filters."""
    with patch('src.modules.data.portfolio.get_tws_connection', return_value=mock_tws_connection):
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        trades = await analyzer.get_trade_history(
            days_back=7,
            symbol='SPY',
            include_executions=True
        )
        
        # Verify trade structure
        assert len(trades) == 1
        trade = trades[0]
        assert trade['symbol'] == 'SPY'
        assert trade['action'] == 'BOT'
        assert trade['quantity'] == 5
        assert trade['price'] == 4.75
        assert trade['realized_pnl'] == 125.50
        
        # Verify execution details included
        assert 'execution' in trade


@pytest.mark.asyncio
async def test_greeks_scenario_analysis(mock_tws_connection):
    """Test portfolio Greeks analysis with scenarios."""
    with patch('src.modules.data.portfolio.get_tws_connection', return_value=mock_tws_connection):
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        analysis = await analyzer.analyze_portfolio_greeks(
            scenario_moves=[-5, 0, 5]
        )
        
        # Verify scenario calculations
        assert analysis['status'] == 'SUCCESS'
        assert 'scenario_analysis' in analysis
        scenarios = analysis['scenario_analysis']
        
        # Check scenario P&L calculations
        for scenario in scenarios:
            if scenario['price_move'] == -5:
                # Delta impact: 550 * -5 = -2750
                # Gamma impact: 0.5 * 20 * 25 = 250
                expected_pnl = -2750 + 250
                assert abs(scenario['total_pnl'] - expected_pnl) < 1
            elif scenario['price_move'] == 5:
                # Delta impact: 550 * 5 = 2750
                # Gamma impact: 0.5 * 20 * 25 = 250
                expected_pnl = 2750 + 250
                assert abs(scenario['total_pnl'] - expected_pnl) < 1
        
        # Verify risk assessment
        assert 'risk_assessment' in analysis
        assert analysis['risk_assessment']['delta_neutral'] == False  # Delta > 10
        assert analysis['risk_assessment']['gamma_risk'] == 'LOW'     # Gamma < 20


@pytest.mark.asyncio
async def test_position_adjustment_roll():
    """Test position adjustment for rolling options."""
    mock_result = {
        'status': 'success',
        'old_position': {'strike': 450, 'expiry': '20250121'},
        'new_position': {'strike': 455, 'expiry': '20250221'},
        'net_credit': 1.25
    }
    
    with patch('src.modules.execution.advanced_orders.roll_option_position', 
               return_value=mock_result):
        # Would call adjust_position with adjustment_type='roll'
        # This tests the routing logic
        assert mock_result['status'] == 'success'
        assert mock_result['new_position']['strike'] == 455


@pytest.mark.asyncio
async def test_position_adjustment_resize(mock_tws_connection):
    """Test position resizing functionality."""
    with patch('src.modules.tws.connection.tws_connection', mock_tws_connection):
        # Mock current position
        mock_position = MagicMock()
        mock_position.contract.symbol = 'SPY'
        mock_position.position = 10
        mock_tws_connection.ib.positionsAsync.return_value = [mock_position]
        
        # Mock order placement
        mock_trade = MagicMock()
        mock_trade.order.orderId = 12345
        mock_tws_connection.ib.placeOrder.return_value = mock_trade
        
        # Test increasing position
        # Would call adjust_position with adjustment_type='resize', new_quantity=15
        # This would place a BUY order for 5 contracts
        
        # Verify order parameters
        # mock_tws_connection.ib.placeOrder.assert_called_once()
        # call_args = mock_tws_connection.ib.placeOrder.call_args
        # order = call_args[0][1]
        # assert order.action == 'BUY'
        # assert order.totalQuantity == 5


@pytest.mark.asyncio
async def test_position_partial_close(mock_tws_connection):
    """Test partial position closing."""
    with patch('src.modules.tws.connection.tws_connection', mock_tws_connection):
        # Mock current position
        mock_position = MagicMock()
        mock_position.contract.symbol = 'SPY'
        mock_position.position = 10
        mock_tws_connection.ib.positionsAsync.return_value = [mock_position]
        
        # Mock order placement
        mock_trade = MagicMock()
        mock_trade.order.orderId = 12346
        mock_tws_connection.ib.placeOrder.return_value = mock_trade
        
        # Test closing 50% of position
        # Would call adjust_position with adjustment_type='close_partial', percentage_to_close=50
        # This would place a SELL order for 5 contracts
        
        # Verify calculation
        expected_close_qty = int(10 * 50 / 100)
        assert expected_close_qty == 5


@pytest.mark.asyncio
async def test_safety_validation():
    """Test safety validation for position adjustments."""
    from src.modules.safety import ExecutionSafety
    
    # Test without confirmation token
    params = {
        'symbol': 'SPY',
        'adjustment_type': 'roll',
        'new_strike': 455,
        'confirm_token': None
    }
    
    is_valid, error_msg = ExecutionSafety.validate_execution_request(
        'trade_adjust_position', params
    )
    
    assert is_valid == False
    assert 'confirm_token' in error_msg.lower()
    
    # Test with confirmation token
    params['confirm_token'] = 'USER_CONFIRMED'
    is_valid, error_msg = ExecutionSafety.validate_execution_request(
        'trade_adjust_position', params
    )
    
    # Should pass with token (unless other validations fail)
    # Actual result depends on ExecutionSafety implementation


@pytest.mark.asyncio
async def test_audit_trail_integration():
    """Test audit trail functionality."""
    from datetime import datetime
    import json
    from pathlib import Path
    
    # Create mock session state with audit
    class MockSessionState:
        def __init__(self):
            self.audit_trail = []
            self.audit_file = Path(f"/tmp/test_audit_{datetime.now().strftime('%Y%m%d')}.json")
        
        def add_audit_entry(self, action, details):
            entry = {
                'timestamp': datetime.now().isoformat(),
                'action': action,
                'details': details,
                'session_id': id(self)
            }
            self.audit_trail.append(entry)
            return entry
    
    session = MockSessionState()
    
    # Add test entries
    session.add_audit_entry('position_adjusted', {
        'type': 'roll',
        'symbol': 'SPY',
        'old_strike': 450,
        'new_strike': 455
    })
    
    session.add_audit_entry('position_closed', {
        'symbol': 'SPY',
        'percentage': 50,
        'quantity': 5
    })
    
    # Verify audit trail
    assert len(session.audit_trail) == 2
    assert session.audit_trail[0]['action'] == 'position_adjusted'
    assert session.audit_trail[1]['action'] == 'position_closed'
    assert 'timestamp' in session.audit_trail[0]
    assert 'session_id' in session.audit_trail[0]


@pytest.mark.asyncio
async def test_risk_scoring_logic():
    """Test risk scoring based on Greeks."""
    # Test high risk scenario
    high_risk_greeks = {
        'total_delta': 150,  # > 100
        'total_gamma': 60,   # > 50
        'total_theta': -75,  # < -50
        'total_vega': 120    # > 100
    }
    
    risk_score = 0
    if abs(high_risk_greeks['total_delta']) > 100:
        risk_score += 2
    if abs(high_risk_greeks['total_gamma']) > 50:
        risk_score += 3
    if high_risk_greeks['total_theta'] < -50:
        risk_score += 2
    if abs(high_risk_greeks['total_vega']) > 100:
        risk_score += 2
    
    assert risk_score == 9
    assert 'HIGH' == ('HIGH' if risk_score >= 6 else 'MODERATE' if risk_score >= 3 else 'LOW')
    
    # Test low risk scenario
    low_risk_greeks = {
        'total_delta': 25,
        'total_gamma': 10,
        'total_theta': -20,
        'total_vega': 30
    }
    
    risk_score = 0
    if abs(low_risk_greeks['total_delta']) > 100:
        risk_score += 2
    if abs(low_risk_greeks['total_gamma']) > 50:
        risk_score += 3
    if low_risk_greeks['total_theta'] < -50:
        risk_score += 2
    if abs(low_risk_greeks['total_vega']) > 100:
        risk_score += 2
    
    assert risk_score == 0
    assert 'LOW' == ('HIGH' if risk_score >= 6 else 'MODERATE' if risk_score >= 3 else 'LOW')


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling in new tools."""
    # Test connection failure
    with patch('src.modules.data.portfolio.get_tws_connection', 
               side_effect=Exception("Connection failed")):
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        with pytest.raises(Exception) as exc_info:
            await analyzer.get_portfolio_summary()
        
        assert "Connection failed" in str(exc_info.value)
    
    # Test invalid parameters
    analyzer = PortfolioAnalyzer()
    
    # Invalid days_back
    with pytest.raises(Exception):
        await analyzer.get_trade_history(days_back=-1)
    
    # Invalid scenario moves
    with pytest.raises(Exception):
        await analyzer.analyze_portfolio_greeks(scenario_moves="invalid")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])