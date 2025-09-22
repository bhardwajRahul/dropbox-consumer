"""
State management module for Dropbox Consumer.

Handles persistent state storage for file tracking and duplicate prevention.
"""

import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from .config import config
from .logging_setup import get_logger

logger = get_logger(__name__)


class StateManager:
    """Manages persistent state for file tracking."""
    
    def __init__(self):
        self.startup_time = time.time()
        self.initial_snapshot: Dict[str, Any] = {}
        self.last_copied_hash: Dict[str, str] = {}
        self.lock = threading.Lock()
        
        # State file paths
        self.snapshot_file = config.STATE_DIR / "initial_snapshot.json"
        self.hash_cache_file = config.STATE_DIR / "hash_cache.json"
    
    def ensure_state_dir(self):
        """Create state directory and verify it's writable."""
        try:
            config.STATE_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"State directory initialized: {config.STATE_DIR}")
            
            # Test write permissions
            test_file = config.STATE_DIR / "__test_write__"
            try:
                with test_file.open('w') as f:
                    f.write('test')
                test_file.unlink()
                logger.info(f"State directory is writable: {config.STATE_DIR}")
            except Exception as e:
                logger.error(f"State directory is not writable: {config.STATE_DIR} ({e})")
        except Exception as e:
            logger.warning(f"Could not create state directory {config.STATE_DIR}: {e}")
            logger.warning("Running without persistent state - data will be lost on restart")
    
    def load_state(self):
        """Load persistent state from files."""
        with self.lock:
            self._load_snapshot()
            self._load_hash_cache()
            self._cleanup_old_state()
    
    def _load_snapshot(self):
        """Load initial snapshot from file."""
        if self.snapshot_file.exists():
            try:
                with self.snapshot_file.open('r') as f:
                    data = json.load(f)
                    self.initial_snapshot = data.get('data', {})
                    logger.info(f"Loaded previous snapshot: {len(self.initial_snapshot)} files")
            except Exception as e:
                logger.warning(f"Could not load snapshot: {e}")
    
    def _load_hash_cache(self):
        """Load hash cache from file."""
        if self.hash_cache_file.exists():
            try:
                with self.hash_cache_file.open('r') as f:
                    data = json.load(f)
                    self.last_copied_hash = data.get('data', {})
                    logger.info(f"Loaded hash cache: {len(self.last_copied_hash)} files")
            except Exception as e:
                logger.warning(f"Could not load hash cache: {e}")
    
    def save_state(self):
        """Save current state to files."""
        if not config.STATE_DIR.exists():
            logger.error(f"State directory does not exist: {config.STATE_DIR}")
            return
        
        with self.lock:
            try:
                # Save initial snapshot
                snapshot_data = {
                    'timestamp': self.startup_time,
                    'data': self.initial_snapshot
                }
                with self.snapshot_file.open('w') as f:
                    json.dump(snapshot_data, f, indent=2)
                logger.debug(f"Wrote snapshot file: {self.snapshot_file}")
                
                # Save hash cache
                hash_data = {
                    'timestamp': time.time(),
                    'data': self.last_copied_hash
                }
                with self.hash_cache_file.open('w') as f:
                    json.dump(hash_data, f, indent=2)
                logger.debug(f"Wrote hash cache file: {self.hash_cache_file}")
                
                logger.debug("State saved successfully")
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
    
    def _cleanup_old_state(self):
        """Remove old entries from state files."""
        if config.STATE_CLEANUP_DAYS <= 0:
            return
        
        cutoff_time = time.time() - (config.STATE_CLEANUP_DAYS * 24 * 3600)
        
        # Clean up hash cache
        old_count = len(self.last_copied_hash)
        for file_path in list(self.last_copied_hash.keys()):
            try:
                if not Path(file_path).exists():
                    del self.last_copied_hash[file_path]
            except Exception:
                del self.last_copied_hash[file_path]
        
        new_count = len(self.last_copied_hash)
        if old_count != new_count:
            logger.info(f"Cleaned up {old_count - new_count} stale hash cache entries")
    
    def save_state_periodically(self):
        """Save state every 5 minutes to prevent data loss."""
        while True:
            time.sleep(300)  # 5 minutes
            self.save_state()
    
    def is_file_in_snapshot(self, path: Path) -> bool:
        """Check if file was present at startup."""
        key = str(path)
        return key in self.initial_snapshot
    
    def add_to_snapshot(self, path: Path):
        """Add file to initial snapshot."""
        try:
            stat = path.stat()
            key = str(path)
            self.initial_snapshot[key] = [stat.st_size, stat.st_mtime, stat.st_ino]
        except Exception as e:
            logger.debug(f"Could not add {path} to snapshot: {e}")
    
    def get_cached_hash(self, path: Path) -> Optional[str]:
        """Get cached hash for file."""
        return self.last_copied_hash.get(str(path))
    
    def set_cached_hash(self, path: Path, hash_value: str):
        """Set cached hash for file."""
        self.last_copied_hash[str(path)] = hash_value


# Global state manager instance
state_manager = StateManager()