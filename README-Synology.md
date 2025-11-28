# Synology NAS Deployment Guide

Deploy the OCR application on your Synology NAS using Container Manager (formerly Docker).

## Prerequisites

- Synology NAS with DSM 7.0 or later
- Container Manager package installed
- OpenAI or OpenRouter API key
- Basic familiarity with Synology DSM interface

## Quick Start (5 Minutes)

### 1. Install Container Manager

1. Open **Package Center**
2. Search for **Container Manager**
3. Click **Install**

### 2. Create Folders

1. Open **File Station**
2. Navigate to your preferred location (e.g., `/docker/`)
3. Create folders:
   - `/docker/ocr/data` - For input/output files
   - `/docker/ocr/watch` - For watch mode (optional)

### 3. Pull the Image

1. Open **Container Manager**
2. Go to **Registry**
3. Search for `ghcr.io/cloonix/excalidraw-ocr`
4. Double-click to download
5. Select tag `latest`
6. Click **Download**

### 4. Create Container

#### Option A: One-Shot Mode (Run Manually)

1. Go to **Container** tab
2. Click **Create** → **Create Container**
3. Select `ghcr.io/cloonix/excalidraw-ocr:latest`
4. Click **Advanced Settings**

**General Settings:**
- Container Name: `ocr-oneshot`
- Enable auto-restart: ❌ (for one-shot)

**Volume Settings:**
- Add folder: `/docker/ocr/data` → `/data`

**Environment:**
- Add variable: `OPENAI_API_KEY` → `your_api_key_here`
- Or: `OPENROUTER_API_KEY` → `your_api_key_here`

**Execution Command:**
```
python ocr.py --help
```

5. Click **Apply** → **Next** → **Done**

To run OCR:
1. Place image in `/docker/ocr/data/`
2. Edit container → Execution Command:
   ```
   python ocr.py /data/your-image.png
   ```
3. Start container
4. View logs for extracted text

#### Option B: Watch Mode (Continuous)

1. Same steps as Option A, but:

**General Settings:**
- Container Name: `ocr-watch`
- Enable auto-restart: ✅ (always)

**Volume Settings:**
- Add folder: `/docker/ocr/watch` → `/watch`

**Execution Command:**
```
python excalidraw_ocr.py /watch -w
```

2. Start container
3. Place `.excalidraw.md` files in `/docker/ocr/watch/`
4. Extracted text appears automatically as `.md` files

## Detailed Configuration

### Environment Variables

Configure in Container Manager → Edit Container → Environment tab:

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (preferred) | `sk-proj-...` |
| `OPENROUTER_API_KEY` | OpenRouter API key (fallback) | `sk-or-v1-...` |
| `OPENAI_MODEL` | OpenAI model to use | `gpt-4o` |
| `OPENROUTER_MODEL` | OpenRouter model to use | `google/gemini-flash-1.5` |
| `DEBUG` | Enable debug logging | `1` |

### Volume Mappings

| Synology Path | Container Path | Purpose |
|---------------|----------------|---------|
| `/docker/ocr/data` | `/data` | Input/output files for one-shot OCR |
| `/docker/ocr/watch` | `/watch` | Continuous monitoring for Excalidraw files |
| `/docker/ocr/logs` | `/home/ocruser/.ocr/logs` | Application logs (optional) |

### Resource Limits (Optional)

Container Manager → Edit Container → Resource Limit:

- **CPU limit**: 200% (2 cores) - adjust based on NAS specs
- **Memory limit**: 2048 MB
- **Swap**: 512 MB

### Network Settings

- **Network Mode**: Bridge (default)
- **No port mapping needed** (file-based processing)

## Usage Examples

### Example 1: Process Single Image

1. Upload `handwriting.jpg` to `/docker/ocr/data/` via File Station
2. Container Manager → Containers → `ocr-oneshot`
3. Edit → Execution Command:
   ```
   python ocr.py /data/handwriting.jpg
   ```
4. Start container
5. View logs for extracted text
6. Or save to file:
   ```
   python ocr.py /data/handwriting.jpg -o /data/result.txt
   ```

### Example 2: Process Excalidraw Drawing

1. Upload `drawing.excalidraw.md` to `/docker/ocr/data/`
2. Execution Command:
   ```
   python excalidraw_ocr.py /data/drawing.excalidraw.md
   ```
