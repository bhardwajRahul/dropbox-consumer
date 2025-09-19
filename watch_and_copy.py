#!/usr/bin/env python3
"""
dropbox-consumer

Watches SOURCE for new/changed files created AFTER the script starts,
copies them (atomically) to DEST, and logs detailed info to stdout.

Behavior highlights:
- At startup, we snapshot existing files and won't re-copy those unless they change after startup.
- We react to created / moved_into / modified events that happen after startup.
- We wait for the file to become stable (size unchanged for a short period) before copying.
- We compute a SHA-256 of the file and only copy if content differs from the last copied version
  (so two identical writes won't re-copy repeatedly).
- Copy performed via temp file + atomic rename so Paperless won't see half-written files.
- Console-only, detailed logging.
"""

import os
import sys
import time
import hashlib
import logging
import threading
import shutil
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent

# --- Configuration (change with env vars) ---
SOURCE = Path(os.environ.get("SOURCE", "/source")).resolve()
DEST = Path(os.environ.get("DEST", "/consume")).resolve()
STATE_DIR = Path(os.environ.get("STATE_DIR", "/app/state")).resolve()  # Persistent state storage
RECURSIVE = os.environ.get("RECURSIVE", "true").lower() in ("1", "true", "yes")
DEBOUNCE_SECONDS = float(os.environ.get("DEBOUNCE_SECONDS", "1.0"))      # debounce events for same path
STABILITY_CHECK_INTERVAL = float(os.environ.get("STABILITY_INTERVAL", "0.5"))
STABILITY_STABLE_ROUNDS = int(os.environ.get("STABILITY_STABLE_ROUNDS", "2"))  # number of consecutive identical size checks to consider stable
COPY_TIMEOUT = int(os.environ.get("COPY_TIMEOUT", "60"))                 # max time to wait for file to stabilize (sec)
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
PRESERVE_DIRS = os.environ.get("PRESERVE_DIRS", "false").lower() in ("1", "true", "yes")
COPY_EMPTY_DIRS = os.environ.get("COPY_EMPTY_DIRS", "false").lower() in ("1", "true", "yes")  # copy empty directories
STATE_CLEANUP_DAYS = int(os.environ.get("STATE_CLEANUP_DAYS", "30"))     # cleanup old state entries after N days

# --- Logging (console only) ---
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,  # Changed to DEBUG to see all events
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("dropbox-consumer")

# --- Globals ---
startup_time = time.time()
initial_snapshot = {}   # path -> (size, mtime, inode)
debounce_timers = {}    # path -> threading.Timer
lock = threading.Lock()
last_copied_hash = {}   # path -> sha256 hex
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# --- State file paths ---
SNAPSHOT_FILE = STATE_DIR / "initial_snapshot.json"
HASH_CACHE_FILE = STATE_DIR / "hash_cache.json"


