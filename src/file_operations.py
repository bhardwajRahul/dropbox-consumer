"""
File operations module for Dropbox Consumer.

Handles file copying, hashing, and directory operations.
"""

import fnmatch
import gzip
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Optional, Dict, Any
from .config import config
from .logging_setup import get_logger
from .state_manager import state_manager

logger = get_logger(__name__)

# Metrics tracking
metrics = {
    "files_processed": 0,
    "files_skipped": 0,
    "files_failed": 0,
    "bytes_processed": 0,
    "start_time": time.time()
}


def get_metrics() -> Dict[str, Any]:
    """Get current metrics."""
    uptime = time.time() - metrics["start_time"]
    return {
        **metrics,
        "uptime_seconds": uptime
    }


def send_webhook(event: str, data: Dict[str, Any]) -> bool:
    """Send webhook notification."""
    if not config.WEBHOOK_URL:
        return False
    
    try:
        import urllib.request
        import urllib.error
        
        payload = json.dumps({"event": event, "data": data}).encode('utf-8')
        req = urllib.request.Request(
            config.WEBHOOK_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                logger.debug(f"Webhook sent successfully: {event}")
                return True
            else:
                logger.warning(f"Webhook returned status {response.status}")
                return False
    except Exception as e:
        logger.warning(f"Webhook failed: {e}")
        return False


def retry_operation(func, *args, **kwargs):
    """Retry operation with exponential backoff."""
    for attempt in range(config.RETRY_ATTEMPTS):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < config.RETRY_ATTEMPTS - 1:
                delay = config.RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Operation failed (attempt {attempt + 1}/{config.RETRY_ATTEMPTS}), retrying in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise


def validate_dest_path(dest: Path) -> bool:
    """Validate destination path to prevent traversal attacks."""
    try:
        dest.resolve().relative_to(config.DEST.resolve())
        return True
    except ValueError:
        logger.error(f"Path traversal detected: {dest}")
        return False


def should_process_file(path: Path) -> bool:
    """Check if file matches include/exclude patterns."""
    filename = path.name
    
    # Check exclude patterns first
    if config.FILE_EXCLUDE_PATTERNS:
        for pattern in config.FILE_EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(filename, pattern):
                logger.debug(f"File excluded by pattern '{pattern}': {filename}")
                return False
    
    # Check include patterns (if specified, file must match at least one)
    if config.FILE_INCLUDE_PATTERNS:
        for pattern in config.FILE_INCLUDE_PATTERNS:
            if fnmatch.fnmatch(filename, pattern):
                return True
        logger.debug(f"File does not match any include patterns: {filename}")
        return False
    
    # No patterns specified or file passed all checks
    return True


def compute_sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Compute SHA-256 hash of file (streaming for large files)."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.error(f"Failed to compute hash for {path}: {e}")
        return ""


def wait_for_stable_file(path: Path) -> bool:
    """Wait for file to become stable (not being written to)."""
    logger.debug(f"Checking file stability: {path}")
    stable_rounds = 0
    last_size = -1
    
    for attempt in range(int(config.COPY_TIMEOUT / config.STABILITY_CHECK_INTERVAL)):
        try:
            current_size = path.stat().st_size
            if current_size == last_size:
                stable_rounds += 1
                if stable_rounds >= config.STABILITY_STABLE_ROUNDS:
                    logger.debug(f"File is stable: {path} (size={current_size})")
                    return True
            else:
                stable_rounds = 0
                last_size = current_size
                logger.debug(f"File size changed: {path} (size={current_size})")
            
            time.sleep(config.STABILITY_CHECK_INTERVAL)
        except OSError as e:
            logger.warning(f"Error checking file stability {path}: {e}")
            return False
    
    logger.warning(f"File did not stabilize within {config.COPY_TIMEOUT}s: {path}")
    return False


def compute_dest_path(src_path: Path) -> Path:
    """Compute destination path based on configuration."""
    if config.PRESERVE_DIRS:
        # Preserve directory structure
        try:
            rel_path = src_path.relative_to(config.SOURCE)
            return config.DEST / rel_path
        except ValueError:
            # File is not under SOURCE, use filename only
            return config.DEST / src_path.name
    else:
        # Flat structure - just filename
        return config.DEST / src_path.name


def atomic_copy(src: Path, dest: Path, compress: bool = False) -> Path:
    """Copy file atomically using temporary file."""
    # Validate destination path
    if not validate_dest_path(dest):
        raise ValueError(f"Invalid destination path: {dest}")
    
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    # Use temporary file for atomic operation
    if compress:
        temp_dest = dest.with_suffix(dest.suffix + ".gz.tmp")
        final_dest = dest.with_suffix(dest.suffix + ".gz")
    else:
        temp_dest = dest.with_suffix(dest.suffix + ".tmp")
        final_dest = dest
    
    try:
        if compress:
            # Compress while copying
            with src.open('rb') as f_in:
                with gzip.open(temp_dest, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(src, temp_dest)  # copy2 preserves metadata
        
        temp_dest.rename(final_dest)  # Atomic on most filesystems
        logger.debug(f"Atomic copy completed: {src} -> {final_dest}")
        return final_dest
    except Exception as e:
        # Clean up temp file if it exists
        if temp_dest.exists():
            temp_dest.unlink()
        raise e


def copy_empty_directory(src_dir: Path):
    """Copy empty directory structure if configured."""
    logger.debug(f"copy_empty_directory called: src_dir={src_dir}, COPY_EMPTY_DIRS={config.COPY_EMPTY_DIRS}")
    if not config.COPY_EMPTY_DIRS:
        logger.debug("COPY_EMPTY_DIRS is disabled, skipping directory copy")
        return
    
    dest_dir = compute_dest_path(src_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created empty directory: {src_dir.name} -> {dest_dir.name}")
        logger.debug(f"COPIED EMPTY DIR -> {src_dir} to {dest_dir}")
    except Exception as e:
        logger.error(f"Failed to create directory {dest_dir}: {e}")


def process_file(path: Path, reason: str):
    """Process a single file for copying."""
    logger.debug(f"Processing candidate: {path} (reason: {reason.upper()})")
    
    # Ensure file exists and is a file
    if not path.exists():
        logger.warning(f"File not found when processing: {path}")
        metrics["files_failed"] += 1
        return
    if path.is_dir():
        logger.debug(f"Ignoring directory: {path}")
        return
    
    # Check file patterns
    if not should_process_file(path):
        logger.debug(f"File filtered out by patterns: {path}")
        metrics["files_skipped"] += 1
        return
    
    # Check file size limit
    try:
        file_size = path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        if config.MAX_FILE_SIZE_MB > 0 and file_size_mb > config.MAX_FILE_SIZE_MB:
            logger.warning(f"File exceeds size limit ({file_size_mb:.1f} MB > {config.MAX_FILE_SIZE_MB} MB): {path}")
            metrics["files_skipped"] += 1
            return
    except OSError as e:
        logger.error(f"Could not stat file {path}: {e}")
        metrics["files_failed"] += 1
        return
    
    # Wait for file to stabilize
    if not wait_for_stable_file(path):
        logger.warning(f"File not stable, skipping: {path}")
        metrics["files_failed"] += 1
        return
    
    # Compute destination
    dest = compute_dest_path(path)
    
    # Check if we've already copied this exact content
    current_hash = compute_sha256(path)
    if not current_hash:
        logger.error(f"Could not compute hash for {path}, skipping")
        metrics["files_failed"] += 1
        return
    
    # Check against previous hash
    cached_hash = state_manager.get_cached_hash(path)
    if cached_hash == current_hash:
        logger.info(f"Found new file: {path.name}")
        logger.debug(f"Skipping copy (content identical to last copied version): {path}")
        metrics["files_skipped"] += 1
        return
    
    # Dry run mode - don't actually copy
    if config.DRY_RUN:
        logger.info(f"[DRY RUN] Would copy: {path.name} -> {dest.name} ({file_size_mb:.1f} MB)")
        metrics["files_processed"] += 1
        return
    
    # Perform the copy with retry logic
    try:
        start = time.time()
        dest = retry_operation(atomic_copy, path, dest, config.COMPRESS_FILES)
        elapsed = time.time() - start
        
        # Log success
        size_mb = file_size / (1024 * 1024)
        compress_note = " (compressed)" if config.COMPRESS_FILES else ""
        logger.info(f"Copied: {path.name} -> {dest.name} ({size_mb:.1f} MB in {elapsed:.2f}s){compress_note}")
        logger.debug(f"Copy details: {path} (size={file_size} bytes, hash={current_hash}) -> {dest}")
        
        # Update metrics
        metrics["files_processed"] += 1
        metrics["bytes_processed"] += file_size
        
        # Update hash cache
        state_manager.set_cached_hash(path, current_hash)
        
        # Send webhook notification
        if config.WEBHOOK_URL:
            webhook_data = {
                "source": str(path),
                "destination": str(dest),
                "size_bytes": file_size,
                "hash": current_hash,
                "elapsed_seconds": elapsed,
                "compressed": config.COMPRESS_FILES
            }
            send_webhook("file_copied", webhook_data)
        
        # Delete source if configured
        if config.DELETE_SOURCE:
            try:
                path.unlink()
                logger.info(f"Deleted source file: {path.name}")
            except Exception as e:
                logger.error(f"Failed to delete source file {path}: {e}")
        
    except Exception as e:
        logger.error(f"Failed to copy {path}: {e}")
        metrics["files_failed"] += 1


def snapshot_existing_files():
    """Create snapshot of files that exist at startup."""
    logger.info(f"Snapshotting existing files under {config.SOURCE} ...")
    count = 0
    
    try:
        if config.RECURSIVE:
            pattern = "**/*"
        else:
            pattern = "*"
        
        for path in config.SOURCE.glob(pattern):
            if path.is_file():
                state_manager.add_to_snapshot(path)
                count += 1
    except Exception as e:
        logger.warning(f"Error during snapshot: {e}")
    
    logger.info(f"Snapshot complete: {count} files recorded.")