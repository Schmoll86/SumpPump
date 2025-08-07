"""
Trading Session State Machine
Manages the complete lifecycle of a trading session with proper state transitions
"""

import asyncio
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
import json
import uuid


class SessionState(Enum):
    """Trading session states with enforced workflow."""
    IDLE = "idle"
    ANALYZING = "analyzing"
    STRATEGY_SELECTED = "strategy_selected"
    RISK_VALIDATED = "risk_validated"
    EXECUTING = "executing"
    FILLS_CONFIRMED = "fills_confirmed"
    STOPS_PLACED = "stops_placed"
    MONITORING = "monitoring"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class SessionContext:
    """Complete context for a trading session."""
    session_id: str
    symbol: str
    created_at: datetime
    updated_at: datetime
    
    # Analysis data
    news_analysis: Optional[Dict[str, Any]] = None
    volatility_analysis: Optional[Dict[str, Any]] = None
    options_chain: Optional[Dict[str, Any]] = None
    
    # Strategy data
    strategy: Optional[Dict[str, Any]] = None
    strategy_id: Optional[str] = None
    calculated_pnl: Optional[Dict[str, Any]] = None
    
    # Risk validation
    risk_check: Optional[Dict[str, Any]] = None
    account_snapshot: Optional[Dict[str, Any]] = None
    
    # Execution data
    orders: List[Dict[str, Any]] = field(default_factory=list)
    fills: List[Dict[str, Any]] = field(default_factory=list)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Stop loss data
    stop_orders: List[Dict[str, Any]] = field(default_factory=list)
    conditional_orders: List[Dict[str, Any]] = field(default_factory=list)
    
    # Monitoring data
    performance_metrics: Optional[Dict[str, Any]] = None
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Audit trail
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


