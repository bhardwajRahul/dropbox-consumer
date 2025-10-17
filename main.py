#!/usr/bin/env python3
"""
Dropbox Consumer - Main Application

A robust file monitoring service for seamless document processing and file synchronization.
Modular architecture with Docker-native logging.
"""

import os
import signal
import threading
import time
from pathlib import Path
from watchdog.observers import Observer
from src.config import config
from src.logging_setup import setup_logging
from src.state_manager import state_manager
from src.file_operations import snapshot_existing_files
from src.event_handlers import FileSystemEventHandler, cleanup_executor


def write_health_file():
    """Write health status file periodically for Docker health checks."""
    health_file = Path('/tmp/health')
    while True:
        try:
            health_file.write_text(str(int(time.time())))
            time.sleep(30)
        except Exception:
            pass


def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    raise KeyboardInterrupt()


def validate_configuration():
    """Validate configuration and directory access."""
    logger = setup_logging()
    errors = []
    
    # Check source directory
    if not config.SOURCE.exists():
        errors.append(f"Source directory does not exist: {config.SOURCE}")
    elif not config.SOURCE.is_dir():
        errors.append(f"Source path is not a directory: {config.SOURCE}")
    elif not os.access(config.SOURCE, os.R_OK):
        errors.append(f"Source directory is not readable: {config.SOURCE}")
    
    # Check/create destination directory
    try:
        config.DEST.mkdir(parents=True, exist_ok=True)
        if not os.access(config.DEST, os.W_OK):
            errors.append(f"Destination directory is not writable: {config.DEST}")
    except Exception as e:
        errors.append(f"Cannot create destination directory {config.DEST}: {e}")
    
    # Check/create state directory
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not os.access(config.STATE_DIR, os.W_OK):
            errors.append(f"State directory is not writable: {config.STATE_DIR}")
    except Exception as e:
        errors.append(f"Cannot create state directory {config.STATE_DIR}: {e}")
    
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        raise ValueError(f"Configuration validation failed with {len(errors)} error(s)")
    
    logger.info("Configuration validation passed")


def main():
    """Main application entry point."""
    # Initialize logging
    logger = setup_logging()
    logger.info("Starting Dropbox Consumer v2.1")
    
    # Validate configuration
    validate_configuration()
    
    # Log configuration
    logger.debug(f"Environment variable COPY_EMPTY_DIRS raw value: '{config.COPY_EMPTY_DIRS}'")
    logger.debug(f"Parsed COPY_EMPTY_DIRS boolean value: {config.COPY_EMPTY_DIRS}")
    logger.info(f"SOURCE={config.SOURCE}  DEST={config.DEST}  PRESERVE_DIRS={config.PRESERVE_DIRS}  "
               f"RECURSIVE={config.RECURSIVE}  COPY_EMPTY_DIRS={config.COPY_EMPTY_DIRS}  "
               f"STATE_DIR={config.STATE_DIR}  LOG_LEVEL={config.LOG_LEVEL}")
    
    if config.FILE_INCLUDE_PATTERNS:
        logger.info(f"Include patterns: {', '.join(config.FILE_INCLUDE_PATTERNS)}")
    if config.FILE_EXCLUDE_PATTERNS:
        logger.info(f"Exclude patterns: {', '.join(config.FILE_EXCLUDE_PATTERNS)}")
    
    # Initialize persistent state
    state_manager.ensure_state_dir()
    state_manager.load_state()
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start periodic state saving in background
    state_saver = threading.Thread(target=state_manager.save_state_periodically, daemon=True)
    state_saver.start()
    
    # Start health file writer in background
    health_writer = threading.Thread(target=write_health_file, daemon=True)
    health_writer.start()
    
    # Snapshot existing files
    snapshot_existing_files()
    
    # Save initial state after snapshotting
    state_manager.save_state()
    
    # Ensure destination exists
    config.DEST.mkdir(parents=True, exist_ok=True)
    
    # Set up file system monitoring
    event_handler = FileSystemEventHandler()
    observer = Observer()
    observer.schedule(event_handler, str(config.SOURCE), recursive=config.RECURSIVE)
    
    try:
        observer.start()
        logger.info(f"Observer started. (startup_time={time.strftime('%Y-%m-%d %H:%M:%S')})")
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Stopping observer...")
        observer.stop()
        observer.join()
        
        logger.info("Saving final state...")
        state_manager.save_state()
        
        logger.info("Cleaning up executor...")
        cleanup_executor()
        
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()