3. Start container
4. Result appears as `/docker/ocr/data/drawing.md`

### Example 3: Continuous Watch Mode

1. Start `ocr-watch` container (auto-restart enabled)
2. Upload `.excalidraw.md` files to `/docker/ocr/watch/`
3. Container automatically processes new files
4. Extracted text appears as `.md` files in same folder
5. Monitor logs: Container Manager → Logs tab

## Monitoring & Logs

### View Logs

1. Container Manager → Containers
2. Select your container
3. Click **Logs** button
4. Filter by severity (Info, Warning, Error)

### Health Check

The container includes a built-in health check:
- Verifies Python and Node.js are functional
- Status visible in Container Manager (green/red indicator)

### Persistent Logs (Optional)

To save logs permanently:

1. Create folder: `/docker/ocr/logs`
2. Add volume mapping:
   - Synology: `/docker/ocr/logs`
   - Container: `/home/ocruser/.ocr/logs`

## Troubleshooting

### Container Won't Start

**Check environment variables**:
- Ensure `OPENAI_API_KEY` or `OPENROUTER_API_KEY` is set
- No spaces in API key values

**Check volume paths**:
- Verify folders exist in File Station
- Ensure paths are correct (`/docker/ocr/data` not `/docker/ocr-data`)

### No Text Extracted

**Check logs**:
- Container Manager → Logs
- Look for API errors or rate limits

**Verify API key**:
- Test key at https://platform.openai.com/playground
- Check account has credits

**Try different model**:
- Change `OPENAI_MODEL` to `gpt-4o` (higher quality)
- Or `OPENROUTER_MODEL` to `anthropic/claude-3.5-sonnet`

### Watch Mode Not Working

**Check file location**:
- Files must be in `/docker/ocr/watch/` (mapped to `/watch` in container)
- Files must have `.excalidraw.md` extension

**Check logs**:
- Look for file system events
- Verify files are being detected

**Restart container**:
- Sometimes watchdog needs a fresh start

### Permission Issues

The container runs as user `ocruser` (UID 1000).

**If you get permission errors**:
1. File Station → Right-click folder → Properties
2. Permissions tab → Edit
3. Add user with UID 1000, or make folder writable by everyone (less secure)

## Advanced Configuration

### Using Docker Compose (Advanced Users)

If you prefer `docker-compose.yml` via SSH:

1. SSH into your Synology
2. Create `/volume1/docker/ocr/docker-compose.yml`:
   ```yaml
   version: '3.8'
   services:
     ocr:
       image: ghcr.io/cloonix/excalidraw-ocr:latest
       container_name: ocr-oneshot
       volumes:
         - ./data:/data
       environment:
         - OPENAI_API_KEY=your_key_here
       restart: no
   ```
3. Run: `docker-compose up -d`

### Custom Models

To use a specific model:

1. Edit container → Environment
2. Set `OPENAI_MODEL=gpt-4o` or `OPENROUTER_MODEL=google/gemini-flash-1.5-8b`
3. Restart container

### Batch Processing

For multiple files:

1. Upload all images to `/docker/ocr/data/`
2. Use watch mode or process individually

## Security Considerations

- ✅ API keys stored in container environment (not in images)
- ✅ Container runs as non-root user
- ✅ No ports exposed (file-based communication)
- ⚠️ Images sent to third-party APIs (OpenAI/OpenRouter)
- 🔒 Keep DSM and Container Manager updated

## Performance Tips

- **Lighter model**: Use `google/gemini-flash-1.5-8b` for faster processing
- **Resource limits**: Adjust CPU/memory based on NAS specs
- **Watch mode**: Only monitor folders with active files (reduces CPU usage)

## Updating

To update to the latest version:

1. Container Manager → Registry
2. Download new version of `ghcr.io/cloonix/excalidraw-ocr:latest`
3. Stop running containers
4. Recreate containers with new image
5. Start containers

Alternatively:
```bash
docker pull ghcr.io/cloonix/excalidraw-ocr:latest
docker restart ocr-watch
```

## Support

- **Issues**: https://github.com/cloonix/excalidraw-ocr/issues
- **Documentation**: https://github.com/cloonix/excalidraw-ocr
- **Synology Forum**: Search for "OCR Docker"

---

**Happy OCR processing on your Synology NAS! 🚀**
