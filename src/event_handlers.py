"""
Event handlers module for Dropbox Consumer.

Handles file system events and schedules file processing.
"""

import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent
from .config import config
from .logging_setup import get_logger
from .file_operations import process_file, copy_empty_directory
from .state_manager import state_manager

logger = get_logger(__name__)

# Global state for event handling
debounce_timers = {}
lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)


def schedule_process(path: str, reason: str):
    """Schedule file processing with debouncing."""
    with lock:
        # Cancel existing timer for this path
        if path in debounce_timers:
            debounce_timers[path].cancel()
        
        # Schedule new processing
        timer = threading.Timer(config.DEBOUNCE_SECONDS, lambda: executor.submit(process_file, Path(path), reason))
        debounce_timers[path] = timer
        timer.start()
        
        logger.debug(f"Scheduled processing for {path} (reason={reason}) in {config.DEBOUNCE_SECONDS:.2f}s")


class FileSystemEventHandler(FileSystemEventHandler):
    """Custom event handler for file system events."""
    
    def on_created(self, event):
        """Handle file/directory creation events."""
        logger.debug(f"DETECTED -> Created event: {event.src_path} (is_directory={event.is_directory})")
        
        if event.is_directory:
            # Handle directory creation - might need to copy empty directory
            self._handle_directory_event(event.src_path)
        else:
            # File created - check if it's new or was present at startup
            path = Path(event.src_path)
            if not state_manager.is_file_in_snapshot(path):
                schedule_process(event.src_path, "created")
    
    def on_modified(self, event):
        """Handle file modification events."""
        logger.debug(f"DETECTED -> Modified event: {event.src_path} (is_directory={event.is_directory})")
        
        if not event.is_directory:
            path = Path(event.src_path)
            if not state_manager.is_file_in_snapshot(path):
                schedule_process(event.src_path, "modified")
    
    def on_moved(self, event):
        """Handle file move/rename events."""
        logger.debug(f"DETECTED -> Moved event: {getattr(event, 'src_path', 'N/A')} -> {getattr(event, 'dest_path', 'N/A')}")
        
        if hasattr(event, 'dest_path') and not event.is_directory:
            path = Path(event.dest_path)
            if not state_manager.is_file_in_snapshot(path):
                schedule_process(event.dest_path, "moved_in")
    
    def _handle_directory_event(self, dir_path: str):
        """Handle directory creation events."""
        dir_path = Path(dir_path)
        
        # Small delay to allow directory to be fully created
        time.sleep(0.1)
        
        try:
            if dir_path.exists() and dir_path.is_dir():
                # Check if directory is empty
                contents = list(dir_path.iterdir())
                if not contents:
                    logger.debug(f"Checking if should copy empty directory: COPY_EMPTY_DIRS={config.COPY_EMPTY_DIRS}")
                    if config.COPY_EMPTY_DIRS:
                        logger.debug(f"Attempting to copy empty directory: {dir_path}")
                        copy_empty_directory(dir_path)
                    else:
                        logger.debug("COPY_EMPTY_DIRS is disabled, not copying empty directory")
        except Exception as e:
            logger.warning(f"Error handling directory event for {dir_path}: {e}")


def cleanup_executor():
    """Clean up the thread pool executor."""
    executor.shutdown(wait=True)