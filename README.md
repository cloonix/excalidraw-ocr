# Excalidraw OCR

[![Docker Build](https://github.com/cloonix/excalidraw-ocr/actions/workflows/docker-build.yml/badge.svg)](https://github.com/cloonix/excalidraw-ocr/actions/workflows/docker-build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Extract text from handwritten images and Excalidraw drawings using AI vision models.

## Quick Start

### Using Docker (Recommended)

```bash
# Pull the pre-built image
docker pull ghcr.io/cloonix/excalidraw-ocr:latest

# Extract text from an image
docker run --rm -v ./data:/data \
  -e OPENAI_API_KEY=your_key_here \
  ghcr.io/cloonix/excalidraw-ocr:latest \
  python ocr.py /data/image.png

# Extract text from Excalidraw drawing
docker run --rm -v ./data:/data \
  -e OPENAI_API_KEY=your_key_here \
  ghcr.io/cloonix/excalidraw-ocr:latest \
  python excalidraw_ocr.py /data/drawing.excalidraw.md

# Watch mode - automatically process new files
docker run -d --name ocr-watch \
  -v ./watch:/watch \
  -e OPENAI_API_KEY=your_key_here \
  ghcr.io/cloonix/excalidraw-ocr:latest \
  python excalidraw_ocr.py /watch -w
```

### Local Installation

```bash
# Install dependencies
pip install -r requirements.txt
npm install
./install_cairo.sh  # For Excalidraw support

# Configure API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY or OPENROUTER_API_KEY

# Run OCR
python ocr.py image.png
python ocr.py --clipboard  # From clipboard

# Run Excalidraw OCR
python excalidraw_ocr.py drawing.excalidraw.md
python excalidraw_ocr.py folder/ -w  # Watch mode
```

## Features

- 📝 Extract text from handwritten images
- 🎨 Extract text from Excalidraw drawings
- 📋 Clipboard support (copy image → extract text → copy result)
- 👁️ Watch mode for continuous processing
- 🐳 Docker support with pre-built images
- 🔄 Supports OpenAI and OpenRouter APIs
- 💾 Smart caching to avoid reprocessing
- 🌍 Multi-platform: x86_64 and ARM64

## API Keys

Get an API key from:
- **OpenAI** (recommended): https://platform.openai.com/api-keys
- **OpenRouter** (alternative): https://openrouter.ai/keys

Set in `.env` file:
```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o

# OR

OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=google/gemini-flash-1.5
```

## Docker Compose

Build and run locally:

```bash
# Setup
make setup  # Creates directories and .env file
make build  # Build Docker image

# Run
make ocr IMAGE=/data/image.png
make excalidraw FILE=/data/drawing.excalidraw.md
make watch-start  # Start watch mode
make watch-logs   # View logs
make watch-stop   # Stop watch mode
```

Or use `docker-compose.yml` directly:

```bash
docker compose run --rm ocr python ocr.py /data/image.png
docker compose run --rm excalidraw python excalidraw_ocr.py /data/drawing.excalidraw.md
docker compose up -d watch
```

## Command Line Options

### General OCR (`ocr.py`)

```bash
python ocr.py image.png                           # Basic usage
python ocr.py --clipboard                         # From clipboard
python ocr.py image.png -o output.txt             # Save to file
python ocr.py image.png -m anthropic/claude-3.5-sonnet  # Use specific model
python ocr.py --list-models                       # Show available models
```

### Excalidraw OCR (`excalidraw_ocr.py`)

```bash
python excalidraw_ocr.py drawing.excalidraw.md    # Basic usage (auto-saves as drawing.md)
python excalidraw_ocr.py drawing.excalidraw.md -o output.txt  # Custom output
python excalidraw_ocr.py drawing.excalidraw.md -c # Copy to clipboard
python excalidraw_ocr.py folder/ -w               # Watch mode
python excalidraw_ocr.py drawing.excalidraw.md -f # Force reprocess (ignore cache)
```

## Recommended Models

**Fast & Cheap:**
- `google/gemini-flash-1.5` (default for OpenRouter)
- `gpt-4o-mini` (OpenAI)

**High Quality:**
- `gpt-4o` (default for OpenAI)
- `anthropic/claude-3.5-sonnet`

## Troubleshooting

**"OPENAI_API_KEY not found"**
- Create `.env` file with your API key

**"cairosvg not available"** (Excalidraw only)
- Run `./install_cairo.sh`
- Or install manually: `brew install cairo pkg-config` (macOS) or `sudo apt-get install libcairo2-dev pkg-config python3-dev` (Ubuntu)

**"No text extracted"**
- Try a better model: `--model anthropic/claude-3.5-sonnet`
- Check image quality
- Verify API credits

## License

MIT License - See [LICENSE](LICENSE)

## Contributing

Issues and pull requests welcome!
