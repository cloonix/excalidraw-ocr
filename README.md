# AI-Powered OCR with OpenRouter

Extract text from handwritten images using AI vision models via OpenRouter API.

## Features

- 📝 Extract text from handwritten images
- 📋 Support for both image files and clipboard input
- ✨ Auto-copy OCR results back to clipboard when using clipboard mode
- 🔄 Easy model switching via OpenRouter
- 🎯 Multiple format support (PNG, JPG, JPEG, WEBP, GIF)
- 💾 Save output to file or print to stdout
- 🚀 Simple command-line interface

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Get an OpenRouter API key:
   - Sign up at https://openrouter.ai/
   - Get your API key from https://openrouter.ai/keys
   - Add credits to your account

4. Create a `.env` file:
```bash
cp .env.example .env
```

5. Edit `.env` and add your API key:
```
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=google/gemini-flash-1.5
```

## Usage

### Basic Usage

Extract text from an image file:
```bash
python ocr.py image.png
```

Extract text from clipboard (result automatically copied back to clipboard):
```bash
python ocr.py --clipboard
```

### Advanced Usage

Use a specific model:
```bash
python ocr.py image.jpg --model anthropic/claude-3.5-sonnet
```

Save output to file:
```bash
python ocr.py image.png --output result.txt
```

Combine options:
```bash
python ocr.py --clipboard --model google/gemini-pro-1.5 --output output.txt
```

List available models:
```bash
python ocr.py --list-models
```

### Command-Line Options

```
positional arguments:
  image                 Path to image file (PNG, JPG, JPEG, WEBP, GIF)

options:
  -h, --help            Show help message
  -c, --clipboard       Read image from clipboard and copy result back to clipboard
  -m MODEL, --model MODEL
                        OpenRouter model to use
  -o OUTPUT, --output OUTPUT
                        Save extracted text to file (disables clipboard copy)
  --list-models         Show popular vision models
  --no-clipboard-copy   Don't copy result to clipboard when using --clipboard mode
```

## Recommended Models

### Fast & Affordable
- `google/gemini-flash-1.5` (default) - Best balance of speed and cost
- `google/gemini-flash-1.5-8b` - Even faster, lower cost

### High Quality
- `anthropic/claude-3.5-sonnet` - Excellent accuracy for handwriting
- `google/gemini-pro-1.5` - High quality results
- `openai/gpt-4o` - Strong overall performance

### Open Source
- `qwen/qwen-2-vl-72b-instruct` - Good open-source alternative
- `meta-llama/llama-3.2-90b-vision-instruct` - Meta's vision model

See the full list at: https://openrouter.ai/models?order=newest&supported_parameters=vision

## Examples

### Example 1: Quick OCR from Screenshot
1. Take a screenshot (it's now in your clipboard)
2. Run: `python ocr.py --clipboard`
3. The extracted text is automatically copied back to your clipboard
4. Paste it anywhere you need!

### Example 2: Batch Processing
```bash
for img in images/*.png; do
  python ocr.py "$img" --output "text/$(basename "$img" .png).txt"
done
```

### Example 3: Test Different Models
```bash
python ocr.py handwriting.jpg --model google/gemini-flash-1.5
python ocr.py handwriting.jpg --model anthropic/claude-3.5-sonnet
```

## Troubleshooting

### "No image found in clipboard"
- Make sure you've copied an image (not a file path) to your clipboard
- On Linux, you may need additional packages: `sudo apt install xclip python3-tk`

### "OPENROUTER_API_KEY not found"
- Check that your `.env` file exists in the same directory as `ocr.py`
- Verify the API key is set correctly in `.env`

### "API request failed"
- Check your internet connection
- Verify your OpenRouter account has credits
- Check the model name is correct

### Poor OCR Quality
- Try a more powerful model (e.g., Claude 3.5 Sonnet)
- Ensure the image is clear and well-lit
- Higher resolution images generally work better

## Cost Information

OpenRouter charges based on the model and tokens used. Vision models typically cost:

- Gemini Flash 1.5: ~$0.0001-0.0003 per image
- Claude 3.5 Sonnet: ~$0.003-0.015 per image
- GPT-4o: ~$0.0025-0.01 per image

Check current pricing at: https://openrouter.ai/models

## License

MIT License - feel free to use and modify as needed.

## Contributing

Contributions welcome! Feel free to open issues or submit pull requests.
