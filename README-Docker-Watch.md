# Docker Watch Mode for Excalidraw OCR

Continuous monitoring and automatic processing of Excalidraw files using Docker.

> **Note**: This project uses a unified `docker-compose.yml` that supports both one-shot OCR processing and continuous watch mode. You can run different services using the same configuration file.

## Quick Start (5 Minutes)

### 1. Setup

```bash
# Clone the repository
cd ocr

# Create watch directory
mkdir -p watch

# Configure API key
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY or OPENAI_API_KEY
```

### 2. Build & Start

```bash
# Build the container
make watch-build

# Start watch mode (runs in background)
make watch-start
```

### 3. Use

```bash
# Place .excalidraw.md files in the ./watch folder
cp my-drawing.excalidraw.md watch/

# Monitor logs to see processing
make watch-logs

# Output files appear automatically in ./watch folder
# my-drawing.excalidraw.md → my-drawing.md
```

### 4. Stop

```bash
# Stop watch mode
make watch-stop
```

---

## How It Works

The watch mode container:
1. **Monitors** the `./watch` folder continuously
2. **Detects** new or modified `.excalidraw.md` files
3. **Processes** them automatically with OCR
4. **Outputs** extracted text as `.md` files in the same folder
5. **Caches** results (only reprocesses if content changes)

---

## Configuration

### Environment Variables

Configure in `.env` file:

```bash
# Required: API Key (use one)
OPENROUTER_API_KEY=your_key_here
# OR
OPENAI_API_KEY=your_key_here

# Optional: Model selection
OPENROUTER_MODEL=google/gemini-flash-1.5  # Default
OPENAI_MODEL=gpt-4o                       # Default

# Optional: Debug logging
DEBUG=1
```

### Volume Mounts

The container mounts:
- `./watch` → `/watch` (read-write) - Your Excalidraw files
- `./.env` → `/app/.env` (read-only) - API configuration
- `watch-logs` → `/home/ocruser/.ocr/logs` (persistent volume) - Application logs

---

## Commands Reference

### Management

```bash
make watch-build    # Build/rebuild container
make watch-start    # Start watch mode
make watch-stop     # Stop watch mode
make watch-restart  # Restart watch mode
make watch-status   # Check if running
make watch-clean    # Remove container & volumes
```

### Monitoring

```bash
make watch-logs     # View live logs (Ctrl+C to exit)

# Or use docker-compose directly:
docker-compose -f docker-compose.watch.yml logs -f
```

---

## Features

### Automatic Processing

- **New files**: Detected and processed immediately
- **Modified files**: Re-processed if content changed
- **Deleted files**: Ignored (outputs remain)

### Smart Caching

Files are cached based on content hash:
- Same content = uses cached result (instant)
- Changed content = re-processes automatically
- Force reprocessing: Not available in watch mode (use one-shot mode)

### File Handling

**Supported formats:**
- `.excalidraw.md` - Excalidraw markdown files
- `.excalidraw` - Excalidraw JSON files

**Ignored files:**
- Temporary files (`.swp`, `~`, `.tmp`, `.bak`)
- Hidden files (starting with `.`)
- Output files (`.md` without `.excalidraw` in name)

### Concurrency

- Processes up to **3 files simultaneously**
- Additional files queued automatically
- Prevents resource exhaustion

### Security

- Runs as **non-root user** (UID 1000)
- **Path validation** prevents directory traversal
- **Symlink rejection** prevents unauthorized access
- **File size limits** (10MB max per file)
- **No new privileges** security option enabled

---

## Monitoring & Health

### Health Check

The container includes automatic health monitoring:
- Checks every **60 seconds**
- Restarts if process dies
- Visible in: `docker ps` or `make watch-status`

### Logs

Logs are automatically rotated:
- Max file size: **10MB**
- Max files kept: **3**
- Total max: ~30MB disk space

View logs:
```bash
make watch-logs
```

### Resource Usage

**Limits:**
- CPU: Up to 4 cores
- Memory: Up to 3GB
- Guaranteed: 1 core, 1GB RAM

**Typical usage:**
- Idle: ~100MB RAM, <1% CPU
- Processing: ~500MB RAM, 50-100% CPU per file

---

## Troubleshooting

### Container Won't Start

```bash
# Check status
make watch-status

# View logs
make watch-logs

# Common issues:
# 1. No .env file
cp .env.example .env
# Edit and add API key

# 2. Port conflict (shouldn't happen - no ports exposed)
# 3. Permission issues
sudo chown -R 1000:1000 ./watch
```

### Files Not Being Processed

```bash
# 1. Check if container is running
make watch-status

# 2. Check logs for errors
make watch-logs

# 3. Verify file format
# Must be .excalidraw.md or .excalidraw

# 4. Check file isn't being ignored
# Avoid temp files (.swp, ~, .tmp)

# 5. Restart watch mode
make watch-restart
```

### Output Files Not Created

