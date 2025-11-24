# Docker Usage Guide for OCR Application

This guide explains how to use the OCR application with Docker for easy deployment and consistent environments.

## Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Usage Examples](#usage-examples)
- [Security Features](#security-features)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)

## Quick Start

```bash
# 1. Clone and navigate to the repository
cd /path/to/ocr

# 2. Setup directories and environment
make setup

# 3. Edit .env and add your API key
nano .env  # or your preferred editor

# 4. Build the Docker image
make build

# 5. Test the setup
make test

# 6. Process an image
make ocr IMAGE=/input/yourimage.png
```

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Make (optional, for convenience commands)
- OpenRouter API key (get one at https://openrouter.ai/)

## Setup

### 1. Initial Setup

Create necessary directories and configuration:

```bash
make setup
```

This creates:
- `./input/` - Place images and Excalidraw files here
- `./output/` - Processed output saved here
- `.env` - Copy of `.env.example` for your API key

### 2. Configure API Key

Edit `.env` and add your OpenRouter API key:

```bash
OPENROUTER_API_KEY=sk-or-v1-your-actual-key-here
OPENROUTER_MODEL=google/gemini-flash-1.5  # Optional: change model
```

### 3. Build Docker Image

```bash
make build
```

Or without Make:

```bash
docker-compose build
```

## Usage Examples

### Basic OCR on Image

Using Make:
```bash
# Copy your image to input directory
cp myimage.png input/

# Process it
make ocr IMAGE=/input/myimage.png
```

Without Make:
```bash
docker-compose run --rm ocr python ocr.py /input/myimage.png
```

### Save OCR Output to File

```bash
# Output to specific file
make ocr IMAGE=/input/myimage.png OUTPUT=/output/result.txt

# Or with docker-compose
docker-compose run --rm ocr python ocr.py /input/myimage.png -o /output/result.txt
```

### Excalidraw OCR

```bash
# Process Excalidraw file
make excalidraw FILE=/input/drawing.excalidraw.md

# Or with docker-compose
docker-compose run --rm ocr python excalidraw_ocr.py /input/drawing.excalidraw.md
```

### Batch Processing

Process all images in input directory:

```bash
make batch-ocr
```

Process all Excalidraw files:

```bash
make batch-excalidraw
```

### Using Different Models

```bash
# List available models
make list-models

# Use specific model
docker-compose run --rm \
  -e OPENROUTER_MODEL=anthropic/claude-3.5-sonnet \
  ocr python ocr.py /input/image.png
```

### Interactive Shell

Open a shell inside the container for debugging:

```bash
make shell

# Inside container:
ls /input
python ocr.py --help
exit
```

## Volume Mounts

The Docker setup uses the following volume mounts:

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `./input` | `/input` | `ro` | Input files (read-only) |
| `./output` | `/output` | `rw` | Output files |
| `./.env` | `/app/.env` | `ro` | Environment variables (read-only) |
| `ocr-logs` | `/home/ocruser/.ocr/logs` | `rw` | Application logs (Docker volume) |

## Security Features

### 1. Non-Root User
- Container runs as `ocruser` (UID 1000)
- No root privileges inside container
- Prevents privilege escalation attacks

### 2. Read-Only Mounts
- Input directory mounted read-only
- `.env` file mounted read-only
- Prevents accidental modifications

### 3. Resource Limits
```yaml
# From docker-compose.yml
limits:
  cpus: '2'
  memory: 2G
```

### 4. Temporary Filesystem
- Isolated tmpfs for temp files
- 1GB size limit
- Automatically cleaned up

### 5. No New Privileges
```yaml
security_opt:
  - no-new-privileges:true
```

### 6. Network Isolation
- No exposed ports
- Only outbound HTTPS to OpenRouter API

## Advanced Usage

### Custom Commands

Run any Python script:
```bash
docker-compose run --rm ocr python your_script.py
```

Run Python interactively:
```bash
docker-compose run --rm ocr python
```

### View Logs

```bash
# Live logs
make logs

# Or with docker-compose
docker-compose logs -f ocr

# View log files from volume
docker-compose run --rm ocr cat /home/ocruser/.ocr/logs/ocr.log
```

### Building Without Cache

```bash
make dev-build

# Or
docker-compose build --no-cache
```

### Override Environment Variables

```bash
docker-compose run --rm \
  -e OPENROUTER_MODEL=openai/gpt-4o \
  -e DEBUG=1 \
  ocr python ocr.py /input/image.png
```

### Process Files from Different Directory

```bash
docker-compose run --rm \
  -v /path/to/your/images:/custom:ro \
  ocr python ocr.py /custom/image.png
```

### Clipboard Support (Advanced)

For clipboard support on Linux with X11:

```bash
docker-compose run --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  ocr python ocr.py --clipboard
```

**Note**: Clipboard features have limited support in Docker.

## Architecture

### Multi-Stage Build

The Dockerfile uses a multi-stage build for optimization:

1. **Builder Stage**: Installs build dependencies, compiles packages
2. **Runtime Stage**: Copies only runtime artifacts, much smaller image

### Image Sizes

- Builder stage: ~1.2GB
- Final image: ~450MB
- With all layers: ~500MB

### Dependencies

**System:**
- Python 3.11
- Node.js 18.x
- Cairo library

**Python packages:**
- Pillow (image processing)
- cairosvg (SVG rendering)
- requests (API calls)
- python-dotenv (environment)
- pyperclip (clipboard - limited in Docker)

**Node packages:**
- lz-string (decompression)

## Troubleshooting

### Image Build Fails

```bash
# Clean everything and rebuild
make clean-all
make build
```

### Permission Denied Errors

The container runs as UID 1000. Ensure your input/output directories are accessible:

```bash
# Fix permissions
sudo chown -R 1000:1000 input output

# Or make world-readable
chmod -R a+rX input
chmod -R a+rwX output
```

### API Key Not Working

Check your `.env` file:

```bash
# View contents (be careful in production!)
cat .env

# Test inside container
docker-compose run --rm ocr env | grep OPENROUTER
```

### Out of Memory

Increase memory limit in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 4G  # Increased from 2G
```

### Node.js or Python Not Found

Verify installation:

```bash
make test
```

### Temp Directory Issues

If you see temp directory errors:

```bash
# Verify tmpfs mount
docker-compose run --rm ocr df -h /tmp
```

### Check Logs

```bash
# Container logs
make logs

# Application logs
docker-compose run --rm ocr cat /home/ocruser/.ocr/logs/ocr.log
```

## Production Deployment

### Using Docker Hub

```bash
# Tag image
docker tag ocr-app:latest yourusername/ocr-app:1.0

# Push to Docker Hub
docker push yourusername/ocr-app:1.0

# Pull on production server
docker pull yourusername/ocr-app:1.0
```

### Using Private Registry

```bash
# Tag for private registry
docker tag ocr-app:latest registry.example.com/ocr-app:1.0

# Push
docker push registry.example.com/ocr-app:1.0
```

### Security Scanning

```bash
# Scan image for vulnerabilities
docker scan ocr-app:latest

# Or with Trivy
trivy image ocr-app:latest
```

### Environment-Specific Configs

Create separate compose files:

```bash
# docker-compose.prod.yml
version: '3.8'
services:
  ocr:
    extends:
      file: docker-compose.yml
      service: ocr
    environment:
      - OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
    deploy:
      resources:
        limits:
          memory: 4G
```

Use it:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up
```

## Makefile Commands Reference

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make setup` | Initial setup (directories, .env) |
| `make build` | Build Docker image |
| `make run` | Run container (shows help) |
| `make shell` | Open interactive shell |
| `make test` | Test installation |
| `make ocr IMAGE=...` | Process single image |
| `make excalidraw FILE=...` | Process Excalidraw file |
| `make batch-ocr` | Process all images |
| `make batch-excalidraw` | Process all Excalidraw files |
| `make list-models` | Show available models |
| `make logs` | View logs |
| `make stop` | Stop containers |
| `make clean` | Remove containers/volumes |
| `make clean-all` | Remove everything |

## Performance Tips

1. **Use local cache**: Docker caches layers, rebuilds are fast
2. **Batch processing**: Process multiple files in one command
3. **Resource limits**: Adjust based on your needs
4. **SSD storage**: Faster for Docker volumes
5. **Model selection**: Faster models like `gemini-flash-1.5` are cheaper

## Best Practices

1. **Never commit .env**: Already in .gitignore
2. **Use specific tags**: Not `latest` in production
3. **Regular updates**: Rebuild periodically for security patches
4. **Monitor logs**: Check for errors regularly
5. **Backup volumes**: Persistent data in Docker volumes
6. **Test locally first**: Before deploying to production

## Support

- Review main README.md for application details
- Check SECURITY.md for security information
- Open issues on GitHub for bugs
- See logs for debugging: `make logs`

## License

See LICENSE file in repository root.
