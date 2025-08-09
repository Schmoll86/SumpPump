"""
Enhanced SessionState with audit trail functionality.
This can be integrated into the existing SessionState class in server.py
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class AuditEntry:
    """Structured audit trail entry."""
    timestamp: datetime
    action: str
    details: Dict[str, Any]
    session_id: str
    user: str = 'claude_desktop'
    severity: str = 'INFO'  # INFO, WARNING, ERROR, CRITICAL
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'action': self.action,
            'details': self.details,
            'session_id': self.session_id,
            'user': self.user,
            'severity': self.severity
        }


class EnhancedSessionState:
    """
    Enhanced session state management with comprehensive audit trail.
    Maintains backward compatibility while adding new features.
    """
    
    def __init__(self):
        """Initialize enhanced session state."""
        # Legacy state (for backward compatibility)
        self.current_strategy = None
        self.current_strategy_dict = None
        self.current_symbol = None
        self.last_calculated = None
        
        # New architecture components
        self.trading_session = None
        self.strategy_manager = None
        self.risk_framework = None
        self.active_pipelines = {}
        
        # Audit trail components
        self.audit_trail: List[AuditEntry] = []
        self.session_id = f"SESSION_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{id(self)}"
        self.audit_file = Path(f"/tmp/sump_audit_{datetime.now().strftime('%Y%m%d')}.jsonl")
        self.audit_enabled = True
        self.max_audit_entries = 1000  # Prevent memory issues
        
        # Session metrics
        self.session_start = datetime.now()
        self.total_calculations = 0
        self.total_executions = 0
        self.total_errors = 0
        
        # Initialize audit file
        self._initialize_audit_file()
        
        # Log session start
        self.add_audit_entry(
            action='session_started',
            details={'session_id': self.session_id}
        )
    
    def _initialize_audit_file(self):
        """Create or verify audit file exists."""
        try:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.audit_file.exists():
                self.audit_file.touch()
                logger.info(f"[AUDIT] Created audit file: {self.audit_file}")
        except Exception as e:
            logger.error(f"[AUDIT] Failed to initialize audit file: {e}")
            self.audit_enabled = False
    
    def add_audit_entry(
        self,
        action: str,
        details: Dict[str, Any],
        severity: str = 'INFO'
    ) -> Optional[AuditEntry]:
        """
        Add an entry to the audit trail.
        
        Args:
            action: Action being audited
            details: Details of the action
            severity: Severity level
            
        Returns:
            The created audit entry, or None if audit is disabled
        """
        if not self.audit_enabled:
            return None
        
        try:
            # Create audit entry
            entry = AuditEntry(
                timestamp=datetime.now(),
                action=action,
                details=details,
                session_id=self.session_id,
                severity=severity
            )
            
            # Add to memory trail (with size limit)
            self.audit_trail.append(entry)
            if len(self.audit_trail) > self.max_audit_entries:
                self.audit_trail.pop(0)  # Remove oldest
            
            # Persist to file
            self._write_audit_entry(entry)
            
            # Update metrics
            if 'calculate' in action.lower():
                self.total_calculations += 1
            elif 'execute' in action.lower():
                self.total_executions += 1
            elif severity in ['ERROR', 'CRITICAL']:
                self.total_errors += 1
            
            logger.debug(f"[AUDIT] {action}: {details.get('symbol', 'N/A')}")
            return entry
            
        except Exception as e:
            logger.error(f"[AUDIT] Failed to add audit entry: {e}")
            return None
    
    def _write_audit_entry(self, entry: AuditEntry):
        """Write audit entry to file."""
        try:
            with open(self.audit_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"[AUDIT] Failed to write to file: {e}")
    
    def save_strategy(self, strategy_obj, strategy_dict, symbol):
        """
        Save calculated strategy with comprehensive audit.
        Maintains backward compatibility.
        """
        # Original functionality
        self.current_strategy = strategy_obj
        self.current_strategy_dict = strategy_dict
        self.current_symbol = symbol
        self.last_calculated = datetime.now()
        
        # Audit the strategy save
        self.add_audit_entry(
            action='strategy_calculated',
            details={
                'symbol': symbol,
                'strategy_type': strategy_dict.get('strategy_type'),
                'strategy_id': strategy_dict.get('strategy_id'),
                'max_loss': strategy_dict.get('max_loss_raw'),
                'max_profit': strategy_dict.get('max_profit_raw'),
                'breakeven': strategy_dict.get('analysis', {}).get('breakeven_points', []),
                'strikes': strategy_dict.get('strikes', []),
                'expiry': strategy_dict.get('expiry')
            }
        )
        
        # Save to strategy manager if available
        if self.strategy_manager and 'strategy_id' in strategy_dict:
            try:
                self.strategy_manager.create_strategy(
                    symbol=symbol,
                    strategy_type=strategy_dict.get('strategy_type'),
                    legs=strategy_dict.get('legs', []),
                    strikes=strategy_dict.get('strikes', []),
                    expiry=strategy_dict.get('expiry'),
                    quantity=strategy_dict.get('quantity', 1),
                    max_loss=strategy_dict.get('max_loss_raw', 0),
                    max_profit=strategy_dict.get('max_profit_raw', 0),
                    breakeven=strategy_dict.get('analysis', {}).get('breakeven_points', [])
                )
                logger.info(f"[SESSION] Strategy {strategy_dict['strategy_id']} saved to manager")
            except Exception as e:
                logger.error(f"[SESSION] Failed to save to strategy manager: {e}")
                self.add_audit_entry(
                    action='strategy_save_failed',
                    details={'error': str(e)},
                    severity='ERROR'
                )
    
    def get_strategy(self, strategy_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve a strategy with audit logging.
        
        Args:
            strategy_id: Strategy ID to retrieve, or None for current
            
        Returns:
            Strategy dictionary or None
        """
        if strategy_id and self.strategy_manager:
            strategy = self.strategy_manager.get_strategy(strategy_id)
            if strategy:
                self.add_audit_entry(
                    action='strategy_retrieved',
                    details={'strategy_id': strategy_id}
                )
                return strategy
        
        # Return current strategy if no ID specified
        if self.current_strategy_dict:
            self.add_audit_entry(
                action='current_strategy_retrieved',
                details={'symbol': self.current_symbol}
            )
            return self.current_strategy_dict
        
        return None
    
    def log_execution(
        self,
        function_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any]
    ):
        """
        Log execution attempt with result.
        
        Args:
            function_name: Name of executed function
            params: Parameters passed
            result: Execution result
        """
        severity = 'ERROR' if result.get('status') == 'error' else 'INFO'
        
        self.add_audit_entry(
            action=f'execution_{function_name}',
            details={
                'params': params,
                'result_status': result.get('status'),
                'order_id': result.get('order_id'),
                'error': result.get('error')
            },
            severity=severity
        )
    
    def log_risk_validation(
        self,
        validation_type: str,
        passed: bool,
        details: Dict[str, Any]
    ):
        """
        Log risk validation results.
        
        Args:
            validation_type: Type of validation performed
            passed: Whether validation passed
            details: Validation details
        """
        self.add_audit_entry(
            action=f'risk_validation_{validation_type}',
            details={
                'passed': passed,
                **details
            },
            severity='INFO' if passed else 'WARNING'
        )
    
    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive session summary.
        
        Returns:
            Session statistics and recent activity
        """
        session_duration = datetime.now() - self.session_start
        
        return {
            'session_id': self.session_id,
            'start_time': self.session_start.isoformat(),
            'duration_minutes': int(session_duration.total_seconds() / 60),
            'total_calculations': self.total_calculations,
            'total_executions': self.total_executions,
            'total_errors': self.total_errors,
            'current_symbol': self.current_symbol,
            'current_strategy': self.current_strategy_dict.get('strategy_type') 
                               if self.current_strategy_dict else None,
            'audit_entries_count': len(self.audit_trail),
            'recent_actions': [
                entry.to_dict() for entry in self.audit_trail[-10:]
            ]
        }
    
    def export_audit_trail(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        severity_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Export filtered audit trail.
        
        Args:
            start_time: Filter entries after this time
            end_time: Filter entries before this time
            severity_filter: Filter by severity level
            
        Returns:
            List of filtered audit entries
        """
        entries = []
        
        try:
            # Read from file for complete history
            with open(self.audit_file, 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        
                        # Apply filters
                        entry_time = datetime.fromisoformat(entry['timestamp'])
                        
                        if start_time and entry_time < start_time:
                            continue
                        if end_time and entry_time > end_time:
                            continue
                        if severity_filter and entry.get('severity') != severity_filter:
                            continue
                        
                        entries.append(entry)
            
            logger.info(f"[AUDIT] Exported {len(entries)} audit entries")
            
        except Exception as e:
            logger.error(f"[AUDIT] Failed to export audit trail: {e}")
            # Fall back to in-memory trail
            entries = [
                entry.to_dict() for entry in self.audit_trail
                if (not start_time or entry.timestamp >= start_time) and
                   (not end_time or entry.timestamp <= end_time) and
                   (not severity_filter or entry.severity == severity_filter)
            ]
        
        return entries
    
    def cleanup_old_audits(self, days_to_keep: int = 7):
        """
        Clean up old audit files.
        
        Args:
            days_to_keep: Number of days of audit files to keep
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            audit_dir = self.audit_file.parent
            
            for audit_file in audit_dir.glob("sump_audit_*.jsonl"):
                # Parse date from filename
                try:
                    date_str = audit_file.stem.split('_')[-1]
                    file_date = datetime.strptime(date_str, '%Y%m%d')
                    
                    if file_date < cutoff_date:
                        audit_file.unlink()
                        logger.info(f"[AUDIT] Removed old audit file: {audit_file}")
                        
                except Exception as e:
                    logger.warning(f"[AUDIT] Could not parse date from {audit_file}: {e}")
            
        except Exception as e:
            logger.error(f"[AUDIT] Failed to cleanup old audits: {e}")
    
    def __del__(self):
        """Cleanup on session end."""
        if hasattr(self, 'audit_enabled') and self.audit_enabled:
            self.add_audit_entry(
                action='session_ended',
                details=self.get_session_summary()
            )


# Example integration with existing SessionState
def enhance_existing_session_state(existing_session):
    """
    Enhance an existing SessionState instance with audit functionality.
    
    Args:
        existing_session: Existing SessionState instance
        
    Returns:
        Enhanced session with audit capabilities
    """
    # Copy existing attributes
    enhanced = EnhancedSessionState()
    
    # Preserve existing state
    if hasattr(existing_session, 'current_strategy'):
        enhanced.current_strategy = existing_session.current_strategy
    if hasattr(existing_session, 'current_strategy_dict'):
        enhanced.current_strategy_dict = existing_session.current_strategy_dict
    if hasattr(existing_session, 'current_symbol'):
        enhanced.current_symbol = existing_session.current_symbol
    if hasattr(existing_session, 'trading_session'):
        enhanced.trading_session = existing_session.trading_session
    if hasattr(existing_session, 'strategy_manager'):
        enhanced.strategy_manager = existing_session.strategy_manager
    
    logger.info(f"[SESSION] Enhanced session state initialized: {enhanced.session_id}")
    
    return enhanced


if __name__ == "__main__":
    # Test the enhanced session state
    session = EnhancedSessionState()
    
    # Test audit entries
    session.add_audit_entry(
        action='test_calculation',
        details={'symbol': 'SPY', 'strategy': 'vertical_spread'}
    )
    
    session.add_audit_entry(
        action='test_execution',
        details={'symbol': 'SPY', 'order_id': 12345},
        severity='WARNING'
    )
    
    # Get summary
    summary = session.get_session_summary()
    print(f"Session Summary: {json.dumps(summary, indent=2)}")
    
    # Export audit trail
    audit_trail = session.export_audit_trail()
    print(f"Audit Trail ({len(audit_trail)} entries):")
    for entry in audit_trail:
        print(f"  - {entry['timestamp']}: {entry['action']}")
    
    # Cleanup old audits
    session.cleanup_old_audits(days_to_keep=7)