#!/usr/bin/env python3
"""
OCR Library - Core functionality shared across OCR scripts.
Provides image encoding, OCR API calls, and output handling.
"""

import base64
import logging
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from functools import wraps
from io import BytesIO
from pathlib import Path

import pyperclip
import requests
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

# Configuration constants
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Determine which API to use (prefer OpenAI if key is set)
# This can be overridden by set_api_provider()
USE_OPENAI = bool(OPENAI_API_KEY)
API_KEY = OPENAI_API_KEY if USE_OPENAI else OPENROUTER_API_KEY
DEFAULT_MODEL = OPENAI_MODEL if USE_OPENAI else OPENROUTER_MODEL
API_URL = OPENAI_API_URL if USE_OPENAI else OPENROUTER_API_URL
API_NAME = "OpenAI" if USE_OPENAI else "OpenRouter"

# Image processing constants
IMAGE_ENCODE_QUALITY = 95  # High quality for OCR accuracy
API_TIMEOUT_SECONDS = 60   # Generous timeout for vision models

# Security constants
MAX_IMAGE_SIZE_MB = 20  # Maximum image file size
MAX_IMAGE_DIMENSION = 8000  # Maximum image dimension in pixels
MAX_EXCALIDRAW_SIZE_MB = 10  # Maximum Excalidraw file size

# Setup logging
def setup_logging(log_level=logging.INFO):
    """Configure logging for security events and debugging."""
    log_dir = Path.home() / '.ocr' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / 'ocr.log'),
            logging.StreamHandler(sys.stderr) if os.getenv('DEBUG') else logging.NullHandler()
        ]
    )

logger = logging.getLogger(__name__)
setup_logging()

# Thread safety for API provider switching
import threading
_config_lock = threading.Lock()

def set_api_provider(provider: str):
    """
    Override the default API provider selection (thread-safe).
    
    Args:
        provider: Either "openai" or "openrouter"
    
    Raises:
        ValueError: If provider is invalid or API key not available
    """
    global API_KEY, DEFAULT_MODEL, API_URL, API_NAME, USE_OPENAI
    
    with _config_lock:  # Thread-safe global state mutation
        provider = provider.lower()
        
        if provider == "openai":
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set. Cannot use OpenAI provider.")
            API_KEY = OPENAI_API_KEY
            DEFAULT_MODEL = OPENAI_MODEL
            API_URL = OPENAI_API_URL
            API_NAME = "OpenAI"
            USE_OPENAI = True
            logger.info("Switched to OpenAI provider")
        elif provider == "openrouter":
            if not OPENROUTER_API_KEY:
                raise ValueError("OPENROUTER_API_KEY not set. Cannot use OpenRouter provider.")
            API_KEY = OPENROUTER_API_KEY
            DEFAULT_MODEL = OPENROUTER_MODEL
            API_URL = OPENROUTER_API_URL
            API_NAME = "OpenRouter"
            USE_OPENAI = False
            logger.info("Switched to OpenRouter provider")
        else:
            raise ValueError(f"Invalid provider: {provider}. Must be 'openai' or 'openrouter'.")


def validate_output_path(output_path: str | Path, allow_absolute: bool = True, allow_temp: bool = False) -> Path:
    """
    Validate output path to prevent path traversal attacks.
    
    Args:
        output_path: Path to validate
        allow_absolute: Whether to allow absolute paths outside CWD
        allow_temp: Whether to allow temporary directory paths (needed for temp files)
    
    Returns:
        Validated Path object
        
    Raises:
        ValueError: If path is unsafe
    """
    path = Path(output_path)
    
    # Check for path traversal attempts
    if '..' in str(path):
        logger.warning(f"Path traversal attempt detected: {output_path}")
        raise ValueError("Path traversal detected: '..' not allowed in paths")
    
    # Resolve to absolute path
    resolved = path.resolve()
    
    # Allow temp directory paths if requested
    if allow_temp:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if str(resolved).startswith(str(temp_dir)):
            return resolved
    
    # If not allowing absolute paths, ensure it's relative to CWD
    if not allow_absolute:
        cwd = Path.cwd().resolve()
        try:
            resolved.relative_to(cwd)
        except ValueError:
            logger.warning(f"Path outside CWD rejected: {resolved}")
            raise ValueError(f"Path {resolved} is outside current directory {cwd}")
    
    # Block sensitive system directories
    sensitive_dirs = ['/etc', '/usr', '/bin', '/sbin', '/boot', '/sys', '/proc']
    for sensitive in sensitive_dirs:
        if str(resolved).startswith(sensitive):
            logger.error(f"Attempt to write to sensitive directory: {resolved}")
            raise ValueError(f"Writing to {sensitive} is not allowed")
    
    return resolved