class TradingSession:
    """
    Manages the complete lifecycle of a trading session.
    Enforces proper workflow and state transitions.
    """
    
    # Valid state transitions
    TRANSITIONS = {
        SessionState.IDLE: [SessionState.ANALYZING],
        SessionState.ANALYZING: [SessionState.STRATEGY_SELECTED, SessionState.ERROR],
        SessionState.STRATEGY_SELECTED: [SessionState.RISK_VALIDATED, SessionState.ANALYZING, SessionState.ERROR],
        SessionState.RISK_VALIDATED: [SessionState.EXECUTING, SessionState.STRATEGY_SELECTED, SessionState.ERROR],
        SessionState.EXECUTING: [SessionState.FILLS_CONFIRMED, SessionState.ERROR],
        SessionState.FILLS_CONFIRMED: [SessionState.STOPS_PLACED, SessionState.ERROR],
        SessionState.STOPS_PLACED: [SessionState.MONITORING, SessionState.ERROR],
        SessionState.MONITORING: [SessionState.CLOSED, SessionState.ERROR],
        SessionState.CLOSED: [],
        SessionState.ERROR: [SessionState.IDLE, SessionState.CLOSED]
    }
    
    def __init__(self, symbol: str, session_id: Optional[str] = None):
        """Initialize a new trading session."""
        self.session_id = session_id or str(uuid.uuid4())
        self.state = SessionState.IDLE
        self.context = SessionContext(
            session_id=self.session_id,
            symbol=symbol,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self._lock = asyncio.Lock()
        
        logger.info(f"[SESSION] Created new session {self.session_id} for {symbol}")
        self._add_audit_entry("session_created", {"symbol": symbol})
    
    async def transition(self, new_state: SessionState, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Transition to a new state if valid.
        
        Args:
            new_state: Target state
            data: Optional data to store with transition
            
        Returns:
            True if transition successful, False otherwise
        """
        async with self._lock:
            # Check if transition is valid
            if new_state not in self.TRANSITIONS[self.state]:
                logger.error(f"[SESSION] Invalid transition: {self.state.value} → {new_state.value}")
                self._add_audit_entry("invalid_transition", {
                    "from": self.state.value,
                    "to": new_state.value,
                    "rejected": True
                })
                return False
            
            # Log transition
            logger.info(f"[SESSION] State transition: {self.state.value} → {new_state.value}")
            self._add_audit_entry("state_transition", {
                "from": self.state.value,
                "to": new_state.value,
                "data": data
            })
            
            # Update state
            old_state = self.state
            self.state = new_state
            self.context.updated_at = datetime.now()
            
            # Store transition data
            if data:
                self._store_transition_data(new_state, data)
            
            # Trigger state-specific actions
            await self._on_state_change(old_state, new_state)
            
            return True
    
    def _store_transition_data(self, state: SessionState, data: Dict[str, Any]):
        """Store data associated with state transition."""
        if state == SessionState.ANALYZING:
            if 'news' in data:
                self.context.news_analysis = data['news']
            if 'volatility' in data:
                self.context.volatility_analysis = data['volatility']
            if 'options_chain' in data:
                self.context.options_chain = data['options_chain']
        
        elif state == SessionState.STRATEGY_SELECTED:
            self.context.strategy = data.get('strategy')
            self.context.strategy_id = data.get('strategy_id')
            self.context.calculated_pnl = data.get('pnl_profile')
        
        elif state == SessionState.RISK_VALIDATED:
            self.context.risk_check = data.get('risk_check')
            self.context.account_snapshot = data.get('account_snapshot')
        
        elif state == SessionState.FILLS_CONFIRMED:
            if 'orders' in data:
                self.context.orders.extend(data['orders'])
            if 'fills' in data:
                self.context.fills.extend(data['fills'])
            if 'positions' in data:
                self.context.positions = data['positions']
        
        elif state == SessionState.STOPS_PLACED:
            if 'stop_orders' in data:
                self.context.stop_orders.extend(data['stop_orders'])
            if 'conditional_orders' in data:
                self.context.conditional_orders.extend(data['conditional_orders'])
    
    async def _on_state_change(self, old_state: SessionState, new_state: SessionState):
        """Handle state-specific actions on transition."""
        if new_state == SessionState.ERROR:
            # Log error details
            logger.error(f"[SESSION] Session entered ERROR state from {old_state.value}")
            # Could trigger alerts here
        
        elif new_state == SessionState.MONITORING:
            # Start monitoring tasks
            logger.info("[SESSION] Starting position monitoring")
            # Could start background monitoring here
        
        elif new_state == SessionState.CLOSED:
            # Clean up session
            logger.info(f"[SESSION] Session {self.session_id} closed")
            # Could archive session data here
    
    def _add_audit_entry(self, event_type: str, data: Dict[str, Any]):
        """Add entry to audit trail."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "state": self.state.value,
            "data": data
        }
        self.context.audit_trail.append(entry)
    
    def add_error(self, error_type: str, error_details: Any):
        """Record an error in the session."""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": error_type,
            "details": str(error_details),
            "state": self.state.value
        }
        self.context.errors.append(error_entry)
        logger.error(f"[SESSION] Error recorded: {error_type}")
    
    def validate_prerequisites(self, target_state: SessionState) -> tuple[bool, str]:
        """
        Validate that prerequisites for a state transition are met.
        
        Returns:
            (is_valid, error_message)
        """
        if target_state == SessionState.STRATEGY_SELECTED:
            # Must have analysis data
            if not self.context.news_analysis and not self.context.volatility_analysis:
                return False, "Cannot select strategy without market analysis"
            if not self.context.options_chain:
                return False, "Cannot select strategy without options chain data"
        
        elif target_state == SessionState.RISK_VALIDATED:
            # Must have strategy
            if not self.context.strategy:
                return False, "Cannot validate risk without selected strategy"
        
        elif target_state == SessionState.EXECUTING:
            # Must have risk validation
            if not self.context.risk_check:
                return False, "Cannot execute without risk validation"
            if self.context.risk_check.get('approved') is False:
                return False, "Risk check failed - cannot execute"
        
        elif target_state == SessionState.STOPS_PLACED:
            # Must have confirmed fills
            if not self.context.fills:
                return False, "Cannot place stops without confirmed fills"
        
        return True, ""
    
    def get_current_state(self) -> Dict[str, Any]:
        """Get current session state and context summary."""
        return {
            "session_id": self.session_id,
            "symbol": self.context.symbol,
            "state": self.state.value,
            "created_at": self.context.created_at.isoformat(),
            "updated_at": self.context.updated_at.isoformat(),
            "has_analysis": bool(self.context.news_analysis or self.context.volatility_analysis),
            "has_strategy": bool(self.context.strategy),
            "has_risk_check": bool(self.context.risk_check),
            "order_count": len(self.context.orders),
            "fill_count": len(self.context.fills),
            "stop_count": len(self.context.stop_orders),
            "error_count": len(self.context.errors),
            "audit_entries": len(self.context.audit_trail)
        }
    
    def export_session(self) -> Dict[str, Any]:
        """Export complete session data for persistence."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "context": {
                "symbol": self.context.symbol,
                "created_at": self.context.created_at.isoformat(),
                "updated_at": self.context.updated_at.isoformat(),
                "news_analysis": self.context.news_analysis,
                "volatility_analysis": self.context.volatility_analysis,
                "options_chain": self.context.options_chain,
                "strategy": self.context.strategy,
                "strategy_id": self.context.strategy_id,
                "calculated_pnl": self.context.calculated_pnl,
                "risk_check": self.context.risk_check,
                "account_snapshot": self.context.account_snapshot,
                "orders": self.context.orders,
                "fills": self.context.fills,
                "positions": self.context.positions,
                "stop_orders": self.context.stop_orders,
                "conditional_orders": self.context.conditional_orders,
                "performance_metrics": self.context.performance_metrics,
                "alerts": self.context.alerts,
                "audit_trail": self.context.audit_trail,
                "errors": self.context.errors
            }
        }
    
    @classmethod
    def import_session(cls, data: Dict[str, Any]) -> 'TradingSession':
        """Import session from exported data."""
        session = cls(data['context']['symbol'], data['session_id'])
        session.state = SessionState(data['state'])
        
        # Restore context
        ctx = data['context']
        session.context = SessionContext(
            session_id=data['session_id'],
            symbol=ctx['symbol'],
            created_at=datetime.fromisoformat(ctx['created_at']),
            updated_at=datetime.fromisoformat(ctx['updated_at']),
            news_analysis=ctx.get('news_analysis'),
            volatility_analysis=ctx.get('volatility_analysis'),
            options_chain=ctx.get('options_chain'),
            strategy=ctx.get('strategy'),
            strategy_id=ctx.get('strategy_id'),
            calculated_pnl=ctx.get('calculated_pnl'),
            risk_check=ctx.get('risk_check'),
            account_snapshot=ctx.get('account_snapshot'),
            orders=ctx.get('orders', []),
            fills=ctx.get('fills', []),
            positions=ctx.get('positions', []),
            stop_orders=ctx.get('stop_orders', []),
            conditional_orders=ctx.get('conditional_orders', []),
            performance_metrics=ctx.get('performance_metrics'),
            alerts=ctx.get('alerts', []),
            audit_trail=ctx.get('audit_trail', []),
            errors=ctx.get('errors', [])
        )
        
        logger.info(f"[SESSION] Imported session {session.session_id} in state {session.state.value}")
        return session