"""
Strategy Manager
Persistent strategy management with position linking
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import json
import uuid
import pickle
from pathlib import Path
from loguru import logger


@dataclass
class ManagedStrategy:
    """Complete strategy with all execution details."""
    strategy_id: str
    symbol: str
    strategy_type: str
    created_at: datetime
    expires_at: datetime
    
    # Strategy details
    legs: List[Dict[str, Any]]
    strikes: List[float]
    expiry: str
    quantity: int
    
    # Risk metrics
    max_loss: float
    max_profit: float
    breakeven: List[float]
    current_pnl: float = 0.0
    
    # Execution details
    order_ids: List[int] = None
    fill_prices: List[float] = None
    position_ids: List[str] = None
    
    # Stop loss configuration
    stop_loss_price: Optional[float] = None
    stop_loss_type: Optional[str] = None
    stop_order_ids: List[int] = None
    
    # Status
    status: str = "pending"  # pending, executing, active, closing, closed
    notes: List[str] = None
    
    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.order_ids is None:
            self.order_ids = []
        if self.fill_prices is None:
            self.fill_prices = []
        if self.position_ids is None:
            self.position_ids = []
        if self.stop_order_ids is None:
            self.stop_order_ids = []
        if self.notes is None:
            self.notes = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['expires_at'] = self.expires_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ManagedStrategy':
        """Create from dictionary."""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        return cls(**data)


class StrategyManager:
    """
    Manages strategy lifecycle with persistence and position linking.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize strategy manager.
        
        Args:
            storage_path: Optional path for persistent storage
        """
        self.active_strategies: Dict[str, ManagedStrategy] = {}
        self.position_to_strategy: Dict[str, str] = {}
        self.symbol_strategies: Dict[str, List[str]] = {}
        
        # Storage configuration
        self.storage_path = storage_path or Path.home() / '.sumppump' / 'strategies'
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Load persisted strategies
        self._load_strategies()
        
        logger.info(f"[STRATEGY_MGR] Initialized with {len(self.active_strategies)} active strategies")
    
    def create_strategy(
        self,
        symbol: str,
        strategy_type: str,
        legs: List[Dict[str, Any]],
        strikes: List[float],
        expiry: str,
        quantity: int,
        max_loss: float,
        max_profit: float,
        breakeven: List[float],
        ttl_minutes: int = 30
    ) -> str:
        """
        Create and save a new strategy.
        
        Args:
            symbol: Stock symbol
            strategy_type: Type of strategy
            legs: Strategy legs configuration
            strikes: Strike prices
            expiry: Option expiry date
            quantity: Number of contracts
            max_loss: Maximum potential loss
            max_profit: Maximum potential profit
            breakeven: Breakeven points
            ttl_minutes: Time to live in minutes
            
        Returns:
            Strategy ID
        """
        strategy_id = str(uuid.uuid4())
        
        strategy = ManagedStrategy(
            strategy_id=strategy_id,
            symbol=symbol,
            strategy_type=strategy_type,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=ttl_minutes),
            legs=legs,
            strikes=strikes,
            expiry=expiry,
            quantity=quantity,
            max_loss=max_loss,
            max_profit=max_profit,
            breakeven=breakeven
        )
        
        # Store strategy
        self.active_strategies[strategy_id] = strategy
        
        # Index by symbol
        if symbol not in self.symbol_strategies:
            self.symbol_strategies[symbol] = []
        self.symbol_strategies[symbol].append(strategy_id)
        
        # Persist
        self._save_strategy(strategy)
        
        logger.info(f"[STRATEGY_MGR] Created strategy {strategy_id} for {symbol} ({strategy_type})")
        return strategy_id
    
    def get_strategy(self, strategy_id: str) -> Optional[ManagedStrategy]:
        """Get strategy by ID."""
        strategy = self.active_strategies.get(strategy_id)
        
        if strategy and strategy.expires_at < datetime.now():
            logger.warning(f"[STRATEGY_MGR] Strategy {strategy_id} has expired")
            self.expire_strategy(strategy_id)
            return None
        
        return strategy
    
    def get_strategies_by_symbol(self, symbol: str) -> List[ManagedStrategy]:
        """Get all active strategies for a symbol."""
        strategy_ids = self.symbol_strategies.get(symbol, [])
        strategies = []
        
        for sid in strategy_ids:
            strategy = self.get_strategy(sid)
            if strategy:
                strategies.append(strategy)
        
        return strategies
    
    def link_position_to_strategy(
        self,
        position_id: str,
        strategy_id: str,
        order_id: Optional[int] = None,
        fill_price: Optional[float] = None
    ) -> bool:
        """
        Link a position to its strategy.
        
        Args:
            position_id: Position identifier
            strategy_id: Strategy ID
            order_id: Optional order ID
            fill_price: Optional fill price
            
        Returns:
            True if successful
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            logger.error(f"[STRATEGY_MGR] Strategy {strategy_id} not found")
            return False
        
        # Link position
        self.position_to_strategy[position_id] = strategy_id
        
        # Update strategy
        if position_id not in strategy.position_ids:
            strategy.position_ids.append(position_id)
        
        if order_id and order_id not in strategy.order_ids:
            strategy.order_ids.append(order_id)
        
        if fill_price:
            strategy.fill_prices.append(fill_price)
        
        # Update status
        if strategy.status == "pending":
            strategy.status = "executing"
        elif strategy.status == "executing" and len(strategy.fill_prices) == len(strategy.legs):
            strategy.status = "active"
        
        # Persist changes
        self._save_strategy(strategy)
        
        logger.info(f"[STRATEGY_MGR] Linked position {position_id} to strategy {strategy_id}")
        return True
    
    def get_strategy_by_position(self, position_id: str) -> Optional[ManagedStrategy]:
        """Get strategy associated with a position."""
        strategy_id = self.position_to_strategy.get(position_id)
        if strategy_id:
            return self.get_strategy(strategy_id)
        return None
    
    def update_strategy_pnl(self, strategy_id: str, current_pnl: float) -> bool:
        """Update strategy P&L."""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        
        strategy.current_pnl = current_pnl
        strategy.notes.append(f"P&L updated: ${current_pnl:.2f} at {datetime.now().strftime('%H:%M:%S')}")
        
        self._save_strategy(strategy)
        return True
    
    def set_stop_loss(
        self,
        strategy_id: str,
        stop_price: float,
        stop_type: str = "underlying",
        order_ids: Optional[List[int]] = None
    ) -> bool:
        """
        Set stop loss for a strategy.
        
        Args:
            strategy_id: Strategy ID
            stop_price: Stop trigger price
            stop_type: Type of stop (underlying, option, delta)
            order_ids: Stop order IDs if placed
            
        Returns:
            True if successful
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        
        strategy.stop_loss_price = stop_price
        strategy.stop_loss_type = stop_type
        
        if order_ids:
            strategy.stop_order_ids.extend(order_ids)
        
        strategy.notes.append(f"Stop loss set at {stop_price} ({stop_type})")
        
        self._save_strategy(strategy)
        
        logger.info(f"[STRATEGY_MGR] Set stop loss for {strategy_id} at {stop_price}")
        return True
    
    def close_strategy(self, strategy_id: str, reason: str = "manual") -> bool:
        """Mark strategy as closed."""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        
        strategy.status = "closed"
        strategy.notes.append(f"Closed: {reason} at {datetime.now().isoformat()}")
        
        # Remove from active
        del self.active_strategies[strategy_id]
        
        # Remove position links
        positions_to_remove = [
            pid for pid, sid in self.position_to_strategy.items()
            if sid == strategy_id
        ]
        for pid in positions_to_remove:
            del self.position_to_strategy[pid]
        
        # Archive strategy
        self._archive_strategy(strategy)
        
        logger.info(f"[STRATEGY_MGR] Closed strategy {strategy_id}: {reason}")
        return True
    
    def expire_strategy(self, strategy_id: str) -> bool:
        """Expire a strategy that has exceeded TTL."""
        return self.close_strategy(strategy_id, "expired")
    
    def cleanup_expired(self) -> int:
        """Remove all expired strategies."""
        expired = []
        for sid, strategy in self.active_strategies.items():
            if strategy.expires_at < datetime.now():
                expired.append(sid)
        
        for sid in expired:
            self.expire_strategy(sid)
        
        if expired:
            logger.info(f"[STRATEGY_MGR] Cleaned up {len(expired)} expired strategies")
        
        return len(expired)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get manager summary."""
        self.cleanup_expired()
        
        return {
            "active_strategies": len(self.active_strategies),
            "linked_positions": len(self.position_to_strategy),
            "by_symbol": {
                symbol: len(self.get_strategies_by_symbol(symbol))
                for symbol in self.symbol_strategies
            },
            "by_status": self._count_by_status(),
            "total_pnl": sum(s.current_pnl for s in self.active_strategies.values())
        }
    
    def _count_by_status(self) -> Dict[str, int]:
        """Count strategies by status."""
        counts = {}
        for strategy in self.active_strategies.values():
            counts[strategy.status] = counts.get(strategy.status, 0) + 1
        return counts
    
    def _save_strategy(self, strategy: ManagedStrategy):
        """Persist strategy to disk."""
        try:
            file_path = self.storage_path / f"{strategy.strategy_id}.json"
            with open(file_path, 'w') as f:
                json.dump(strategy.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"[STRATEGY_MGR] Failed to save strategy: {e}")
    
    def _archive_strategy(self, strategy: ManagedStrategy):
        """Archive closed strategy."""
        try:
            # Move to archive folder
            archive_path = self.storage_path / 'archive'
            archive_path.mkdir(exist_ok=True)
            
            old_path = self.storage_path / f"{strategy.strategy_id}.json"
            new_path = archive_path / f"{strategy.strategy_id}.json"
            
            if old_path.exists():
                old_path.rename(new_path)
            else:
                # Save directly to archive
                with open(new_path, 'w') as f:
                    json.dump(strategy.to_dict(), f, indent=2)
                    
        except Exception as e:
            logger.error(f"[STRATEGY_MGR] Failed to archive strategy: {e}")
    
    def _load_strategies(self):
        """Load persisted strategies from disk."""
        try:
            # Load active strategies
            for file_path in self.storage_path.glob("*.json"):
                if file_path.stem == "archive":
                    continue
                    
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    
                    strategy = ManagedStrategy.from_dict(data)
                    
                    # Skip expired
                    if strategy.expires_at < datetime.now():
                        self._archive_strategy(strategy)
                        continue
                    
                    # Restore strategy
                    self.active_strategies[strategy.strategy_id] = strategy
                    
                    # Restore indexes
                    if strategy.symbol not in self.symbol_strategies:
                        self.symbol_strategies[strategy.symbol] = []
                    self.symbol_strategies[strategy.symbol].append(strategy.strategy_id)
                    
                    # Restore position links
                    for pid in strategy.position_ids:
                        self.position_to_strategy[pid] = strategy.strategy_id
                        
                except Exception as e:
                    logger.error(f"[STRATEGY_MGR] Failed to load {file_path}: {e}")
                    
        except Exception as e:
            logger.error(f"[STRATEGY_MGR] Failed to load strategies: {e}")


# Global instance
_strategy_manager: Optional[StrategyManager] = None


def get_strategy_manager() -> StrategyManager:
    """Get or create the global strategy manager."""
    global _strategy_manager
    if _strategy_manager is None:
        _strategy_manager = StrategyManager()
    return _strategy_manager