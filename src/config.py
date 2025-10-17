"""
Configuration module for Dropbox Consumer.

Handles all environment variable parsing and configuration validation.
"""

import os
from pathlib import Path


class Config:
    """Configuration settings loaded from environment variables."""
    
    def __init__(self):
        # Core paths
        self.SOURCE = Path(os.environ.get("SOURCE", "/source")).resolve()
        self.DEST = Path(os.environ.get("DEST", "/consume")).resolve()
        self.STATE_DIR = Path(os.environ.get("STATE_DIR", "/app/state")).resolve()
        
        # File monitoring settings
        self.RECURSIVE = self._parse_bool(os.environ.get("RECURSIVE", "true"))
        self.DEBOUNCE_SECONDS = float(os.environ.get("DEBOUNCE_SECONDS", "1.0"))
        self.STABILITY_CHECK_INTERVAL = float(os.environ.get("STABILITY_INTERVAL", "0.5"))
        self.STABILITY_STABLE_ROUNDS = int(os.environ.get("STABILITY_STABLE_ROUNDS", "2"))
        self.COPY_TIMEOUT = int(os.environ.get("COPY_TIMEOUT", "60"))
        self.MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
        
        # Directory handling
        self.PRESERVE_DIRS = self._parse_bool(os.environ.get("PRESERVE_DIRS", "false"))
        self.COPY_EMPTY_DIRS = self._parse_bool(os.environ.get("COPY_EMPTY_DIRS", "false"))
        
        # File filtering
        self.FILE_INCLUDE_PATTERNS = self._parse_patterns(os.environ.get("FILE_INCLUDE_PATTERNS", ""))
        self.FILE_EXCLUDE_PATTERNS = self._parse_patterns(os.environ.get("FILE_EXCLUDE_PATTERNS", ""))
        
        # Advanced features
        self.WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
        self.DRY_RUN = self._parse_bool(os.environ.get("DRY_RUN", "false"))
        self.DELETE_SOURCE = self._parse_bool(os.environ.get("DELETE_SOURCE", "false"))
        self.MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "0"))  # 0 = unlimited
        self.RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", "3"))
        self.RETRY_DELAY = float(os.environ.get("RETRY_DELAY", "2.0"))
        self.COMPRESS_FILES = self._parse_bool(os.environ.get("COMPRESS_FILES", "false"))
        
        # State management
        self.STATE_CLEANUP_DAYS = int(os.environ.get("STATE_CLEANUP_DAYS", "30"))
        self.STATE_BACKUP_COUNT = int(os.environ.get("STATE_BACKUP_COUNT", "3"))
        
        # Logging
        self.LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
        self._validate_log_level()
    
    def _parse_bool(self, value: str) -> bool:
        """Parse string to boolean."""
        return value.lower() in ("1", "true", "yes")
    
    def _parse_patterns(self, value: str) -> list:
        """Parse comma-separated patterns."""
        if not value or not value.strip():
            return []
        return [p.strip() for p in value.split(',') if p.strip()]
    
    def _validate_log_level(self):
        """Validate log level is supported."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if self.LOG_LEVEL not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL: {self.LOG_LEVEL}. Must be one of {valid_levels}")
    
    def __str__(self) -> str:
        """String representation for logging."""
        return (f"Config(SOURCE={self.SOURCE}, DEST={self.DEST}, "
                f"LOG_LEVEL={self.LOG_LEVEL}, PRESERVE_DIRS={self.PRESERVE_DIRS})")


# Global configuration instance
config = Config()