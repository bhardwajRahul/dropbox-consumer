# Release Notes

## [2.0.0] - 2025-09-19

### 🚀 **Major Release - Persistent State Storage**

**Key Innovation**: State persistence ensures files are never re-processed after container restarts, making the service truly production-ready for long-term deployments.

### ✨ **New Features**

#### **🔄 Persistent State Storage**
- 💾 **State persistence** - Maintains file tracking across container restarts
- 📊 **Dual storage system**:
  - `initial_snapshot.json` - Tracks files present at startup
  - `hash_cache.json` - Stores SHA-256 hashes of processed files
- 🗂️ **Configurable state directory** - Defaults to `./state` in current directory
- 🧹 **Automatic cleanup** - Removes old state entries after configurable days
- 🔍 **State loading on startup** - Restores previous session state

#### **⚙️ Enhanced Configuration**
- 🆕 `STATE_DIR` environment variable - Configure state storage location
- 🆕 `STATE_CLEANUP_DAYS` environment variable - Control state retention
- 🛡️ **Permission handling** - Improved PUID/PGID documentation and support
- 📁 **Auto-creation** - State directory created automatically if missing

### 🔧 **Improvements**

#### **📋 Documentation Enhancements**
- 📖 **PUID/PGID guidance** - Detailed user permission configuration
- 🛠️ **Enhanced troubleshooting** - State persistence troubleshooting section
- 💡 **Permission best practices** - Security and ownership recommendations
- 🔍 **Command examples** - How to check user IDs and diagnose issues

#### **🐛 Bug Fixes & Stability**
- ✅ **Immediate state save** - State now saved immediately after initial snapshot
- 🔧 **Improved logging** - Better state operation visibility
- 🛡️ **Permission validation** - Container checks state directory writability
- 📊 **Startup feedback** - Clear indication of loaded state on restart

### 📊 **State Persistence Details**

```json
// initial_snapshot.json - Tracks existing files
{
  "timestamp": 1758300680.0525515,
  "data": {
    "/source/document.pdf": [size, mtime, inode],
    "/source/archive/report.docx": [size, mtime, inode]
  }
}

// hash_cache.json - Prevents duplicate processing
{
  "timestamp": 1758300704.3263733,
  "data": {
    "/source/processed_file.pdf": "sha256_hash_here"
  }
}
```

### 🚨 **Breaking Changes**

- **Docker Compose**: State directory now defaults to `./state` (auto-created)
- **New Environment Variables**: `STATE_DIR` and `STATE_CLEANUP_DAYS` added

### 📦 **Upgrade Instructions**

1. **Update docker-compose.yml** to include state volume:
   ```yaml
   volumes:
     - ./state:/app/state:rw  # Add this line
   ```

2. **Set proper permissions** if needed:
   ```bash
   # Check your user ID
   id $(whoami)
   
   # Update docker-compose.yml
   environment:
     - PUID=1000  # Your user ID
     - PGID=1000  # Your group ID
   ```

3. **Pull and restart**:
   ```bash
   docker compose pull
   docker compose down
   docker compose up -d
   ```

---

## [1.0.0] - 2025-09-18

### 🎉 Initial Release

**Dropbox Consumer** - A robust file monitoring service for seamless document processing and file synchronization.

### ✨ **Core Features**

#### **Smart File Monitoring**
- 🔍 **Real-time file system watching** using efficient event-driven monitoring
- 📁 **Recursive directory scanning** with configurable depth control
- 🕐 **Startup snapshot protection** - only processes files created/modified after service start
- ⚡ **Event debouncing** to handle rapid file system changes intelligently

#### **Intelligent File Processing**
- 🛡️ **File stability detection** - waits for files to finish writing before processing
- 🔒 **Atomic operations** - ensures destination never sees incomplete files
- 📊 **SHA-256 hash comparison** prevents duplicate processing of identical content
- 🧵 **Multi-threaded processing** with configurable worker pool

#### **Directory Structure Management**
- 📂 **Structure preservation** - maintains source directory organization in destination
- 📁 **Empty directory handling** - optional copying of empty folder structures
- 🔄 **Flat vs hierarchical** - configurable directory layout options

#### **Production Ready**
- 🐳 **Docker containerized** with multi-platform support (amd64, arm64)
- 📋 **Comprehensive logging** with configurable verbosity levels
- 🔧 **Environment-based configuration** - no code changes needed
- 🏥 **Health checks** and proper signal handling
- 👤 **Non-root execution** for enhanced security