def rate_limit(max_calls: int = 10, period: int = 60):
    """
    Rate limit decorator for API calls.
    
    Args:
        max_calls: Maximum number of calls allowed
        period: Time period in seconds
    """
    calls = []
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            # Remove old calls
            calls[:] = [c for c in calls if c > now - period]
            
            if len(calls) >= max_calls:
                sleep_time = period - (now - calls[0])
                if sleep_time > 0:
                    logger.info(f"Rate limit reached. Waiting {sleep_time:.1f}s...")
                    print(f"Rate limit reached. Waiting {sleep_time:.1f}s...", 
                          file=sys.stderr)
                    time.sleep(sleep_time)
                    calls.clear()
            
            calls.append(time.time())
            return func(*args, **kwargs)
        return wrapper
    return decorator


def encode_image_to_base64(image: Image.Image) -> str:
    """
    Convert PIL Image to base64-encoded JPEG string.
    
    Args:
        image: PIL Image object
    
    Returns:
        Base64-encoded JPEG image string
    
    Note:
        Converts RGBA/LA/P images to RGB with white background for compatibility.
        Resizes very large images to prevent API payload issues.
    """
    buffered = BytesIO()
    
    # Convert to RGB if necessary (for PNG with transparency, etc.)
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None)
        image = background
    
    # Resize if image is too large (helps prevent API payload issues)
    max_dimension = 4096  # Reasonable size for vision models
    if image.width > max_dimension or image.height > max_dimension:
        logger.info(f"Resizing large image from {image.width}x{image.height}")
        ratio = min(max_dimension / image.width, max_dimension / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        logger.info(f"Resized to {image.width}x{image.height}")
    
    image.save(buffered, format="JPEG", quality=IMAGE_ENCODE_QUALITY)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


@rate_limit(max_calls=10, period=60)  # 10 requests per minute
def perform_ocr(image_base64: str, model: str | None = None) -> str:
    """
    Send image to OpenAI or OpenRouter API for OCR using vision models.
    
    Args:
        image_base64: Base64-encoded image string
        model: Model to use (optional, uses OPENAI_MODEL or OPENROUTER_MODEL env var)
    
    Returns:
        Extracted text from the image
    
    Raises:
        ValueError: If neither OPENAI_API_KEY nor OPENROUTER_API_KEY is set
        Exception: If API request fails or returns an error
    """
    if not API_KEY:
        logger.error("No API key set")
        raise ValueError(
            "Neither OPENAI_API_KEY nor OPENROUTER_API_KEY found. "
            "Please set one in your .env file or environment variables."
        )
    
    model = model or DEFAULT_MODEL
    logger.info(f"Performing OCR with {API_NAME} model: {model}")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
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
        # Create session with retries
        session = requests.Session()
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            raise_on_status=False  # Let us handle status codes
        )
        
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        logger.info(f"Sending OCR request to {API_NAME} (may retry up to 5 times on errors)...")
        response = session.post(
            API_URL, 
            headers=headers, 
            json=payload, 
            timeout=API_TIMEOUT_SECONDS,
            verify=True  # Explicit HTTPS verification
        )
        response.raise_for_status()
        
        data = response.json()
        
        if "error" in data:
            logger.error(f"API error: {data['error']}")
            raise Exception(f"{API_NAME} API error: {data['error']}")
        
        logger.info("OCR completed successfully")
        return data["choices"][0]["message"]["content"].strip()
    
    except requests.exceptions.Timeout:
        logger.error("API request timed out")
        raise Exception("API request timed out after 60 seconds")
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {str(e)}")
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
        # Validate output path for security
        safe_path = validate_output_path(output_path)
        logger.info(f"Saving output to: {safe_path.name}")
        
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✓ Text saved to {output_path}", file=sys.stderr)
    else:
        print(text)
    
    if to_clipboard:
        copy_to_clipboard(text)
        print("✓ Text copied to clipboard", file=sys.stderr)


@contextmanager
def temp_file(suffix: str = "", secure: bool = True):
    """
    Context manager for temporary files with automatic cleanup and secure permissions.
    
    Args:
        suffix: File suffix/extension (e.g., '.svg', '.png')
        secure: Whether to use secure file creation (restrictive permissions)
    
    Yields:
        Path to temporary file
    
    Note:
        File is automatically deleted when context exits, even if exception occurs.
        Secure mode creates files with 0o600 permissions (owner read/write only).
    
    Example:
        with temp_file('.png') as png_path:
            # Use png_path
            pass
        # File automatically cleaned up
    """
    if secure:
        # Create with mode 0o600 (owner read/write only)
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        os.chmod(path, 0o600)
    else:
        temp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        path = temp.name
        temp.close()
    
    try:
        yield path
    finally:
        try:
            if os.path.exists(path):
                # Securely wipe file before deletion for sensitive data (< 100MB)
                if secure and os.path.getsize(path) < 100 * 1024 * 1024:
                    try:
                        with open(path, 'r+b') as f:
                            size = os.path.getsize(path)
                            if size > 0:
                                f.write(b'\x00' * size)
                                f.flush()
                                os.fsync(f.fileno())
                    except Exception:
                        pass  # Best effort wipe
                os.unlink(path)
        except OSError:
            pass  # Best effort cleanup


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
