#!/usr/bin/env python3
"""
OCR Library - Core functionality shared across OCR scripts.
Provides image encoding, OCR API calls, and output handling.
"""

import base64
import os
import sys
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pyperclip
import requests
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

# Configuration constants
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Image processing constants
IMAGE_ENCODE_QUALITY = 95  # High quality for OCR accuracy
API_TIMEOUT_SECONDS = 60   # Generous timeout for vision models


def encode_image_to_base64(image: Image.Image) -> str:
    """
    Convert PIL Image to base64-encoded JPEG string.
    
    Args:
        image: PIL Image object
    
    Returns:
        Base64-encoded JPEG image string
    
    Note:
        Converts RGBA/LA/P images to RGB with white background for compatibility.
    """
    buffered = BytesIO()
    
    # Convert to RGB if necessary (for PNG with transparency, etc.)
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None)
        image = background
    
    image.save(buffered, format="JPEG", quality=IMAGE_ENCODE_QUALITY)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def perform_ocr(image_base64: str, model: str | None = None) -> str:
    """
    Send image to OpenRouter API for OCR using vision models.
    
    Args:
        image_base64: Base64-encoded image string
        model: OpenRouter model to use (optional, uses OPENROUTER_MODEL env var)
    
    Returns:
        Extracted text from the image
    
    Raises:
        ValueError: If OPENROUTER_API_KEY is not set
        Exception: If API request fails or returns an error
    """
    if not OPENROUTER_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY not found. "
            "Please set it in your .env file or environment variables."
        )
    
    model = model or OPENROUTER_MODEL
    
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
                        "text": (
                            "Please extract all text from this image. "
                            "If it contains handwriting, transcribe it as accurately as possible. "
                            "Return only the extracted text, without any additional commentary."
                        ),
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
        response = requests.post(
            OPENROUTER_API_URL, 
            headers=headers, 
            json=payload, 
            timeout=API_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        
        data = response.json()
        
        if "error" in data:
            raise Exception(f"OpenRouter API error: {data['error']}")
        
        return data["choices"][0]["message"]["content"].strip()
    
    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {str(e)}")


def copy_to_clipboard(text: str) -> None:
    """
    Copy text to system clipboard.
    
    Args:
        text: Text to copy
    
    Raises:
        Exception: If clipboard operation fails
    """
    try:
        pyperclip.copy(text)
    except Exception as e:
        raise Exception(f"Failed to copy to clipboard: {str(e)}")


def save_output(text: str, output_path: str | None = None, to_clipboard: bool = False) -> None:
    """
    Save or print OCR output, optionally copying to clipboard.
    
    Args:
        text: Extracted text to output
        output_path: File path to save to (optional, prints to stdout if not provided)
        to_clipboard: Whether to also copy to clipboard
    
    Note:
        Prints status messages to stderr, actual text to stdout if not saving to file.
    """
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✓ Text saved to {output_path}", file=sys.stderr)
    else:
        print(text)
    
    if to_clipboard:
        copy_to_clipboard(text)
        print("✓ Text copied to clipboard", file=sys.stderr)


@contextmanager
def temp_file(suffix: str = ""):
    """
    Context manager for temporary files with automatic cleanup.
    
    Args:
        suffix: File suffix/extension (e.g., '.svg', '.png')
    
    Yields:
        Path to temporary file
    
    Note:
        File is automatically deleted when context exits, even if exception occurs.
    
    Example:
        with temp_file('.png') as png_path:
            # Use png_path
            pass
        # File automatically cleaned up
    """
    temp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = temp.name
    temp.close()
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def get_excalidraw_output_path(input_path: Path, output_arg: str | None) -> Path:
    """
    Determine output file path for Excalidraw processing.
    
    Args:
        input_path: Path to input Excalidraw file
        output_arg: User-specified output path (optional)
    
    Returns:
        Path object for output file
    
    Note:
        If output_arg is None, automatically generates clean filename:
        - "Drawing.excalidraw.md" → "Drawing.md"
        - "Diagram.excalidraw" → "Diagram.txt"
    """
    if output_arg:
        return Path(output_arg)
    
    filename = input_path.name
    if '.excalidraw.' in filename:
        output_filename = filename.replace('.excalidraw.', '.')
    elif filename.endswith('.excalidraw'):
        output_filename = filename.replace('.excalidraw', '.txt')
    else:
        output_filename = input_path.stem + '.txt'
    
    return input_path.parent / output_filename
