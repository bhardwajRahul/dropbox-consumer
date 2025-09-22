#!/usr/bin/env python3
"""
Dropbox Consumer - Main Application

A robust file monitoring service for seamless document processing and file synchronization.
Modular architecture with Docker-native logging.
"""

import threading
import time
from watchdog.observers import Observer
from src.config import config
from src.logging_setup import setup_logging
from src.state_manager import state_manager
from src.file_operations import snapshot_existing_files
from src.event_handlers import FileSystemEventHandler, cleanup_executor


def main():
    """Main application entry point."""
    # Initialize logging
    logger = setup_logging()
    logger.info("Starting Dropbox Consumer v2.1")
    
    # Log configuration
    logger.debug(f"Environment variable COPY_EMPTY_DIRS raw value: '{config.COPY_EMPTY_DIRS}'")
    logger.debug(f"Parsed COPY_EMPTY_DIRS boolean value: {config.COPY_EMPTY_DIRS}")
    logger.info(f"SOURCE={config.SOURCE}  DEST={config.DEST}  PRESERVE_DIRS={config.PRESERVE_DIRS}  "
               f"RECURSIVE={config.RECURSIVE}  COPY_EMPTY_DIRS={config.COPY_EMPTY_DIRS}  "
               f"STATE_DIR={config.STATE_DIR}  LOG_LEVEL={config.LOG_LEVEL}")
    
    # Initialize persistent state
    state_manager.ensure_state_dir()
    state_manager.load_state()
    
    # Start periodic state saving in background
    state_saver = threading.Thread(target=state_manager.save_state_periodically, daemon=True)
    state_saver.start()
    
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