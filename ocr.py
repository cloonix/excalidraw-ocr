#!/usr/bin/env python3
"""
OCR Script using OpenAI/OpenRouter API
Extracts text from handwritten images using AI vision models.
Supports both image files and clipboard input.
"""

import argparse
import logging
import sys
from pathlib import Path

from PIL import Image, ImageGrab

# Import shared OCR library functions
from ocr_lib import (
    encode_image_to_base64, 
    perform_ocr, 
    save_output, 
    copy_to_clipboard,
    set_api_provider,
    DEFAULT_MODEL,
    API_NAME,
    MAX_IMAGE_SIZE_MB,
    MAX_IMAGE_DIMENSION,
    logger
)

# Supported image formats
SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def load_image_from_file(file_path: str) -> Image.Image:
    """
    Load image from file path with security validation.
    
    Args:
        file_path: Path to image file
    
    Returns:
        PIL Image object
    
    Raises:
        FileNotFoundError: If image file doesn't exist
        ValueError: If image format is not supported or file is too large
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    
    # Check file size before loading
    file_size = path.stat().st_size
    max_size_bytes = MAX_IMAGE_SIZE_MB * 1024 * 1024
    
    if file_size > max_size_bytes:
        logger.warning(f"Image file too large: {file_size / 1024 / 1024:.2f}MB")
        raise ValueError(
            f"Image file too large: {file_size / 1024 / 1024:.2f}MB "
            f"(max: {MAX_IMAGE_SIZE_MB}MB)"
        )
    
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format. Supported: {', '.join(SUPPORTED_FORMATS)}")
    
    # Load image
    logger.info(f"Loading image: {path.name} ({file_size / 1024:.2f}KB)")
    image = Image.open(path)
    
    # Validate image dimensions
    if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
        logger.warning(f"Image dimensions too large: {image.width}x{image.height}")
        raise ValueError(
            f"Image dimensions too large: {image.width}x{image.height} "
            f"(max: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION})"
        )
    
    # Verify it's actually an image (not just extension spoofing)
    try:
        image.verify()
        # Reopen after verify (verify() closes the file)
        image = Image.open(path)
    except Exception as e:
        logger.error(f"Image verification failed: {str(e)}")
        raise ValueError(f"File is not a valid image: {str(e)}")
    
    return image


def load_image_from_clipboard() -> Image.Image:
    """
    Load image from clipboard with validation.
    
    Returns:
        PIL Image object from clipboard
    
    Raises:
        ValueError: If no image found in clipboard or clipboard content is not an image
    """
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


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from handwritten images using AI OCR (OpenAI/OpenRouter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s image.png                    # Process image file
  %(prog)s --clipboard                  # Process clipboard image, copy result back
  %(prog)s image.jpg --model MODEL      # Use specific model
  %(prog)s image.png --provider openrouter  # Use OpenRouter instead of OpenAI
  %(prog)s -c -o output.txt             # Save clipboard OCR to file

Environment Variables:
  OPENAI_API_KEY        Your OpenAI API key (preferred if set)
  OPENAI_MODEL          OpenAI model to use (default: gpt-4o)
  OPENROUTER_API_KEY    Your OpenRouter API key (fallback)
  OPENROUTER_MODEL      OpenRouter model to use (default: google/gemini-flash-1.5)
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
        help="Model to use (overrides default env var model)",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "openrouter"],
        help="API provider to use (default: auto-detect based on API keys)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Save extracted text to file (disables clipboard copy)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Show popular vision models",
    )
    parser.add_argument(
        "--no-clipboard-copy",
        action="store_true",
        help="Don't copy result to clipboard when using --clipboard mode",
    )
    
    args = parser.parse_args()
    
    # Override API provider if specified
    if args.provider:
        try:
            set_api_provider(args.provider)
        except ValueError as e:
            logger.error(f"Provider configuration error: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1
    
    # Show model list if requested
    if args.list_models:
        print(f"Currently using: {API_NAME}")
        print("\nPopular Vision Models:")
        print("  OpenAI:")
        print("    - gpt-4o (best, most capable)")
        print("    - gpt-4o-mini (fast, affordable)")
        print("  OpenRouter:")
        print("    - google/gemini-flash-1.5 (fast, affordable)")
        print("    - google/gemini-pro-1.5 (high quality)")
        print("    - anthropic/claude-3.5-sonnet (excellent accuracy)")
        print("    - openai/gpt-4o (strong performance)")
        print("    - qwen/qwen-2-vl-72b-instruct (open source)")
        print("\nSet OPENAI_API_KEY to use OpenAI, or OPENROUTER_API_KEY for OpenRouter")
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
        model = args.model or DEFAULT_MODEL
        print(f"Performing OCR with {API_NAME} ({model})...", file=sys.stderr)
        extracted_text = perform_ocr(image_base64, model)
        print("✓ OCR completed\n", file=sys.stderr)
        
        # Output results
        to_clipboard = args.clipboard and not args.output and not args.no_clipboard_copy
        save_output(extracted_text, args.output, to_clipboard)
        
        return 0
    
    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        print(f"Error: File not found", file=sys.stderr)
        return 1
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Unexpected error occurred")
        print(f"Error: An unexpected error occurred. Check logs for details.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
