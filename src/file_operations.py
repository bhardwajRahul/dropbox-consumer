"""
File operations module for Dropbox Consumer.

Handles file copying, hashing, and directory operations.
"""

import hashlib
import shutil
import time
from pathlib import Path
from typing import Optional
from .config import config
from .logging_setup import get_logger
from .state_manager import state_manager

logger = get_logger(__name__)


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


def atomic_copy(src: Path, dest: Path) -> Path:
    """Copy file atomically using temporary file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    # Use temporary file for atomic operation
    temp_dest = dest.with_suffix(dest.suffix + ".tmp")
    
    try:
        shutil.copy2(src, temp_dest)  # copy2 preserves metadata
        temp_dest.rename(dest)  # Atomic on most filesystems
        logger.debug(f"Atomic copy completed: {src} → {dest}")
        return dest
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
        logger.info(f"📁 Created empty directory: {src_dir.name} → {dest_dir.name}")
        logger.debug(f"COPIED EMPTY DIR -> {src_dir} to {dest_dir}")
    except Exception as e:
        logger.error(f"Failed to create directory {dest_dir}: {e}")


def process_file(path: Path, reason: str):
    """Process a single file for copying."""
    logger.debug(f"Processing candidate: {path} (reason: {reason.upper()})")
    
    # Ensure file exists and is a file
    if not path.exists():
        logger.warning(f"File not found when processing: {path}")
        return
    if path.is_dir():
        logger.debug(f"Ignoring directory: {path}")
        return
    
    # Wait for file to stabilize
    if not wait_for_stable_file(path):
        logger.warning(f"File not stable, skipping: {path}")
        return
    
    # Compute destination
    dest = compute_dest_path(path)
    
    # Check if we've already copied this exact content
    current_hash = compute_sha256(path)
    if not current_hash:
        logger.error(f"Could not compute hash for {path}, skipping")
        return
    
    # Check against previous hash
    cached_hash = state_manager.get_cached_hash(path)
    if cached_hash == current_hash:
        logger.info(f"📄 Found new file: {path.name}")
        logger.debug(f"Skipping copy (content identical to last copied version): {path}")
        return
    
    # Perform the copy
    try:
        start = time.time()
        dest = atomic_copy(path, dest)
        elapsed = time.time() - start
        
        # Log success
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info(f"✅ Copied: {path.name} → {dest.name} ({size_mb:.1f} MB in {elapsed:.2fs})")
        logger.debug(f"Copy details: {path} (size={path.stat().st_size} bytes, hash={current_hash}) → {dest}")
        
        # Update hash cache
        state_manager.set_cached_hash(path, current_hash)
        
    except Exception as e:
        logger.error(f"Failed to copy {path}: {e}")


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