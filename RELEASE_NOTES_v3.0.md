# Release Notes - v3.0

## Changes

### Modular Architecture
- Refactored monolithic application into separate modules
- Improved code maintainability and testing

### Docker Logging
- Replaced Python log rotation with Docker-native logging
- Configurable LOG_LEVEL environment variable
- Automatic log size management (10MB max, 3 files)

### Configuration Updates
- Removed LOG_ROTATION_DAYS (Docker handles rotation)
- Simplified logging configuration
- Updated Dockerfile for modular structure

### Bug Fixes
- Fixed logging format string error in file operations

## Breaking Changes
- LOG_ROTATION_DAYS environment variable removed
- Application entry point changed from watch_and_copy.py to main.py

## Migration
No action required for existing deployments. Update docker-compose.yml to remove LOG_ROTATION_DAYS if present.

## Files Changed
- Added: main.py, src/config.py, src/logging_setup.py, src/state_manager.py, src/file_operations.py, src/event_handlers.py
- Modified: Dockerfile, docker-compose.yml, README.md
- Deprecated: watch_and_copy.py (functionality moved to modular structure)