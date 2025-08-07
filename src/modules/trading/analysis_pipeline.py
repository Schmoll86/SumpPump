"""
Pre-Trade Analysis Pipeline
Enforces complete analysis workflow before trading
"""

import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from loguru import logger

from src.modules.trading.session import TradingSession, SessionState


class AnalysisStep(Enum):
    """Analysis pipeline steps."""
    NEWS = "news_analysis"
    VOLATILITY = "volatility_analysis"
    OPTIONS_CHAIN = "options_chain"
    STRATEGY_CALC = "strategy_calculation"
    RISK_CHECK = "risk_validation"


@dataclass
class AnalysisRequirements:
    """Requirements for each analysis step."""
    news_required: bool = True
    volatility_required: bool = True
    options_chain_required: bool = True
    strategy_required: bool = True
    risk_validation_required: bool = True
    
    # Thresholds
    min_news_items: int = 1
    max_iv_rank: float = 80.0  # Don't trade if IV rank > 80%
    min_volume: int = 100  # Min option volume
    max_risk_percent: float = 2.0  # Max 2% portfolio risk


class AnalysisResult:
    """Result of an analysis step."""
    
    def __init__(self, step: AnalysisStep, success: bool, data: Any, message: str = ""):
        self.step = step
        self.success = success
        self.data = data
        self.message = message
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step.value,
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "has_data": self.data is not None
        }