def ensure_state_dir():
    """Ensure state directory exists with proper permissions."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("State directory initialized: %s", STATE_DIR)
        # Check permissions
        test_file = STATE_DIR / "__test_write__"
        try:
            with test_file.open('w') as f:
                f.write('test')
            test_file.unlink()
            log.info("State directory is writable: %s", STATE_DIR)
        except Exception as e:
            log.error("State directory is not writable: %s (%s)", STATE_DIR, e)
    except Exception as e:
        log.warning("Could not create state directory %s: %s", STATE_DIR, e)
        log.warning("Running without persistent state - data will be lost on restart")


def save_state():
    """Save current state to disk."""
    if not STATE_DIR.exists():
        log.error("State directory does not exist: %s", STATE_DIR)
        return
    try:
        # Save initial snapshot
        snapshot_data = {
            'timestamp': startup_time,
            'data': initial_snapshot
        }
        with SNAPSHOT_FILE.open('w') as f:
            json.dump(snapshot_data, f, indent=2)
        log.info("Wrote snapshot file: %s", SNAPSHOT_FILE)
        # Save hash cache with timestamp for cleanup
        hash_data = {
            'timestamp': time.time(),
            'data': last_copied_hash
        }
        with HASH_CACHE_FILE.open('w') as f:
            json.dump(hash_data, f, indent=2)
        log.info("Wrote hash cache file: %s", HASH_CACHE_FILE)
        log.debug("State saved successfully")
    except Exception as e:
        log.error("Failed to save state: %s", e)


def load_state():
    """Load previous state from disk."""
    global initial_snapshot, last_copied_hash
    
    if not STATE_DIR.exists():
        log.info("No state directory found, starting fresh")
        return
    
    try:
        # Load initial snapshot
        if SNAPSHOT_FILE.exists():
            with SNAPSHOT_FILE.open('r') as f:
                snapshot_data = json.load(f)
            initial_snapshot = snapshot_data.get('data', {})
            log.info("Loaded previous snapshot: %d files", len(initial_snapshot))
        
        # Load hash cache
        if HASH_CACHE_FILE.exists():
            with HASH_CACHE_FILE.open('r') as f:
                hash_data = json.load(f)
            last_copied_hash = hash_data.get('data', {})
            log.info("Loaded hash cache: %d files", len(last_copied_hash))
            
        # Cleanup old entries
        cleanup_old_state()
            
    except Exception as e:
        log.warning("Failed to load previous state: %s", e)
        log.info("Starting with fresh state")
        initial_snapshot = {}
        last_copied_hash = {}


def cleanup_old_state():
    """Remove old entries from state to prevent unbounded growth."""
    if STATE_CLEANUP_DAYS <= 0:
        return
    
    cleanup_threshold = time.time() - (STATE_CLEANUP_DAYS * 24 * 3600)
    cleaned_hashes = 0
    
    # Clean up hash cache entries
    old_hash_cache = last_copied_hash.copy()
    for file_path, hash_value in old_hash_cache.items():
        try:
            # Check if file still exists
            if not Path(file_path).exists():
                del last_copied_hash[file_path]
                cleaned_hashes += 1
        except Exception:
            # Remove entries that can't be checked
            del last_copied_hash[file_path]
            cleaned_hashes += 1
    
    if cleaned_hashes > 0:
        log.info("Cleaned up %d old hash cache entries", cleaned_hashes)
        save_state()


def save_state_periodically():
    """Save state every 5 minutes to prevent data loss."""
    while True:
        time.sleep(300)  # 5 minutes
        save_state()


def compute_sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Compute SHA-256 hash (streaming)"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def snapshot_existing_files():
    """Record existing files at startup to avoid copying them immediately."""
    log.info("Snapshotting existing files under %s ...", SOURCE)
    if not SOURCE.exists():
        log.warning("Source path %s does not exist at startup.", SOURCE)
        return
    for root, _, files in os.walk(SOURCE):
        for fname in files:
            p = Path(root) / fname
            try:
                st = p.stat()
                initial_snapshot[str(p.resolve())] = (st.st_size, st.st_mtime, getattr(st, "st_ino", None))
            except FileNotFoundError:
                continue
    log.info("Snapshot complete: %d files recorded.", len(initial_snapshot))


def path_within_source(path: str) -> bool:
    try:
        return os.path.commonpath([str(SOURCE), path]) == str(SOURCE)
    except Exception:
        return False


def schedule_process(path: str, reason: str):
    """Debounce events for the same path and schedule actual processing."""
    path = str(Path(path).resolve())
    if not path_within_source(path):
        return

    def _submit():
        with lock:
            debounce_timers.pop(path, None)
        executor.submit(process_file, path, reason)

    with lock:
        timer = debounce_timers.get(path)
        if timer:
            timer.cancel()
        t = threading.Timer(DEBOUNCE_SECONDS, _submit)
        debounce_timers[path] = t
        t.daemon = True
        t.start()
        log.debug("Scheduled processing for %s (reason=%s) in %.2fs", path, reason, DEBOUNCE_SECONDS)


def should_process_event(path: str) -> bool:
    """
    Decide whether this path should be considered:
    - If it was present at startup, only process it if it changed (mtime) after startup.
    - If it wasn't present, process it.
    """
    path = str(Path(path).resolve())
    if path not in initial_snapshot:
        return True
    # It was present at startup; check current mtime
    try:
        st = Path(path).stat()
    except FileNotFoundError:
        return False
    size, mtime, ino = initial_snapshot.get(path)
    # If the file's mtime or size differ since startup snapshot, treat as changed after startup
    if st.st_mtime > startup_time + 1e-6:
        return True
    if st.st_size != size:
        return True
    return False


def wait_for_stable(path: Path, timeout: int = COPY_TIMEOUT) -> bool:
    """Wait until file size stays the same for STABILITY_STABLE_ROUNDS checks."""
    start = time.time()
    prev_size = -1
    same_rounds = 0
    while True:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            log.warning("File disappeared while waiting for stability: %s", path)
            return False
        if size == prev_size:
            same_rounds += 1
        else:
            same_rounds = 0
        prev_size = size
        if same_rounds >= STABILITY_STABLE_ROUNDS:
            return True
        if time.time() - start > timeout:
            log.warning("Timeout waiting for stability for %s (last size=%d). Proceeding anyway.", path, size)
            return True
        time.sleep(STABILITY_CHECK_INTERVAL)


def make_dest_dir_path(src_path: Path) -> Path:
    """Compute the destination directory path. If PRESERVE_DIRS: preserve relative path under DEST; else use DEST."""
    if PRESERVE_DIRS:
        try:
            rel = src_path.resolve().relative_to(SOURCE.resolve())
            dest = DEST / rel
        except Exception:
            dest = DEST
    else:
        dest = DEST
    return dest


def make_dest_path(src_path: Path) -> Path:
    """Compute the destination path. If PRESERVE_DIRS: preserve relative path under DEST; else flat basename."""
    if PRESERVE_DIRS:
        try:
            rel = src_path.resolve().relative_to(SOURCE.resolve())
            dest = DEST / rel
        except Exception:
            dest = DEST / src_path.name
    else:
        dest = DEST / src_path.name
    return dest


def copy_empty_directory(src_dir: Path):
    """Copy an empty directory structure to destination."""
    log.debug("copy_empty_directory called: src_dir=%s, COPY_EMPTY_DIRS=%s", src_dir, COPY_EMPTY_DIRS)
    if not COPY_EMPTY_DIRS:
        log.debug("COPY_EMPTY_DIRS is disabled, skipping directory copy")
        return
    
    dest_dir = make_dest_dir_path(src_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        log.info("COPIED EMPTY DIR -> %s to %s", src_dir, dest_dir)
    except Exception as e:
        log.exception("Failed to copy empty directory %s -> %s: %s", src_dir, dest_dir, e)


def atomic_copy(src: Path, dest: Path):
    """Copy src -> dest atomically (copy to temp then os.replace)."""
    dest_dir = dest.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmpname = f".{dest.name}.part.{os.getpid()}.{int(time.time()*1000)}"
    tmp_path = dest_dir / tmpname
    # shutil.copy2 preserves metadata
    shutil.copy2(src, tmp_path)
    os.replace(tmp_path, dest)  # atomic on same filesystem
    return dest


def process_file(path: str, reason: str):
    path = Path(path)
    log.info("EVENT -> %s ; candidate: %s", reason.upper(), path)
    # ensure file exists and is a file
    if not path.exists():
        log.warning("File not found when processing: %s", path)
        return
    if path.is_dir():
        log.debug("Ignoring directory: %s", path)
        return

    if not should_process_event(str(path)):
        log.info("Skipping (file existed at startup and not changed after startup): %s", path)
        return

    # wait for file to stabilize (size not changing)
    ok = wait_for_stable(path)
    if not ok:
        log.warning("File not stable but proceeding: %s", path)

    # compute hash for change detection
    try:
        sha = compute_sha256(path)
    except Exception as e:
        log.exception("Failed computing hash for %s: %s", path, e)
        sha = None

    last_sha = last_copied_hash.get(str(path))
    if sha is not None and last_sha == sha:
        log.info("Skipping copy (content identical to last copied version): %s", path)
        return

    # perform atomic copy
    dest = make_dest_path(path)
    try:
        start = time.time()
        dest = atomic_copy(path, dest)
        elapsed = time.time() - start
        log.info("COPIED -> %s  (size=%d bytes, hash=%s) to %s  (took %.3fs)",
                 path, path.stat().st_size, sha or "?", dest, elapsed)
        if sha:
            last_copied_hash[str(path)] = sha
            # Save state immediately after successful copy
            save_state()
    except Exception as e:
        log.exception("Copy failed for %s -> %s: %s", path, dest, e)


class MyHandler(FileSystemEventHandler):
    def on_created(self, event):
        log.debug("DETECTED -> Created event: %s (is_directory=%s)", event.src_path, event.is_directory)
        if event.is_directory:
            # When a directory is created, scan it for existing files
            self._scan_new_directory(event.src_path)
            return
        if should_process_event(event.src_path):
            schedule_process(event.src_path, "created")

    def on_modified(self, event):
        # many editors and copy utilities produce modified events; we handle them but debounce
        log.debug("DETECTED -> Modified event: %s (is_directory=%s)", event.src_path, event.is_directory)
        if event.is_directory:
            # Directory modified - might contain new files, scan it
            self._scan_new_directory(event.src_path)
            return
        if should_process_event(event.src_path):
            schedule_process(event.src_path, "modified")
    
    def _scan_new_directory(self, dir_path: str):
        """Scan a newly created/modified directory for files to process."""
        dir_path = Path(dir_path)
        if not dir_path.is_dir() or not path_within_source(str(dir_path)):
            return
        
        log.info("Scanning new/modified directory: %s", dir_path)
        
        try:
            files_found = 0
            if RECURSIVE:
                # Recursively scan the directory
                for root, _, files in os.walk(dir_path):
                    for fname in files:
                        file_path = Path(root) / fname
                        if file_path.is_file() and should_process_event(str(file_path)):
                            schedule_process(str(file_path), "found_in_new_dir")
                            files_found += 1
            else:
                # Only scan direct files in the directory
                for item in dir_path.iterdir():
                    if item.is_file() and should_process_event(str(item)):
                        schedule_process(str(item), "found_in_new_dir")
                        files_found += 1
            
            if files_found == 0:
                log.info("Directory %s is empty or contains no new files to process", dir_path)
                # If enabled, copy the empty directory structure
                log.debug("Checking if should copy empty directory: COPY_EMPTY_DIRS=%s", COPY_EMPTY_DIRS)
                if COPY_EMPTY_DIRS:
                    log.debug("Attempting to copy empty directory: %s", dir_path)
                    copy_empty_directory(dir_path)
                else:
                    log.debug("COPY_EMPTY_DIRS is disabled, not copying empty directory")
            else:
                log.info("Found %d files to process in directory %s", files_found, dir_path)
                
        except Exception as e:
            log.exception("Error scanning directory %s: %s", dir_path, e)

    def on_moved(self, event):
        log.debug("DETECTED -> Moved event: %s -> %s", getattr(event, 'src_path', 'N/A'), getattr(event, 'dest_path', 'N/A'))
        # if a file is moved into the watched dir, dest_path is the interesting one
        if isinstance(event, FileMovedEvent):
            if event.dest_path and path_within_source(event.dest_path):
                if should_process_event(event.dest_path):
                    schedule_process(event.dest_path, "moved_in")


def main():
    log.info("Starting file watcher.")
    log.debug("Environment variable COPY_EMPTY_DIRS raw value: '%s'", os.environ.get("COPY_EMPTY_DIRS", "NOT_SET"))
    log.debug("Parsed COPY_EMPTY_DIRS boolean value: %s", COPY_EMPTY_DIRS)
    log.info("SOURCE=%s  DEST=%s  PRESERVE_DIRS=%s  RECURSIVE=%s  COPY_EMPTY_DIRS=%s  STATE_DIR=%s", 
             SOURCE, DEST, PRESERVE_DIRS, RECURSIVE, COPY_EMPTY_DIRS, STATE_DIR)

    # Initialize persistent state
    ensure_state_dir()
    load_state()

    # Start periodic state saving in background
    state_saver = threading.Thread(target=save_state_periodically, daemon=True)
    state_saver.start()

    snapshot_existing_files()
    
    # Save initial state after snapshotting
    save_state()

    # ensure destination exists
    DEST.mkdir(parents=True, exist_ok=True)

    event_handler = MyHandler()
    observer = Observer()
    observer.schedule(event_handler, str(SOURCE), recursive=RECURSIVE)
    observer.start()
    log.info("Observer started. (startup_time=%s)", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(startup_time)))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt, stopping observer...")
    finally:
        observer.stop()
        observer.join()
        # Save final state before shutdown
        save_state()
        executor.shutdown(wait=True)
        log.info("Watcher stopped cleanly.")


if __name__ == "__main__":
    main()