```bash
# 1. Check logs for processing errors
make watch-logs

# 2. Verify API key is set
cat .env | grep API_KEY

# 3. Check file permissions
ls -la watch/

# 4. Ensure file has valid Excalidraw content
```

### Container Keeps Restarting

```bash
# View last logs before crash
make watch-logs

# Common causes:
# 1. Missing API key
# 2. Invalid .env file syntax
# 3. Memory exhaustion (too many large files)

# Reset container
make watch-clean
make watch-build
make watch-start
```

### High Memory Usage

```bash
# Check current usage
docker stats excalidraw-watch

# If consistently >2GB:
# 1. Reduce concurrent processing (edit docker-compose.watch.yml)
# 2. Process files in smaller batches
# 3. Restart periodically: make watch-restart
```

---

## Performance Tips

### Optimize Processing Speed

1. **Use faster models** (edit `.env`):
   ```bash
   OPENROUTER_MODEL=google/gemini-flash-1.5  # Fast
   # vs
   OPENROUTER_MODEL=anthropic/claude-3-opus  # Slow but higher quality
   ```

2. **Process files in batches**:
   - Don't drop 100 files at once
   - Add 5-10 at a time for better throughput

3. **Use caching**:
   - Don't modify files unnecessarily
   - Cached results are instant

### Reduce Resource Usage

1. **Lower concurrent processing**:
   Edit `docker-compose.watch.yml`:
   ```yaml
   # Change from 3 to 1 for lower resource usage
   ```

2. **Reduce memory limit**:
   ```yaml
   limits:
     memory: 2G  # Instead of 3G
   ```

3. **Schedule restarts**:
   ```bash
   # Add to crontab for daily restart
   0 3 * * * cd /path/to/ocr && make watch-restart
   ```

---

## Advanced Usage

### Multiple Watch Folders

Run multiple containers for different folders:

```bash
# Create second compose file
cp docker-compose.watch.yml docker-compose.watch-notes.yml

# Edit to use different folder and container name
# Then:
docker-compose -f docker-compose.watch-notes.yml up -d
```

### Custom Configuration

Edit `docker-compose.watch.yml` to customize:
- Resource limits (CPU, memory)
- Health check intervals
- Logging configuration
- Restart policies

### Integration with Other Tools

**Obsidian/Notion/etc:**
```bash
# Watch your notes folder
ln -s ~/Obsidian/drawings ./watch
make watch-start
```

**Git Integration:**
```bash
# Auto-commit processed files
watch-logs | while read line; do
  if [[ $line == *"✓ Text saved"* ]]; then
    git add watch/*.md
    git commit -m "Auto-processed Excalidraw files"
  fi
done
```

---

## Security Best Practices

### API Keys

**DO:**
- ✅ Store in `.env` file
- ✅ Add `.env` to `.gitignore`
- ✅ Use read-only mount in container
- ✅ Rotate keys periodically

**DON'T:**
- ❌ Commit `.env` to git
- ❌ Hardcode in docker-compose.yml
- ❌ Share keys publicly
- ❌ Use production keys in development

### File Access

The container runs as UID 1000:
```bash
# Ensure proper permissions
sudo chown -R 1000:1000 ./watch

# Or match your user ID
id -u  # Check your UID
# Update docker-compose.watch.yml if not 1000
```

### Network Security

- Container has no exposed ports
- Uses bridge network (isolated)
- Only outbound HTTPS for API calls
- No incoming connections possible

---

## Comparison: Watch Mode vs One-Shot Mode

| Feature | Watch Mode | One-Shot Mode |
|---------|-----------|---------------|
| **Use Case** | Continuous monitoring | Process once and exit |
| **Command** | `make watch-start` | `make excalidraw FILE=...` |
| **Runs in** | Background (daemon) | Foreground |
| **Caching** | Automatic | Manual (--force to disable) |
| **Resources** | Always running | Only when processing |
| **Best For** | Active projects | Batch processing |

---

## FAQ

### Q: Can I force reprocessing in watch mode?
**A:** Not currently. Use one-shot mode with `--force` flag if needed, or delete the output file.

### Q: How do I know when processing is complete?
**A:** Watch the logs (`make watch-logs`) or check for output `.md` files in the watch folder.

### Q: Can I process files from network drives?
**A:** Yes, but performance may be slower. Ensure the mounted folder is accessible to UID 1000.

### Q: What happens if my API key is invalid?
**A:** Processing will fail with an error in logs. Update `.env` and restart: `make watch-restart`

### Q: Can I run this on a server without X11/display?
**A:** Yes! This is perfect for headless servers. No display needed.

### Q: How much does this cost (API usage)?
**A:** Depends on model and file size. Gemini Flash is ~$0.001 per file. GPT-4o is ~$0.01 per file.

### Q: Can I pause watch mode temporarily?
**A:** Yes: `make watch-stop`, then `make watch-start` to resume.

---

## Support

For issues, questions, or contributions:
- Check logs: `make watch-logs`
- Review main README.md
- File issues on GitHub
- Check AGENTS.md for development guidelines

---

## License

Same as main project.