class PreTradeAnalysisPipeline:
    """
    Enforces complete pre-trade analysis workflow.
    No trading without proper analysis.
    """
    
    def __init__(self, session: TradingSession, requirements: Optional[AnalysisRequirements] = None):
        """
        Initialize pipeline.
        
        Args:
            session: Trading session to update
            requirements: Analysis requirements (uses defaults if None)
        """
        self.session = session
        self.requirements = requirements or AnalysisRequirements()
        self.results: Dict[AnalysisStep, AnalysisResult] = {}
        self._analysis_complete = False
        
        logger.info(f"[PIPELINE] Initialized for session {session.session_id}")
    
    async def run_analysis(
        self,
        symbol: str,
        tws_connection: Any,
        mcp_tools: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Run complete pre-trade analysis.
        
        Args:
            symbol: Stock symbol to analyze
            tws_connection: TWS connection instance
            mcp_tools: Dictionary of MCP tool functions
            
        Returns:
            (success, analysis_data)
        """
        logger.info(f"[PIPELINE] Starting analysis for {symbol}")
        
        # Transition to analyzing state
        await self.session.transition(SessionState.ANALYZING)
        
        try:
            # Step 1: News Analysis
            if self.requirements.news_required:
                news_result = await self._analyze_news(symbol, mcp_tools.get('trade_get_news'))
                self.results[AnalysisStep.NEWS] = news_result
                
                if not news_result.success:
                    logger.warning(f"[PIPELINE] News analysis failed: {news_result.message}")
                    # Continue anyway - news might not be critical
            
            # Step 2: Volatility Analysis
            if self.requirements.volatility_required:
                vol_result = await self._analyze_volatility(
                    symbol,
                    mcp_tools.get('trade_get_volatility_analysis')
                )
                self.results[AnalysisStep.VOLATILITY] = vol_result
                
                if not vol_result.success:
                    return await self._fail_analysis("Volatility analysis failed")
                
                # Check IV rank threshold
                iv_rank = vol_result.data.get('iv_rank', 0)
                if iv_rank > self.requirements.max_iv_rank:
                    return await self._fail_analysis(
                        f"IV rank too high: {iv_rank:.1f}% > {self.requirements.max_iv_rank}%"
                    )
            
            # Step 3: Options Chain
            if self.requirements.options_chain_required:
                chain_result = await self._get_options_chain(
                    symbol,
                    mcp_tools.get('trade_get_options_chain')
                )
                self.results[AnalysisStep.OPTIONS_CHAIN] = chain_result
                
                if not chain_result.success:
                    return await self._fail_analysis("Failed to get options chain")
                
                # Validate chain has sufficient liquidity
                if not self._validate_chain_liquidity(chain_result.data):
                    return await self._fail_analysis("Insufficient options liquidity")
            
            # Store analysis data in session
            analysis_data = {
                'news': self.results.get(AnalysisStep.NEWS, AnalysisResult(AnalysisStep.NEWS, False, None)).data,
                'volatility': self.results.get(AnalysisStep.VOLATILITY, AnalysisResult(AnalysisStep.VOLATILITY, False, None)).data,
                'options_chain': self.results.get(AnalysisStep.OPTIONS_CHAIN, AnalysisResult(AnalysisStep.OPTIONS_CHAIN, False, None)).data
            }
            
            await self.session.transition(
                SessionState.ANALYZING,
                analysis_data
            )
            
            self._analysis_complete = True
            
            logger.info("[PIPELINE] Pre-trade analysis complete")
            return True, self._compile_analysis_summary()
            
        except Exception as e:
            logger.error(f"[PIPELINE] Analysis failed: {e}")
            self.session.add_error("analysis_pipeline_error", str(e))
            await self.session.transition(SessionState.ERROR)
            return False, {"error": str(e)}
    
    async def validate_strategy(
        self,
        strategy: Dict[str, Any],
        mcp_tools: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate a selected strategy.
        
        Args:
            strategy: Strategy configuration
            mcp_tools: MCP tool functions
            
        Returns:
            (is_valid, validation_result)
        """
        if not self._analysis_complete:
            return False, {"error": "Cannot validate strategy without complete analysis"}
        
        logger.info(f"[PIPELINE] Validating strategy: {strategy.get('strategy_type')}")
        
        # Calculate strategy P&L
        calc_tool = mcp_tools.get('trade_calculate_strategy')
        if calc_tool:
            strategy_result = await self._calculate_strategy(strategy, calc_tool)
            self.results[AnalysisStep.STRATEGY_CALC] = strategy_result
            
            if not strategy_result.success:
                return False, {"error": f"Strategy calculation failed: {strategy_result.message}"}
            
            # Store strategy in session
            await self.session.transition(
                SessionState.STRATEGY_SELECTED,
                {
                    'strategy': strategy,
                    'pnl_profile': strategy_result.data
                }
            )
            
            return True, strategy_result.data
        
        return False, {"error": "Strategy calculation tool not available"}
    
    async def validate_risk(
        self,
        strategy: Dict[str, Any],
        account: Dict[str, Any],
        mcp_tools: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate risk parameters.
        
        Args:
            strategy: Strategy to validate
            account: Account information
            mcp_tools: MCP tool functions
            
        Returns:
            (is_valid, risk_check_result)
        """
        logger.info("[PIPELINE] Validating risk parameters")
        
        risk_tool = mcp_tools.get('trade_check_margin_risk')
        if not risk_tool:
            return False, {"error": "Risk validation tool not available"}
        
        risk_result = await self._check_risk(strategy, account, risk_tool)
        self.results[AnalysisStep.RISK_CHECK] = risk_result
        
        if not risk_result.success:
            return False, {"error": f"Risk validation failed: {risk_result.message}"}
        
        risk_data = risk_result.data
        
        # Apply our risk rules
        checks = {
            'buying_power': risk_data.get('has_buying_power', False),
            'margin': risk_data.get('has_margin', False),
            'risk_percent': risk_data.get('portfolio_risk_percent', 100) <= self.requirements.max_risk_percent,
            'approved': True  # Will be set to False if any check fails
        }
        
        # Check all requirements
        if not checks['buying_power']:
            checks['approved'] = False
            risk_data['rejection_reason'] = "Insufficient buying power"
        elif not checks['margin']:
            checks['approved'] = False
            risk_data['rejection_reason'] = "Insufficient margin"
        elif not checks['risk_percent']:
            checks['approved'] = False
            risk_data['rejection_reason'] = f"Risk exceeds {self.requirements.max_risk_percent}% limit"
        
        # Update session
        await self.session.transition(
            SessionState.RISK_VALIDATED if checks['approved'] else SessionState.STRATEGY_SELECTED,
            {
                'risk_check': checks,
                'account_snapshot': account
            }
        )
        
        return checks['approved'], risk_data
    
    async def _analyze_news(self, symbol: str, news_tool: Any) -> AnalysisResult:
        """Run news analysis."""
        try:
            if not news_tool:
                return AnalysisResult(AnalysisStep.NEWS, False, None, "News tool not available")
            
            news_data = await news_tool(symbol=symbol, max_items=10)
            
            if 'error' in news_data:
                return AnalysisResult(AnalysisStep.NEWS, False, None, news_data['error'])
            
            # Check minimum news items
            news_items = news_data.get('news', [])
            if len(news_items) < self.requirements.min_news_items:
                return AnalysisResult(
                    AnalysisStep.NEWS,
                    False,
                    news_data,
                    f"Insufficient news: {len(news_items)} < {self.requirements.min_news_items}"
                )
            
            return AnalysisResult(AnalysisStep.NEWS, True, news_data)
            
        except Exception as e:
            return AnalysisResult(AnalysisStep.NEWS, False, None, str(e))
    
    async def _analyze_volatility(self, symbol: str, vol_tool: Any) -> AnalysisResult:
        """Run volatility analysis."""
        try:
            if not vol_tool:
                return AnalysisResult(AnalysisStep.VOLATILITY, False, None, "Volatility tool not available")
            
            vol_data = await vol_tool(symbol=symbol)
            
            if 'error' in vol_data:
                return AnalysisResult(AnalysisStep.VOLATILITY, False, None, vol_data['error'])
            
            return AnalysisResult(AnalysisStep.VOLATILITY, True, vol_data)
            
        except Exception as e:
            return AnalysisResult(AnalysisStep.VOLATILITY, False, None, str(e))
    
    async def _get_options_chain(self, symbol: str, chain_tool: Any) -> AnalysisResult:
        """Get options chain."""
        try:
            if not chain_tool:
                return AnalysisResult(AnalysisStep.OPTIONS_CHAIN, False, None, "Chain tool not available")
            
            chain_data = await chain_tool(symbol=symbol, min_dte=7, max_dte=60)
            
            if 'error' in chain_data:
                return AnalysisResult(AnalysisStep.OPTIONS_CHAIN, False, None, chain_data['error'])
            
            return AnalysisResult(AnalysisStep.OPTIONS_CHAIN, True, chain_data)
            
        except Exception as e:
            return AnalysisResult(AnalysisStep.OPTIONS_CHAIN, False, None, str(e))
    
    async def _calculate_strategy(self, strategy: Dict[str, Any], calc_tool: Any) -> AnalysisResult:
        """Calculate strategy P&L."""
        try:
            calc_data = await calc_tool(
                strategy_type=strategy['strategy_type'],
                symbol=strategy['symbol'],
                strikes=strategy['strikes'],
                expiry=strategy.get('expiry'),
                quantity=strategy.get('quantity', 1)
            )
            
            if 'error' in calc_data:
                return AnalysisResult(AnalysisStep.STRATEGY_CALC, False, None, calc_data['error'])
            
            return AnalysisResult(AnalysisStep.STRATEGY_CALC, True, calc_data)
            
        except Exception as e:
            return AnalysisResult(AnalysisStep.STRATEGY_CALC, False, None, str(e))
    
    async def _check_risk(self, strategy: Dict[str, Any], account: Dict[str, Any], risk_tool: Any) -> AnalysisResult:
        """Check risk parameters."""
        try:
            risk_data = await risk_tool(
                strategy=strategy,
                account_balance=account.get('net_liquidation', 0)
            )
            
            if 'error' in risk_data:
                return AnalysisResult(AnalysisStep.RISK_CHECK, False, None, risk_data['error'])
            
            return AnalysisResult(AnalysisStep.RISK_CHECK, True, risk_data)
            
        except Exception as e:
            return AnalysisResult(AnalysisStep.RISK_CHECK, False, None, str(e))
    
    def _validate_chain_liquidity(self, chain_data: Dict[str, Any]) -> bool:
        """Validate options chain has sufficient liquidity."""
        if not chain_data:
            return False
        
        options = chain_data.get('options', [])
        if not options:
            return False
        
        # Check that at least some options meet volume threshold
        liquid_options = [
            opt for opt in options
            if opt.get('volume', 0) >= self.requirements.min_volume
        ]
        
        return len(liquid_options) > 0
    
    async def _fail_analysis(self, reason: str) -> Tuple[bool, Dict[str, Any]]:
        """Handle analysis failure."""
        logger.error(f"[PIPELINE] Analysis failed: {reason}")
        self.session.add_error("analysis_failure", reason)
        await self.session.transition(SessionState.ERROR)
        return False, {"error": reason, "results": self._compile_analysis_summary()}
    
    def _compile_analysis_summary(self) -> Dict[str, Any]:
        """Compile summary of all analysis results."""
        return {
            "symbol": self.session.context.symbol,
            "complete": self._analysis_complete,
            "steps": {
                step.value: result.to_dict()
                for step, result in self.results.items()
            },
            "has_news": AnalysisStep.NEWS in self.results and self.results[AnalysisStep.NEWS].success,
            "has_volatility": AnalysisStep.VOLATILITY in self.results and self.results[AnalysisStep.VOLATILITY].success,
            "has_chain": AnalysisStep.OPTIONS_CHAIN in self.results and self.results[AnalysisStep.OPTIONS_CHAIN].success,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_missing_steps(self) -> List[str]:
        """Get list of missing analysis steps."""
        missing = []
        
        if self.requirements.news_required and AnalysisStep.NEWS not in self.results:
            missing.append("news_analysis")
        
        if self.requirements.volatility_required and AnalysisStep.VOLATILITY not in self.results:
            missing.append("volatility_analysis")
        
        if self.requirements.options_chain_required and AnalysisStep.OPTIONS_CHAIN not in self.results:
            missing.append("options_chain")
        
        return missing