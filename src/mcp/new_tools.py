"""
New MCP Tools for SumpPump v2.1
These tools can be directly copied into server.py at line 3687
"""

# ============================================================================
# NEW PORTFOLIO & ANALYSIS TOOLS
# Add these after line 3686 in server.py
# ============================================================================

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
    params = {
        'position_id': position_id,
        'symbol': symbol,
        'adjustment_type': adjustment_type,
        'new_quantity': new_quantity,
        'new_strike': new_strike,
        'new_expiry': new_expiry,
        'hedge_strategy': hedge_strategy,
        'percentage_to_close': percentage_to_close,
        'confirm_token': confirm_token
    }
    
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
        
        # Route to appropriate handler based on adjustment_type
        if adjustment_type == 'roll':
            # Use existing roll functionality
            from src.modules.execution.advanced_orders import roll_option_position
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
            # Add protective hedge - simplified implementation
            if not symbol:
                return {
                    'status': 'error',
                    'error': 'Symbol required for hedge'
                }
            
            # This would need full implementation in advanced_orders module
            result = {
                'status': 'pending_implementation',
                'message': 'Hedge functionality requires advanced_orders module update',
                'hedge_strategy': hedge_strategy,
                'symbol': symbol
            }
            
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
        
        # Update session state with audit trail
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


# ============================================================================
# CONSOLIDATED TOOLS (Phase 2 - Optional Implementation)
# ============================================================================

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
    logger.info(f"[CLOSE] Unified close for {symbol or position_id}, "
               f"type={close_type}, percentage={percentage}%")
    
    # Route to appropriate handler
    if close_type == 'emergency' or bypass_confirmation:
        logger.warning("[DEPRECATION] Using emergency_close through unified close")
        # Call existing emergency_close_all function
        return await emergency_close_all()
        
    elif percentage < 100:
        # Partial close via adjust_position
        return await adjust_position(
            position_id=position_id,
            symbol=symbol,
            adjustment_type='close_partial',
            percentage_to_close=percentage,
            confirm_token=confirm_token
        )
        
    else:
        # Full close via existing close_position
        logger.warning("[DEPRECATION] Using close_position through unified close")
        return await close_position(
            symbol=symbol or position_id,
            order_type='MKT' if close_type == 'market' else 'LMT',
            limit_price=limit_price,
            confirm_token=confirm_token
        )