#### **Integration Focused**
- 📄 **Paperless-NGX optimized** - designed for document management workflows
- 🔌 **Generic file processing** - adaptable for various use cases
- 🔗 **Volume mounting support** - flexible path configuration
- 🎯 **Zero-configuration** default settings for common scenarios

### 🔧 **Configuration Options**

| Feature | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| **Source Monitoring** | `SOURCE` | `/source` | Directory to monitor for new files |
| **Destination** | `DEST` | `/consume` | Target directory for processed files |
| **Recursive Scanning** | `RECURSIVE` | `true` | Monitor subdirectories |
| **Directory Preservation** | `PRESERVE_DIRS` | `false` | Maintain folder structure |
| **Empty Directory Copying** | `COPY_EMPTY_DIRS` | `false` | Copy empty folders |
| **Event Debouncing** | `DEBOUNCE_SECONDS` | `1.0` | Delay between rapid events |
| **File Stability** | `STABILITY_INTERVAL` | `0.5` | Stability check frequency |
| **Stability Rounds** | `STABILITY_STABLE_ROUNDS` | `2` | Required stable checks |
| **Processing Timeout** | `COPY_TIMEOUT` | `60` | Max wait for file stability |
| **Worker Threads** | `MAX_WORKERS` | `4` | Concurrent processing limit |

### 🎯 **Use Cases**

#### **Document Management**
- ✅ Paperless-NGX document ingestion
- ✅ Automated document organization
- ✅ Scan-to-folder workflows

#### **Media Processing**
- ✅ Photo library organization
- ✅ Video processing pipelines
- ✅ Automated media sorting

#### **Data Workflows**
- ✅ ETL pipeline file processing
- ✅ Log file aggregation
- ✅ Backup automation

#### **Development & CI/CD**
- ✅ Build artifact processing
- ✅ Deployment automation
- ✅ File-based triggers

### 🐳 **Docker Distribution**

**Docker Hub**: `trusmith/dropbox-consumer:1.0`

```bash
# Pull and run
docker pull trusmith/dropbox-consumer:1.0
docker run -v /your/source:/source:ro -v /your/dest:/consume:rw trusmith/dropbox-consumer:1.0
```

**Docker Compose**: Ready-to-use configuration included

### 🏗️ **Technical Architecture**

- **Language**: Python 3.12
- **File Monitoring**: Watchdog library with cross-platform support
- **Concurrency**: ThreadPoolExecutor for scalable processing
- **Hashing**: SHA-256 for content deduplication
- **Logging**: Structured logging with multiple severity levels
- **Container**: Distroless-style minimal image for security

### 📋 **Installation & Usage**

#### **Quick Start**
```bash
# Using Docker Compose (recommended)
wget https://raw.githubusercontent.com/john-lazarus/dropbox-consumer/v1.0.0/docker-compose.yml
docker-compose up -d

# Direct Docker run
docker run -d \
  --name dropbox_consumer \
  -v /your/watch/folder:/source:ro \
  -v /your/destination:/consume:rw \
  trusmith/dropbox-consumer:1.0
```

#### **Development Setup**
```bash
git clone https://github.com/john-lazarus/dropbox-consumer.git
cd dropbox-consumer
docker-compose -f docker-compose.dev.yml up
```

### 🛡️ **Security Features**

- ✅ **Non-root container execution** with configurable UID/GID
- ✅ **Read-only source mounting** prevents accidental source modifications
- ✅ **Minimal attack surface** with optimized container image
- ✅ **No network dependencies** for core functionality
- ✅ **Secure file handling** with atomic operations

### 📊 **Performance Characteristics**

- **Memory Usage**: ~20-50MB baseline (scales with concurrent files)
- **CPU Usage**: Minimal (event-driven, not polling-based)
- **File Throughput**: 100s-1000s of files per minute (hardware dependent)
- **Platform Support**: Linux amd64/arm64, Windows (Docker Desktop), macOS (Docker Desktop)

### 📄 **License**

Creative Commons Attribution-NonCommercial 4.0 International License
- ✅ Free for personal and educational use
- ✅ Attribution required
- ❌ Commercial use requires permission

### 🙏 **Acknowledgments**

- Built for the Paperless-NGX community
- Powered by Python Watchdog library
- Inspired by the need for reliable file processing automation

---

**Full Documentation**: [GitHub Repository](https://github.com/john-lazarus/dropbox-consumer)  
**Docker Hub**: [trusmith/dropbox-consumer](https://hub.docker.com/r/trusmith/dropbox-consumer)