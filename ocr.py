#!/usr/bin/env python3
"""
OCR Script using OpenRouter API
Extracts text from handwritten images using AI vision models.
Supports both image files and clipboard input.
"""

import argparse
import base64
import os
import sys
from io import BytesIO
from pathlib import Path

import pyperclip
import requests
from dotenv import load_dotenv
from PIL import Image, ImageGrab

# Load environment variables
load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Supported image formats
SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def encode_image_to_base64(image: Image.Image) -> str:
    """Convert PIL Image to base64 string."""
    buffered = BytesIO()
    # Convert to RGB if necessary (for PNG with transparency, etc.)
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None)
        image = background
    image.save(buffered, format="JPEG", quality=95)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def load_image_from_file(file_path: str) -> Image.Image:
    """Load image from file path."""
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format. Supported: {', '.join(SUPPORTED_FORMATS)}")
    
    return Image.open(path)


def load_image_from_clipboard() -> Image.Image:
    """Load image from clipboard with validation."""
    image = ImageGrab.grabclipboard()
    
    if image is None:
        raise ValueError(
            "No image found in clipboard. "
            "Please copy an image to clipboard first (e.g., take a screenshot)."
        )
    
    if not isinstance(image, Image.Image):
        raise ValueError(
            f"Clipboard content is not an image. Found: {type(image).__name__}. "
            "Please copy an image, not a file path or text."
        )
    
    return image


def copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard."""
    try:
        pyperclip.copy(text)
    except Exception as e:
        raise Exception(f"Failed to copy to clipboard: {str(e)}")


def perform_ocr(image_base64: str, model: str | None = None, custom_prompt: str | None = None) -> str:
    """
    Send image to OpenRouter API for OCR.
    
    Args:
        image_base64: Base64 encoded image string
        model: OpenRouter model to use (optional, uses env var default)
        custom_prompt: Custom instruction for AI (optional, uses default prompt)
    
    Returns:
        Extracted text from the image
    """
    if not OPENROUTER_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY not found. "
            "Please set it in your .env file or environment variables."
        )
    
    model = model or OPENROUTER_MODEL
    
    # Use custom prompt if provided, otherwise use default
    prompt = custom_prompt or (
        "Please extract all text from this image. "
        "If it contains handwriting, transcribe it as accurately as possible. "
        "Return only the extracted text, without any additional commentary."
    )
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
                    },
                ],
            }
        ],
    }
    
    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        
        if "error" in data:
            raise Exception(f"OpenRouter API error: {data['error']}")
        
        return data["choices"][0]["message"]["content"].strip()
    
    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from handwritten images using AI OCR (OpenRouter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s image.png                                    # Process image file
  %(prog)s --clipboard                                  # Process clipboard image, copy result back
  %(prog)s image.jpg --model MODEL                      # Use specific OpenRouter model
  %(prog)s -c -o output.txt                             # Save clipboard OCR to file
  %(prog)s diagram.png -p "Extract as Mermaid syntax"  # Custom prompt for diagrams
  %(prog)s math.jpg -p "Convert to LaTeX equations"    # Extract math notation

Environment Variables:
  OPENROUTER_API_KEY    Your OpenRouter API key (required)
  OPENROUTER_MODEL      Default model to use (default: google/gemini-flash-1.5)
        """
    )
    
    parser.add_argument(
        "image",
        nargs="?",
        help="Path to image file (PNG, JPG, JPEG, WEBP, GIF)",
    )
    parser.add_argument(
        "-c", "--clipboard",
        action="store_true",
        help="Read image from clipboard and copy result back to clipboard",
    )
    parser.add_argument(
        "-m", "--model",
        help="OpenRouter model to use (overrides OPENROUTER_MODEL env var)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Save extracted text to file (disables clipboard copy)",
    )
    parser.add_argument(
        "-p", "--prompt",
        help="Custom instruction for the AI (e.g., 'Extract as Mermaid diagram')",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Show popular vision models available on OpenRouter",
    )
    parser.add_argument(
        "--no-clipboard-copy",
        action="store_true",
        help="Don't copy result to clipboard when using --clipboard mode",
    )
    
    args = parser.parse_args()
    
    # Show model list if requested
    if args.list_models:
        print("Popular Vision Models on OpenRouter:")
        print("  - google/gemini-flash-1.5 (fast, affordable)")
        print("  - google/gemini-pro-1.5 (high quality)")
        print("  - anthropic/claude-3.5-sonnet (excellent accuracy)")
        print("  - openai/gpt-4o (strong performance)")
        print("  - qwen/qwen-2-vl-72b-instruct (open source)")
        print("\nSee https://openrouter.ai/models for full list")
        return 0
    
    # Validate input arguments
    if not args.clipboard and not args.image:
        parser.error("Either provide an image file or use --clipboard")
    
    if args.clipboard and args.image:
        parser.error("Cannot use both --clipboard and image file")
    
    try:
        # Load image
        print("Loading image...", file=sys.stderr)
        if args.clipboard:
            image = load_image_from_clipboard()
            print("✓ Image loaded from clipboard", file=sys.stderr)
        else:
            image = load_image_from_file(args.image)
            print(f"✓ Image loaded from {args.image}", file=sys.stderr)
        
        # Convert to base64
        print("Encoding image...", file=sys.stderr)
        image_base64 = encode_image_to_base64(image)
        print("✓ Image encoded", file=sys.stderr)
        
        # Perform OCR
        model = args.model or OPENROUTER_MODEL
        print(f"Performing OCR with {model}...", file=sys.stderr)
        extracted_text = perform_ocr(image_base64, model, args.prompt)
        print("✓ OCR completed\n", file=sys.stderr)
        
        # Output results
        if args.output:
            # Save to file
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(extracted_text)
            print(f"✓ Text saved to {args.output}", file=sys.stderr)
        else:
            # Print to stdout
            print(extracted_text)
        
        # Copy to clipboard if using clipboard mode (unless disabled or saving to file)
        if args.clipboard and not args.output and not args.no_clipboard_copy:
            copy_to_clipboard(extracted_text)
            print("✓ Text copied to clipboard", file=sys.stderr)
        
        return 0
    
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
