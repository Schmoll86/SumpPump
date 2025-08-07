"""
Risk Validation Framework
Comprehensive risk checks before any trade execution
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from loguru import logger


class RiskLevel(Enum):
    """Risk levels for position sizing."""
    CONSERVATIVE = 0.01  # 1% of portfolio
    MODERATE = 0.02      # 2% of portfolio
    AGGRESSIVE = 0.03    # 3% of portfolio
    MAXIMUM = 0.05       # 5% of portfolio (hard limit)


@dataclass
class RiskProfile:
    """User risk profile configuration."""
    max_position_risk: float = 0.02  # 2% default
    max_portfolio_risk: float = 0.06  # 6% total portfolio risk
    max_positions: int = 10
    max_correlation_risk: float = 0.04  # Max risk in correlated positions
    require_stop_loss: bool = True
    min_win_rate: float = 0.4  # Minimum 40% win rate for strategy
    min_risk_reward: float = 1.5  # Minimum 1.5:1 reward/risk ratio
    
    # Level-specific limits
    level2_max_contracts: int = 10
    level2_forbidden_strategies: List[str] = None
    
    def __post_init__(self):
        if self.level2_forbidden_strategies is None:
            self.level2_forbidden_strategies = [
                'naked_call', 'naked_put', 'short_straddle',
                'short_strangle', 'ratio_spread', 'cash_secured_put'
            ]


@dataclass
class RiskMetrics:
    """Calculated risk metrics for a trade."""
    max_loss: float
    max_profit: float
    risk_reward_ratio: float
    portfolio_risk_percent: float
    buying_power_required: float
    margin_required: float
    breakeven_points: List[float]
    probability_profit: Optional[float] = None
    expected_value: Optional[float] = None
    kelly_criterion: Optional[float] = None


class RiskValidationFramework:
    """
    Comprehensive risk validation before trade execution.
    """
    
    def __init__(self, risk_profile: Optional[RiskProfile] = None):
        """
        Initialize risk framework.
        
        Args:
            risk_profile: User risk preferences (uses defaults if None)
        """
        self.profile = risk_profile or RiskProfile()
        self.active_risk: Dict[str, float] = {}  # Symbol -> current risk
        self.correlation_groups: Dict[str, List[str]] = {
            'tech': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA'],
            'finance': ['JPM', 'BAC', 'GS', 'MS', 'WFC'],
            'energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG']
        }
        
        logger.info(f"[RISK] Framework initialized with max position risk: {self.profile.max_position_risk:.1%}")
    
    def validate_trade(
        self,
        strategy: Dict[str, Any],
        account: Dict[str, Any],
        current_positions: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate a trade against all risk parameters.
        
        Args:
            strategy: Strategy to validate
            account: Account information
            current_positions: Current open positions
            
        Returns:
            (is_valid, validation_result)
        """
        logger.info(f"[RISK] Validating trade: {strategy.get('symbol')} {strategy.get('strategy_type')}")
        
        validation_result = {
            'timestamp': datetime.now().isoformat(),
            'symbol': strategy.get('symbol'),
            'strategy_type': strategy.get('strategy_type'),
            'checks': {},
            'metrics': None,
            'approved': False,
            'rejection_reasons': []
        }
        
        # Calculate risk metrics
        metrics = self._calculate_risk_metrics(strategy, account)
        validation_result['metrics'] = metrics.__dict__
        
        # Run all validation checks
        checks = {
            'strategy_allowed': self._check_strategy_allowed(strategy),
            'position_risk': self._check_position_risk(metrics, account),
            'portfolio_risk': self._check_portfolio_risk(metrics, account, current_positions),
            'buying_power': self._check_buying_power(metrics, account),
            'margin': self._check_margin(metrics, account),
            'position_limits': self._check_position_limits(current_positions),
            'correlation_risk': self._check_correlation_risk(strategy, current_positions),
            'risk_reward': self._check_risk_reward(metrics),
            'stop_loss': self._check_stop_loss_requirement(strategy)
        }
        
        validation_result['checks'] = checks
        
        # Determine overall approval
        failed_checks = [name for name, result in checks.items() if not result['passed']]
        
        if not failed_checks:
            validation_result['approved'] = True
            logger.info(f"[RISK] Trade APPROVED for {strategy.get('symbol')}")
        else:
            validation_result['approved'] = False
            validation_result['rejection_reasons'] = [
                checks[name]['reason'] for name in failed_checks
            ]
            logger.warning(f"[RISK] Trade REJECTED: {', '.join(failed_checks)}")
        
        return validation_result['approved'], validation_result
    
    def _calculate_risk_metrics(self, strategy: Dict[str, Any], account: Dict[str, Any]) -> RiskMetrics:
        """Calculate risk metrics for the strategy."""
        max_loss = abs(strategy.get('max_loss', 0))
        max_profit = strategy.get('max_profit', 0)
        
        # Risk/reward ratio
        risk_reward = max_profit / max_loss if max_loss > 0 else 0
        
        # Portfolio risk percentage
        net_liquidation = account.get('net_liquidation', 0)
        portfolio_risk_pct = (max_loss / net_liquidation) if net_liquidation > 0 else 1.0
        
        # Margin and buying power (simplified - should be calculated from strategy)
        buying_power_req = max_loss  # For cash-secured strategies
        margin_req = max_loss * 0.3  # Rough estimate for margin strategies
        
        # Breakeven points
        breakevens = strategy.get('breakeven', [])
        
        return RiskMetrics(
            max_loss=max_loss,
            max_profit=max_profit,
            risk_reward_ratio=risk_reward,
            portfolio_risk_percent=portfolio_risk_pct,
            buying_power_required=buying_power_req,
            margin_required=margin_req,
            breakeven_points=breakevens
        )
    
    def _check_strategy_allowed(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Check if strategy type is allowed."""
        strategy_type = strategy.get('strategy_type', '')
        
        if strategy_type in self.profile.level2_forbidden_strategies:
            return {
                'passed': False,
                'reason': f"Strategy '{strategy_type}' requires Level 3+ permissions",
                'details': f"Forbidden strategies: {self.profile.level2_forbidden_strategies}"
            }
        
        # Check contract limits for Level 2
        quantity = strategy.get('quantity', 1)
        if quantity > self.profile.level2_max_contracts:
            return {
                'passed': False,
                'reason': f"Quantity {quantity} exceeds Level 2 limit of {self.profile.level2_max_contracts}",
                'details': "Reduce position size"
            }
        
        return {'passed': True, 'reason': 'Strategy type allowed'}
    
    def _check_position_risk(self, metrics: RiskMetrics, account: Dict[str, Any]) -> Dict[str, Any]:
        """Check position risk against limits."""
        if metrics.portfolio_risk_percent > self.profile.max_position_risk:
            return {
                'passed': False,
                'reason': f"Position risk {metrics.portfolio_risk_percent:.1%} exceeds limit {self.profile.max_position_risk:.1%}",
                'details': f"Max loss ${metrics.max_loss:.2f} is too large for account"
            }
        
        return {'passed': True, 'reason': f'Position risk {metrics.portfolio_risk_percent:.1%} within limits'}
    
    def _check_portfolio_risk(
        self,
        metrics: RiskMetrics,
        account: Dict[str, Any],
        current_positions: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Check total portfolio risk."""
        # Calculate current portfolio risk
        current_risk = 0
        if current_positions:
            for pos in current_positions:
                current_risk += abs(pos.get('unrealized_pnl', 0))
        
        net_liquidation = account.get('net_liquidation', 1)
        current_risk_pct = current_risk / net_liquidation
        
        # Total risk with new position
        total_risk_pct = current_risk_pct + metrics.portfolio_risk_percent
        
        if total_risk_pct > self.profile.max_portfolio_risk:
            return {
                'passed': False,
                'reason': f"Total portfolio risk {total_risk_pct:.1%} would exceed limit {self.profile.max_portfolio_risk:.1%}",
                'details': f"Current risk: {current_risk_pct:.1%}, New position: {metrics.portfolio_risk_percent:.1%}"
            }
        
        return {
            'passed': True,
            'reason': f'Total portfolio risk {total_risk_pct:.1%} within limits'
        }
    
    def _check_buying_power(self, metrics: RiskMetrics, account: Dict[str, Any]) -> Dict[str, Any]:
        """Check buying power availability."""
        available_funds = account.get('available_funds', 0)
        
        if metrics.buying_power_required > available_funds:
            return {
                'passed': False,
                'reason': f"Insufficient buying power: need ${metrics.buying_power_required:.2f}, have ${available_funds:.2f}",
                'details': "Reduce position size or close other positions"
            }
        
        return {
            'passed': True,
            'reason': f'Sufficient buying power: ${available_funds:.2f} available'
        }
    
    def _check_margin(self, metrics: RiskMetrics, account: Dict[str, Any]) -> Dict[str, Any]:
        """Check margin requirements."""
        excess_liquidity = account.get('excess_liquidity', account.get('available_funds', 0))
        
        if metrics.margin_required > excess_liquidity:
            return {
                'passed': False,
                'reason': f"Insufficient margin: need ${metrics.margin_required:.2f}, have ${excess_liquidity:.2f}",
                'details': "Margin cushion too low"
            }
        
        # Check margin cushion ratio
        total_margin = account.get('maintenance_margin', 0) + metrics.margin_required
        net_liquidation = account.get('net_liquidation', 1)
        margin_ratio = total_margin / net_liquidation
        
        if margin_ratio > 0.5:  # Don't use more than 50% margin
            return {
                'passed': False,
                'reason': f"Margin usage {margin_ratio:.1%} would be too high",
                'details': "Keep margin usage below 50%"
            }
        
        return {
            'passed': True,
            'reason': f'Margin requirements met: ${excess_liquidity:.2f} available'
        }
    
    def _check_position_limits(self, current_positions: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Check position count limits."""
        position_count = len(current_positions) if current_positions else 0
        
        if position_count >= self.profile.max_positions:
            return {
                'passed': False,
                'reason': f"Position limit reached: {position_count}/{self.profile.max_positions}",
                'details': "Close existing positions before opening new ones"
            }
        
        return {
            'passed': True,
            'reason': f'Within position limits: {position_count}/{self.profile.max_positions}'
        }
    
    def _check_correlation_risk(
        self,
        strategy: Dict[str, Any],
        current_positions: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Check correlation risk with existing positions."""
        if not current_positions:
            return {'passed': True, 'reason': 'No correlation risk (no other positions)'}
        
        symbol = strategy.get('symbol')
        
        # Find correlation group
        symbol_group = None
        for group_name, symbols in self.correlation_groups.items():
            if symbol in symbols:
                symbol_group = group_name
                break
        
        if not symbol_group:
            return {'passed': True, 'reason': 'Symbol not in correlation groups'}
        
        # Check exposure to correlated positions
        correlated_symbols = self.correlation_groups[symbol_group]
        correlated_exposure = 0
        
        for pos in current_positions:
            if pos.get('symbol') in correlated_symbols:
                correlated_exposure += abs(pos.get('market_value', 0))
        
        # Add new position exposure
        correlated_exposure += strategy.get('max_loss', 0)
        
        # Check against limit (simplified - should use net liquidation)
        if correlated_exposure > 100000 * self.profile.max_correlation_risk:  # Placeholder
            return {
                'passed': False,
                'reason': f"Too much exposure to {symbol_group} sector",
                'details': f"Correlated exposure: ${correlated_exposure:.2f}"
            }
        
        return {
            'passed': True,
            'reason': f'Correlation risk acceptable for {symbol_group} sector'
        }
    
    def _check_risk_reward(self, metrics: RiskMetrics) -> Dict[str, Any]:
        """Check risk/reward ratio."""
        if metrics.risk_reward_ratio < self.profile.min_risk_reward:
            return {
                'passed': False,
                'reason': f"Risk/reward ratio {metrics.risk_reward_ratio:.2f} below minimum {self.profile.min_risk_reward}",
                'details': "Find better risk/reward opportunities"
            }
        
        return {
            'passed': True,
            'reason': f'Risk/reward ratio {metrics.risk_reward_ratio:.2f} acceptable'
        }
    
    def _check_stop_loss_requirement(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Check if stop loss is configured when required."""
        if self.profile.require_stop_loss:
            has_stop = strategy.get('stop_loss_price') is not None
            
            if not has_stop:
                return {
                    'passed': False,
                    'reason': 'Stop loss required but not configured',
                    'details': 'Set stop loss price before execution'
                }
        
        return {'passed': True, 'reason': 'Stop loss requirement met'}
    
    def calculate_position_size(
        self,
        account_value: float,
        max_loss_per_contract: float,
        risk_level: RiskLevel = RiskLevel.MODERATE
    ) -> int:
        """
        Calculate optimal position size based on risk.
        
        Args:
            account_value: Total account value
            max_loss_per_contract: Max loss for one contract
            risk_level: Risk level to use
            
        Returns:
            Number of contracts
        """
        if max_loss_per_contract <= 0:
            return 0
        
        # Calculate max risk amount
        max_risk = account_value * risk_level.value
        
        # Calculate position size
        position_size = int(max_risk / max_loss_per_contract)
        
        # Apply limits
        position_size = min(position_size, self.profile.level2_max_contracts)
        position_size = max(position_size, 1)
        
        logger.info(f"[RISK] Calculated position size: {position_size} contracts")
        return position_size
    
    def get_risk_summary(self, current_positions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Get current risk summary."""
        summary = {
            'profile': {
                'max_position_risk': f"{self.profile.max_position_risk:.1%}",
                'max_portfolio_risk': f"{self.profile.max_portfolio_risk:.1%}",
                'max_positions': self.profile.max_positions,
                'require_stop_loss': self.profile.require_stop_loss
            },
            'current_exposure': {}
        }
        
        if current_positions:
            total_risk = sum(abs(pos.get('unrealized_pnl', 0)) for pos in current_positions)
            summary['current_exposure'] = {
                'position_count': len(current_positions),
                'total_risk': total_risk,
                'positions_available': self.profile.max_positions - len(current_positions)
            }
        
        return summary