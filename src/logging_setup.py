"""
Logging setup module for Dropbox Consumer.

Configures console-only logging for Docker-native log management.
"""

import logging
import sys
from .config import config


def setup_logging():
    """Configure console-only logging with configurable level."""
    # Map string levels to logging constants
    level_mapping = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }
    
    log_level = level_mapping.get(config.LOG_LEVEL, logging.INFO)
    
    # Configure root logger for console output only
    logging.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True  # Override any existing configuration
    )
    
    # Create application logger
    logger = logging.getLogger("dropbox-consumer")
    
    # Log configuration
    logger.info(f"Logging configured: Level={config.LOG_LEVEL}")
    if config.LOG_LEVEL == "DEBUG":
        logger.warning("DEBUG logging enabled - extensive output will be generated")
    
    return logger


def get_logger(name: str = "dropbox-consumer"):
    """Get a logger instance."""
    return logging.getLogger(name)