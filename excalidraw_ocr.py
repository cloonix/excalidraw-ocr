#!/usr/bin/env python3
"""
Excalidraw OCR Script
Extracts text from Excalidraw drawings using AI OCR via OpenRouter.
Requires cairo system libraries - run ./install_cairo.sh first.
"""

import argparse
import hashlib
import json
import math
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

# Import OCR functions from shared library
from ocr_lib import (
    encode_image_to_base64, 
    perform_ocr, 
    copy_to_clipboard,
    temp_file,
    get_excalidraw_output_path,
    validate_output_path,
    set_api_provider,
    MAX_EXCALIDRAW_SIZE_MB,
    logger
)
from PIL import Image

# Import lzstring for decompression
try:
    import lzstring
    HAS_LZSTRING = True
except ImportError:
    HAS_LZSTRING = False

# Configuration constants
SVG_RENDER_SCALE = 2  # 2x scale for better OCR accuracy
MAX_ELEMENTS = 10000  # Maximum elements in Excalidraw to prevent DoS
MAX_DECOMPRESSED_SIZE_MB = 50  # Maximum decompressed JSON size

# Watch mode configuration
WATCH_DEBOUNCE_SECONDS = 1.0  # Minimum time between processing same file
WATCH_FILE_STABILITY_MS = 500  # Wait time to check file size stability
WATCH_MAX_CONCURRENT = 3  # Maximum concurrent file processing
WATCH_MAX_DEBOUNCE_ENTRIES = 1000  # Maximum debounce entries before cleanup
WATCH_EXTENSIONS = {'.excalidraw.md', '.excalidraw'}  # File extensions to watch
WATCH_IGNORE_PATTERNS = {'.swp', '~', '.tmp', '.bak'}  # Temp file patterns to ignore

# Stabilization delay: wait for file to stop changing before processing
# This prevents processing files that are being actively edited (e.g., during meetings)
try:
    WATCH_STABILIZATION_DELAY_MINUTES = int(os.environ.get('STABILIZATION_DELAY_MINUTES', '15'))
except ValueError:
    logger.warning("Invalid STABILIZATION_DELAY_MINUTES, using default 15")
    WATCH_STABILIZATION_DELAY_MINUTES = 15
WATCH_STABILIZATION_CHECK_INTERVAL = 10  # Check for ready files every N seconds

# Try to import cairosvg
try:
    import cairosvg
    HAS_CAIROSVG = True
except ImportError:
    HAS_CAIROSVG = False

# Try to import watchdog for watch mode
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


def get_content_hash(compressed_data: str) -> str:
    """Generate SHA256 hash of Excalidraw content."""
    return hashlib.sha256(compressed_data.encode()).hexdigest()[:16]


def read_output_metadata(output_path: Path) -> dict:
    """Extract metadata from YAML frontmatter if exists."""
    if not output_path.exists():
        return {}
    
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            
            # Check if file starts with YAML frontmatter
            if first_line != '---':
                return {}
            
            metadata = {}
            for line in f:
                line = line.strip()
                
                # End of frontmatter
                if line == '---':
                    break
                
                # Parse YAML key-value pairs
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'excalidraw-ocr-hash':
                        metadata['hash'] = value
                    elif key == 'excalidraw-ocr-source':
                        metadata['source'] = value
                    elif key == 'excalidraw-ocr-date':
                        metadata['date'] = value
            
            return metadata
    except Exception:
        return {}


def should_reprocess(output_path: Path, current_hash: str, force: bool = False) -> tuple[bool, str]:
    """
    Check if file needs reprocessing.
    Returns (should_process, reason).
    """
    if force:
        return True, "forced reprocessing"
    
    if not output_path.exists():
        return True, "output file doesn't exist"
    
    metadata = read_output_metadata(output_path)
    
    if 'hash' not in metadata:
        return True, "no hash metadata found"
    
    if metadata['hash'] != current_hash:
        return True, "content has changed"
    
    return False, f"output is up-to-date (hash: {current_hash})"


def clean_markdown_wrapper(text: str) -> str:
    """
    Remove wrapping markdown code blocks if present.
    Removes outer ```markdown or ``` blocks, keeps inner code blocks like ```mermaid.
    """
    text = text.strip()
    lines = text.split('\n')
    
    if not lines:
        return text
    
    # Remove wrapping ```markdown or ``` from start
    if lines[0].strip().startswith('```'):
        lines = lines[1:]
    
    # Remove wrapping ``` from end
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    
    return '\n'.join(lines).strip()


def save_with_metadata(output_path: Path, text: str, content_hash: str, source_file: str):
    """Save output with YAML frontmatter metadata."""
    # Validate output path for security
    safe_path = validate_output_path(output_path)
    logger.info(f"Saving output to: {safe_path.name}")
    
    # Create YAML frontmatter (only hash is needed for caching)
    frontmatter = [
        "---",
        f"excalidraw-ocr-hash: {content_hash}",
        "---",
        "",  # Empty line after frontmatter
    ]
    
    with open(safe_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(frontmatter))
        f.write(text.strip())  # Strip to avoid extra whitespace
        f.write('\n')  # End with newline


def extract_compressed_data(excalidraw_file_path: Path) -> str:
    """Extract compressed JSON data from Excalidraw markdown file with size validation."""
    try:
        # Check file size first
        file_size = excalidraw_file_path.stat().st_size
        max_size_bytes = MAX_EXCALIDRAW_SIZE_MB * 1024 * 1024
        
        if file_size > max_size_bytes:
            logger.warning(f"Excalidraw file too large: {file_size / 1024 / 1024:.2f}MB")
            raise ValueError(
                f"Excalidraw file too large: {file_size / 1024 / 1024:.2f}MB "
                f"(max: {MAX_EXCALIDRAW_SIZE_MB}MB)"
            )
        
        logger.info(f"Reading Excalidraw file: {excalidraw_file_path.name} ({file_size / 1024:.2f}KB)")
        
        with open(excalidraw_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the compressed-json block
        pattern = r'```compressed-json\s*([\s\S]*?)\s*```'
        match = re.search(pattern, content)
        
        if not match:
            # Try to give helpful error message
            if '```json' in content:
                raise ValueError(
                    "Found ```json block but expected ```compressed-json. "
                    "Is this an Excalidraw file?"
                )
            raise ValueError(
                "No compressed-json block found. Not a valid Excalidraw file?"
            )
        
        # Extract and clean the compressed data
        compressed_data = match.group(1)
        compressed_data = ''.join(compressed_data.split())  # Remove all whitespace
        
        return compressed_data
        
    except FileNotFoundError:
        raise FileNotFoundError(f"Excalidraw file not found: {excalidraw_file_path}")
    except Exception as e:
        raise Exception(f"Failed to extract compressed data: {str(e)}")


def decompress_excalidraw(compressed_data: str) -> dict:
    """
    Decompress base64-compressed Excalidraw JSON data using Python lzstring.
    
    Args:
        compressed_data: Base64-compressed Excalidraw JSON data
    
    Returns:
        Decompressed Excalidraw data as dict
    
    Raises:
        Exception: If decompression fails or data is invalid
    """
    if not HAS_LZSTRING:
        raise ImportError(
            "lzstring package not found. Install it with:\n"
            "  pip install lzstring"
        )
    
    try:
        # Decompress using lzstring
        decompressed = lzstring.LZString().decompressFromBase64(compressed_data)
        
        if not decompressed:
            raise ValueError("Decompression failed - no data returned")
        
        # Parse JSON
        excalidraw_data = json.loads(decompressed)
        
        # Validate structure
        if not isinstance(excalidraw_data, dict):
            raise ValueError("Invalid Excalidraw data structure")
        
        if not isinstance(excalidraw_data.get('elements'), list):
            raise ValueError("Excalidraw data missing elements array")
        
        # Size limits
        json_size = len(decompressed)
        max_size = MAX_DECOMPRESSED_SIZE_MB * 1024 * 1024
        if json_size > max_size:
            raise ValueError(
                f"Decompressed data too large: {json_size / 1024 / 1024:.2f}MB "
                f"(max: {MAX_DECOMPRESSED_SIZE_MB}MB)"
            )
        
        # Element count limit
        if len(excalidraw_data['elements']) > MAX_ELEMENTS:
            raise ValueError(
                f"Too many elements: {len(excalidraw_data['elements'])} "
                f"(max: {MAX_ELEMENTS})"
            )
        
        return excalidraw_data
        
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse decompressed JSON: {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to decompress Excalidraw data: {str(e)}")


def escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def create_svg_from_excalidraw(excalidraw_data: dict) -> tuple[str, int, int, int]:
    """
    Generate SVG from Excalidraw JSON data (Python implementation).
    
    Args:
        excalidraw_data: Decompressed Excalidraw data dict
    
    Returns:
        Tuple of (svg_string, width, height, element_count)
    """
    elements = excalidraw_data.get('elements', [])
    
    if not elements:
        raise ValueError("No elements found in Excalidraw data")
    
    # Calculate bounding box
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')
    
    for element in elements:
        if element.get('isDeleted'):
            continue
        
        x = element.get('x')
        y = element.get('y')
        if x is not None and y is not None:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + element.get('width', 0))
            max_y = max(max_y, y + element.get('height', 0))
    
    # Add padding
    padding = 40
    min_x -= padding
    min_y -= padding
    max_x += padding
    max_y += padding
    
    width = int(max_x - min_x)
    height = int(max_y - min_y)
    
    # Start SVG
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        '<g>'
    ]
    
    # Render each element
    element_count = 0
    for element in elements:
        if element.get('isDeleted'):
            continue
        
        element_count += 1
        elem_type = element.get('type')
        x = element.get('x', 0) - min_x
        y = element.get('y', 0) - min_y
        stroke_color = element.get('strokeColor', '#000000')
        fill_color = 'none' if element.get('backgroundColor') == 'transparent' else element.get('backgroundColor', 'none')
        stroke_width = element.get('strokeWidth', 1)
        opacity = element.get('opacity', 100) / 100
        
        # Stroke style
        stroke_dasharray = ''
        if element.get('strokeStyle') == 'dashed':
            stroke_dasharray = ' stroke-dasharray="12,8"'
        elif element.get('strokeStyle') == 'dotted':
            stroke_dasharray = ' stroke-dasharray="2,6"'
        
        # Render by type
        if elem_type == 'freedraw':
            points = element.get('points', [])
            if len(points) > 1:
                path = f'M {x + points[0][0]} {y + points[0][1]}'
                for px, py in points[1:]:
                    path += f' L {x + px} {y + py}'
                svg_parts.append(
                    f'<path d="{path}" stroke="{stroke_color}" stroke-width="{stroke_width}" '
                    f'fill="none" opacity="{opacity}"{stroke_dasharray}/>'
                )
        
        elif elem_type in ('line', 'arrow'):
            points = element.get('points', [])
            if len(points) > 1:
                path = f'M {x + points[0][0]} {y + points[0][1]}'
                for px, py in points[1:]:
                    path += f' L {x + px} {y + py}'
                svg_parts.append(
                    f'<path d="{path}" stroke="{stroke_color}" stroke-width="{stroke_width}" '
                    f'fill="none" opacity="{opacity}"{stroke_dasharray}/>'
                )
                
                # Arrow head
                if elem_type == 'arrow' and len(points) >= 2:
                    p1 = points[-2]
                    p2 = points[-1]
                    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                    arrow_length = 15
                    arrow_angle = math.pi / 6
                    
                    x2 = x + p2[0]
                    y2 = y + p2[1]
                    
                    arrow_path = (
                        f'M {x2} {y2} '
                        f'L {x2 - arrow_length * math.cos(angle - arrow_angle)} '
                        f'{y2 - arrow_length * math.sin(angle - arrow_angle)} '
                        f'M {x2} {y2} '
                        f'L {x2 - arrow_length * math.cos(angle + arrow_angle)} '
                        f'{y2 - arrow_length * math.sin(angle + arrow_angle)}'
                    )
                    svg_parts.append(
                        f'<path d="{arrow_path}" stroke="{stroke_color}" '
                        f'stroke-width="{stroke_width}" fill="none" opacity="{opacity}"/>'
                    )
        
        elif elem_type == 'rectangle':
            elem_width = element.get('width', 0)
            elem_height = element.get('height', 0)
            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{elem_width}" height="{elem_height}" '
                f'stroke="{stroke_color}" stroke-width="{stroke_width}" fill="{fill_color}" '
                f'opacity="{opacity}"{stroke_dasharray}/>'
            )
        
        elif elem_type == 'ellipse':
            elem_width = element.get('width', 0)
            elem_height = element.get('height', 0)
            cx = x + elem_width / 2
            cy = y + elem_height / 2
            rx = elem_width / 2
            ry = elem_height / 2
            svg_parts.append(
                f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
                f'stroke="{stroke_color}" stroke-width="{stroke_width}" fill="{fill_color}" '
                f'opacity="{opacity}"{stroke_dasharray}/>'
            )
        
        elif elem_type == 'text':
            text = element.get('text', '')
            if text:
                font_size = element.get('fontSize', 20)
                font_family = element.get('fontFamily', 'Arial, sans-serif')
                lines = text.split('\n')
                line_height = font_size * 1.2
                
                for i, line in enumerate(lines):
                    text_y = y + font_size + (i * line_height)
                    svg_parts.append(
                        f'<text x="{x}" y="{text_y}" font-size="{font_size}" '
                        f'font-family="{font_family}" fill="{stroke_color}" '
                        f'opacity="{opacity}">{escape_xml(line)}</text>'
                    )
    
    svg_parts.append('</g></svg>')
    
    return ''.join(svg_parts), width, height, element_count


def render_excalidraw_to_svg(compressed_data: str, output_svg_path: str) -> dict:
    """
    Decompress and render Excalidraw to SVG using Python (no Node.js required).
    
    Args:
        compressed_data: Base64-compressed Excalidraw JSON data
        output_svg_path: Path where SVG file should be written
    
    Returns:
        Dict with render info (width, height, elementCount, success, outputPath)
    
    Raises:
        Exception: If rendering fails
    """
    # Validate SVG output path for security
    safe_svg_path = validate_output_path(output_svg_path, allow_temp=True)
    logger.info(f"Rendering Excalidraw to SVG: {safe_svg_path.name}")
    
    try:
        # Decompress Excalidraw data
        excalidraw_data = decompress_excalidraw(compressed_data)
        
        # Generate SVG
        svg, width, height, element_count = create_svg_from_excalidraw(excalidraw_data)
        
        # Write SVG to file
        with open(safe_svg_path, 'w', encoding='utf-8') as f:
            f.write(svg)
        
        return {
            'success': True,
            'width': width,
            'height': height,
            'elementCount': element_count,
            'outputPath': str(safe_svg_path)
        }
        
    except Exception as e:
        raise Exception(f"Failed to render Excalidraw: {str(e)}")


def svg_to_png(svg_path: str, png_path: str):
    """
    Convert SVG to PNG using cairosvg at 2x scale for OCR quality.
    
    Args:
        svg_path: Path to input SVG file
        png_path: Path where PNG should be written
    
    Raises:
        Exception: If cairosvg not installed or conversion fails
    """
    if not HAS_CAIROSVG:
        script_dir = Path(__file__).parent
        install_script = script_dir / "install_cairo.sh"
        raise Exception(
            "cairosvg not available. Cairo system libraries are required.\n\n"
            f"Run the installation script: {install_script}\n"
            "Or install manually:\n"
            "  Ubuntu/Debian: sudo apt-get install libcairo2-dev pkg-config python3-dev\n"
            "  Fedora/RHEL: sudo dnf install cairo-devel pkg-config python3-devel\n"
            "  macOS: brew install cairo pkg-config\n"
            "Then: pip install cairosvg"
        )
    
    try:
        # Convert SVG to PNG with scale for better OCR quality
        cairosvg.svg2png(url=svg_path, write_to=png_path, scale=SVG_RENDER_SCALE)
    except Exception as e:
        raise Exception(f"Failed to convert SVG to PNG: {str(e)}")


def process_excalidraw_file(
    excalidraw_path: Path,
    output_path: str | None = None,
    model: str | None = None,
    force: bool = False
) -> tuple[str, bool, str]:
    """
    Process an Excalidraw file and extract text via OCR.
    Returns (extracted_text, was_processed, content_hash).
    """
    
    if not excalidraw_path.exists():
        raise FileNotFoundError(f"File not found: {excalidraw_path}")
    
    if excalidraw_path.suffix not in ['.md', '.excalidraw']:
        raise ValueError(f"Expected .excalidraw.md or .excalidraw file, got: {excalidraw_path.suffix}")
    
    # Extract compressed data
    compressed_data = extract_compressed_data(excalidraw_path)
    
    # Calculate content hash
    content_hash = get_content_hash(compressed_data)
    
    # Determine output path using helper
    output_file = get_excalidraw_output_path(excalidraw_path, output_path)
    
    # Check if reprocessing is needed
    needs_processing, reason = should_reprocess(output_file, content_hash, force)
    
    if not needs_processing:
        print(f"✓ {reason}", file=sys.stderr)
        # Read and return existing content (skip YAML frontmatter)
        with open(output_file, 'r', encoding='utf-8') as f:
            content = []
            in_frontmatter = False
            first_line = True
            
            for line in f:
                # Check if file starts with frontmatter
                if first_line:
                    first_line = False
                    if line.strip() == '---':
                        in_frontmatter = True
                        continue
                
                # Skip until end of frontmatter
                if in_frontmatter:
                    if line.strip() == '---':
                        in_frontmatter = False
                    continue
                
                content.append(line)
            
            return ''.join(content).strip(), False, content_hash
    
    print(f"Processing: {excalidraw_path.name} ({reason})", file=sys.stderr)
    
    # Use context managers for automatic temp file cleanup
    print("Rendering to SVG...", file=sys.stderr)
    with temp_file('.svg') as svg_path, temp_file('.png') as png_path:
        # Render to SVG
        render_info = render_excalidraw_to_svg(compressed_data, svg_path)
        print(f"✓ SVG rendered: {render_info['width']:.0f}x{render_info['height']:.0f} px, "
              f"{render_info['elementCount']} elements", file=sys.stderr)
        
        # Convert SVG to PNG
        print("Converting to PNG...", file=sys.stderr)
        svg_to_png(svg_path, png_path)
        print("✓ PNG created", file=sys.stderr)
        
        # Load image and encode for OCR
        print("Encoding image...", file=sys.stderr)
        image = Image.open(png_path)
        image_base64 = encode_image_to_base64(image)
        print("✓ Image encoded", file=sys.stderr)
        
        # Perform OCR
        print(f"Performing OCR with {model or 'default model'}...", file=sys.stderr)
        extracted_text = perform_ocr(image_base64, model)
        print("✓ OCR completed\n", file=sys.stderr)
        
        # Clean any markdown wrapper that AI might have added
        extracted_text = clean_markdown_wrapper(extracted_text)
        
        return extracted_text, True, content_hash


class PendingFileTracker:
    """
    Tracks files pending processing with stabilization delay.
    
    When a file is created or modified, it's added to the pending queue with a
    "process after" timestamp. If the file is modified again before that time,
    the timer resets. This ensures files that are being actively edited (e.g.,
    during a meeting) aren't processed until editing has stopped.
    
    Args:
        delay_seconds: How long to wait after last modification before processing
        
    Attributes:
        pending: Dict mapping file paths to their "process after" timestamps
    """
    
    def __init__(self, delay_seconds: float) -> None:
        self.delay = delay_seconds
        self.pending: dict[str, float] = {}  # path -> process_after_timestamp
        self.lock = threading.Lock()
    
    def touch(self, path: str) -> None:
        """
        Register or reset timer for a file.
        
        Args:
            path: Path to the file that was created/modified
        """
        process_after = time.time() + self.delay
        with self.lock:
            was_pending = path in self.pending
            self.pending[path] = process_after
        
        # Log the action
        delay_mins = self.delay / 60
        if was_pending:
            logger.info(f"Timer reset for {Path(path).name}, will process in {delay_mins:.0f} min")
        else:
            logger.info(f"Queued {Path(path).name}, will process in {delay_mins:.0f} min")
    
    def get_ready_files(self) -> list[str]:
        """
        Return files whose delay has expired and remove them from pending.
        
        Returns:
            List of file paths ready for processing
        """
        now = time.time()
        with self.lock:
            ready = [p for p, t in self.pending.items() if now >= t]
            for p in ready:
                del self.pending[p]
            return ready
    
    def remove(self, path: str) -> None:
        """
        Remove a file from tracking (e.g., if deleted).
        
        Args:
            path: Path to remove from pending queue
        """
        with self.lock:
            if path in self.pending:
                del self.pending[path]
                logger.info(f"Removed {Path(path).name} from pending queue")
    
    def get_pending_count(self) -> int:
        """Return the number of files currently pending."""
        with self.lock:
            return len(self.pending)


class ExcalidrawWatcher(FileSystemEventHandler):
    """
    File system event handler for Excalidraw files.
    
    Monitors directory for new/modified .excalidraw.md files and processes
    them with OCR. Includes debouncing, thread-safety, and security validation.
    
    Args:
        model: OCR model to use (optional)
        force: Force reprocessing even if cached
        pending_tracker: Optional PendingFileTracker for stabilization delay
        
    Attributes:
        processed_count: Number of files processed
        cached_count: Number of files served from cache
        error_count: Number of processing errors
    """
    
    def __init__(
        self,
        model: str | None = None,
        force: bool = False,
        pending_tracker: PendingFileTracker | None = None
    ) -> None:
        super().__init__()
        self.model = model
        self.force = force
        self.pending_tracker = pending_tracker
        
        # Thread-safe state
        self.last_processed: dict[str, float] = {}
        self.lock = threading.Lock()
        self.processing_semaphore = threading.Semaphore(WATCH_MAX_CONCURRENT)
        
        # Statistics
        self.processed_count = 0
        self.cached_count = 0
        self.error_count = 0
    
    def should_process(self, path: str) -> bool:
        """
        Check if file should be processed (security + debouncing).
        
        Args:
            path: File path to check
            
        Returns:
            True if file should be processed, False otherwise
        """
        try:
            # Convert to Path for validation
            file_path = Path(path)
            
            # Security: Validate path is safe
            try:
                safe_path = validate_output_path(file_path)
            except ValueError as e:
                logger.warning(f"Rejected unsafe path {path}: {e}")
                return False
            
            # Security: Reject symlinks
            if safe_path.is_symlink():
                logger.warning(f"Ignoring symlink: {path}")
                return False
            
            # Check extension
            if not any(path.endswith(ext) for ext in WATCH_EXTENSIONS):
                return False
            
            # Ignore temp/hidden files
            filename = safe_path.name
            if filename.startswith('.'):
                return False
            
            if any(filename.endswith(pattern) for pattern in WATCH_IGNORE_PATTERNS):
                return False
            
            # Debounce check (thread-safe)
            with self.lock:
                current_time = time.time()
                last_time = self.last_processed.get(path, 0)
                
                if current_time - last_time < WATCH_DEBOUNCE_SECONDS:
                    return False
                
                self.last_processed[path] = current_time
                
                # Prevent memory leak: clean old entries
                if len(self.last_processed) > WATCH_MAX_DEBOUNCE_ENTRIES:
                    self.last_processed = {
                        k: v for k, v in self.last_processed.items()
                        if current_time - v < 3600  # Keep last hour only
                    }
            
            return True
            
        except Exception as e:
            logger.error(f"Error in should_process for {path}: {e}")
            return False
    
    def check_file_stable(self, path: Path) -> bool:
        """
        Check if file has finished being written.
        
        Args:
            path: Path to file
            
        Returns:
            True if file size is stable, False otherwise
        """
        try:
            size1 = path.stat().st_size
            time.sleep(WATCH_FILE_STABILITY_MS / 1000.0)
            size2 = path.stat().st_size
            return size1 == size2 and size2 > 0  # File must be stable AND non-empty
        except (FileNotFoundError, PermissionError):
            return False
    
    def process_file(self, path: Path) -> None:
        """
        Process an Excalidraw file with OCR.
        
        Args:
            path: Path to Excalidraw file
            
        Note:
            Handles errors gracefully and updates statistics.
        """
        # Limit concurrent processing
        with self.processing_semaphore:
            try:
                # Check file still exists and is readable
                if not path.exists():
                    logger.warning(f"File disappeared: {path}")
                    return
                
                timestamp = time.strftime("%H:%M:%S")
                print(f"\n[{timestamp}] Processing: {path.name}", file=sys.stderr)
                
                # Process the file
                extracted_text, was_processed, content_hash = process_excalidraw_file(
                    path,
                    output_path=None,
                    model=self.model,
                    force=self.force
                )
                
                # Determine output file path
                output_file = get_excalidraw_output_path(path, None)
                
                # Save with metadata if it was newly processed
                if was_processed:
                    save_with_metadata(output_file, extracted_text, content_hash, str(path))
                    print(f"✓ Text saved to {output_file.name}", file=sys.stderr)
                    self.processed_count += 1
                else:
                    print(f"✓ Using cached result: {output_file.name}", file=sys.stderr)
                    self.cached_count += 1
                
            except FileNotFoundError:
                logger.warning(f"File not found during processing: {path}")
                print(f"✗ File not found: {path.name}", file=sys.stderr)
                self.error_count += 1
            except PermissionError:
                logger.error(f"Permission denied: {path}")
                print(f"✗ Permission denied: {path.name}", file=sys.stderr)
                self.error_count += 1
            except Exception as e:
                logger.exception(f"Error processing {path.name}: {e}")
                print(f"✗ Error processing {path.name}: {str(e)}", file=sys.stderr)
                self.error_count += 1
    
    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        if event.is_directory:
            return
        
        path_str = event.src_path
        
        if not self.should_process(path_str):
            return
        
        path = Path(path_str)
        logger.info(f"Detected new file: {path.name}")
        
        # Wait for file to stabilize (file might be created empty then written to)
        # Try multiple times with increasing delays
        for attempt in range(3):
            time.sleep(0.1 * (attempt + 1))  # 0.1s, 0.2s, 0.3s
            if self.check_file_stable(path):
                break
        else:
            # If still unstable after retries, log warning
            logger.warning(f"File unstable after retries: {path.name}")
            return
        
        # If we have a pending tracker, queue the file; otherwise process immediately
        if self.pending_tracker:
            self.pending_tracker.touch(path_str)
            timestamp = time.strftime("%H:%M:%S")
            delay_mins = self.pending_tracker.delay / 60
            print(f"[{timestamp}] Queued: {path.name} (will process in {delay_mins:.0f} min if unchanged)", 
                  file=sys.stderr)
        else:
            self.process_file(path)
    
    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return
        
        path_str = event.src_path
        
        if not self.should_process(path_str):
            return
        
        path = Path(path_str)
        logger.info(f"Detected modification: {path.name}")
        
        # Wait for file to stabilize
        if not self.check_file_stable(path):
            logger.warning(f"File unstable, skipping: {path.name}")
            return
        
        # If we have a pending tracker, queue the file; otherwise process immediately
        if self.pending_tracker:
            self.pending_tracker.touch(path_str)
            timestamp = time.strftime("%H:%M:%S")
            delay_mins = self.pending_tracker.delay / 60
            print(f"[{timestamp}] Queued: {path.name} (will process in {delay_mins:.0f} min if unchanged)", 
                  file=sys.stderr)
        else:
            self.process_file(path)
    
    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        if event.is_directory:
            return
        
        path_str = event.src_path
        
        # Remove from pending tracker if present
        if self.pending_tracker:
            self.pending_tracker.remove(path_str)
    
    def get_stats(self) -> dict[str, int]:
        """Get processing statistics."""
        return {
            'processed': self.processed_count,
            'cached': self.cached_count,
            'errors': self.error_count,
        }


def watch_folder(
    folder_path: Path,
    model: str | None = None,
    force: bool = False,
    delay_minutes: int | None = None
) -> None:
    """
    Watch a folder for Excalidraw file changes and process them automatically.
    
    Args:
        folder_path: Path to folder to watch
        model: OCR model to use (optional)
        force: Force reprocessing even if cached
        delay_minutes: Minutes to wait after last modification before processing.
                      None means use default from env/config. 0 means no delay.
        
    Raises:
        ImportError: If watchdog library is not installed
    """
    if not HAS_WATCHDOG:
        raise ImportError(
            "watchdog library is required for watch mode.\n"
            "Install it with: pip install watchdog"
        )
    
    # Determine stabilization delay
    if delay_minutes is None:
        delay_minutes = WATCH_STABILIZATION_DELAY_MINUTES
    
    # Create pending file tracker (None if no delay)
    pending_tracker: PendingFileTracker | None = None
    if delay_minutes > 0:
        delay_seconds = delay_minutes * 60
        pending_tracker = PendingFileTracker(delay_seconds)
        print(f"Stabilization delay: {delay_minutes} minutes", file=sys.stderr)
    else:
        print("Stabilization delay: disabled (immediate processing)", file=sys.stderr)
    
    print(f"Initializing watch mode for: {folder_path}", file=sys.stderr)
    
    # Initial scan: process all existing files immediately (no delay)
    existing_files = sorted(folder_path.glob("*.excalidraw.md"))
    if existing_files:
        print(f"Processing {len(existing_files)} existing file(s)...\n", file=sys.stderr)
        processed = 0
        cached = 0
        errors = 0
        
        for file_path in existing_files:
            try:
                extracted_text, was_processed, content_hash = process_excalidraw_file(
                    file_path,
                    output_path=None,
                    model=model,
                    force=force
                )
                
                output_file = get_excalidraw_output_path(file_path, None)
                
                if was_processed:
                    save_with_metadata(output_file, extracted_text, content_hash, str(file_path))
                    print(f"✓ {file_path.name} -> {output_file.name}", file=sys.stderr)
                    processed += 1
                else:
                    print(f"✓ {file_path.name} (cached)", file=sys.stderr)
                    cached += 1
                    
            except Exception as e:
                print(f"✗ Error processing {file_path.name}: {str(e)}", file=sys.stderr)
                logger.exception(f"Error in initial scan for {file_path}")
                errors += 1
        
        print(f"\nInitial scan complete: {processed} processed, {cached} cached, {errors} errors", file=sys.stderr)
    
    # Set up file system observer
    event_handler = ExcalidrawWatcher(model=model, force=force, pending_tracker=pending_tracker)
    observer = Observer()
    observer.schedule(event_handler, str(folder_path), recursive=False)
    observer.start()
    
    if delay_minutes > 0:
        print(f"\nWatching {folder_path} for changes... (Ctrl+C to stop)", file=sys.stderr)
        print(f"Files will be processed {delay_minutes} min after last modification\n", file=sys.stderr)
    else:
        print(f"\nWatching {folder_path} for changes... (Ctrl+C to stop)\n", file=sys.stderr)
    
    # Set up signal handlers for graceful shutdown
    shutdown_event = threading.Event()
    
    def signal_handler(signum, frame):
        print("\n\nReceived shutdown signal...", file=sys.stderr)
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Main loop: check for ready files and process them
        while not shutdown_event.is_set():
            # Check for files ready to process
            if pending_tracker:
                ready_files = pending_tracker.get_ready_files()
                for file_path_str in ready_files:
                    file_path = Path(file_path_str)
                    if file_path.exists():
                        event_handler.process_file(file_path)
                    else:
                        logger.warning(f"Ready file no longer exists: {file_path}")
            
            # Sleep for the check interval (shorter if using tracker)
            sleep_time = WATCH_STABILIZATION_CHECK_INTERVAL if pending_tracker else 1
            
            # Use shorter sleeps to allow responsive shutdown
            for _ in range(int(sleep_time)):
                if shutdown_event.is_set():
                    break
                time.sleep(1)
                
    except KeyboardInterrupt:
        pass
    
    print("Stopping watch mode...", file=sys.stderr)
    observer.stop()
    observer.join()
    
    # Print final statistics
    stats = event_handler.get_stats()
    pending_count = pending_tracker.get_pending_count() if pending_tracker else 0
    print(f"\n✓ Watch mode stopped", file=sys.stderr)
    print(f"  Final stats: {stats['processed']} processed, {stats['cached']} cached, {stats['errors']} errors", file=sys.stderr)
    if pending_count > 0:
        print(f"  Note: {pending_count} file(s) were still pending (not processed)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from Excalidraw drawings using AI OCR (OpenAI/OpenRouter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s drawing.excalidraw.md                    # Auto-save to drawing.md
  %(prog)s drawing.excalidraw.md -o output.txt      # Save to custom file
  %(prog)s drawing.excalidraw.md -m MODEL           # Use specific OCR model
  %(prog)s drawing.excalidraw.md --provider openrouter  # Use OpenRouter instead of OpenAI
  %(prog)s drawing.excalidraw.md -c                 # Also copy to clipboard
  %(prog)s drawing.excalidraw.md -f                 # Force reprocessing
  %(prog)s ./drawings/                              # Process all .excalidraw.md files in folder
  %(prog)s ./drawings/ -w                           # Watch folder for changes
  %(prog)s ./drawings/ -w --force                   # Watch and always reprocess
  %(prog)s ./drawings/ -w --delay 30                # Wait 30 min before processing
  %(prog)s ./drawings/ -w --no-delay                # Process immediately (no wait)

Note: Output is automatically saved to a file with the same name but without
      the .excalidraw part (e.g., "name.excalidraw.md" -> "name.md").
      Intermediate files (SVG, PNG) are automatically cleaned up.
      
      Results are cached - if the Excalidraw content hasn't changed, the
      cached output is used instead of reprocessing. Use -f to force.
      
      Batch Processing: When given a folder path, processes all .excalidraw.md
      files in that folder. Shows summary at the end.
      
      Watch Mode: Use --watch to continuously monitor a folder for new or changed
      .excalidraw.md files. By default, waits 15 minutes after the last modification
      before processing (stabilization delay). This prevents processing files that
      are being actively edited, e.g., during a meeting. Use --no-delay to disable.

Environment Variables:
  OPENAI_API_KEY              Your OpenAI API key (preferred if set)
  OPENAI_MODEL                OpenAI model to use (default: gpt-4o)
  OPENROUTER_API_KEY          Your OpenRouter API key (fallback)
  OPENROUTER_MODEL            OpenRouter model to use (default: google/gemini-flash-1.5)
  STABILIZATION_DELAY_MINUTES Minutes to wait before processing (default: 15)

Requirements:
  - Node.js and npm (for Excalidraw rendering)
  - Cairo system library (for SVG to PNG conversion)
  
  Run ./install_cairo.sh to install cairo dependencies.
        """
    )
    
    parser.add_argument(
        "excalidraw_file",
        help="Path to Excalidraw file (.excalidraw.md) or folder containing such files",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: auto-generate from input filename)",
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
        "-c", "--clipboard",
        action="store_true",
        help="Copy extracted text to clipboard",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force reprocessing even if output is up-to-date",
    )
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Watch folder for changes and process files automatically",
    )
    parser.add_argument(
        "--delay",
        type=int,
        metavar="MINUTES",
        default=None,
        help=f"Minutes to wait after last file modification before processing (default: {WATCH_STABILIZATION_DELAY_MINUTES})",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="Disable stabilization delay, process files immediately (for testing)",
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
    
    try:
        input_path = Path(args.excalidraw_file).resolve()
        
        # Watch mode
        if args.watch:
            if not input_path.is_dir():
                print("Error: --watch requires a folder path, not a file", file=sys.stderr)
                return 1
            
            if args.output:
                print("Error: Cannot specify --output in watch mode", file=sys.stderr)
                return 1
            
            if args.clipboard:
                print("Error: Cannot use --clipboard in watch mode", file=sys.stderr)
                return 1
            
            # Determine delay: --no-delay sets to 0, --delay overrides default
            if args.no_delay:
                delay_minutes = 0
            else:
                delay_minutes = args.delay  # None means use default
            
            try:
                watch_folder(input_path, model=args.model, force=args.force, delay_minutes=delay_minutes)
                return 0
            except ImportError as e:
                logger.error(f"Watch mode not available: {e}")
                print(f"Error: {e}", file=sys.stderr)
                return 1
        
        # Determine if input is a file or folder
        if input_path.is_file():
            files_to_process = [input_path]
        elif input_path.is_dir():
            # Find all .excalidraw.md files in the directory
            files_to_process = sorted(input_path.glob("*.excalidraw.md"))
            if not files_to_process:
                print(f"No .excalidraw.md files found in {input_path}", file=sys.stderr)
                return 1
            print(f"Found {len(files_to_process)} .excalidraw.md file(s) to process\n", file=sys.stderr)
        else:
            print(f"Error: {input_path} is neither a file nor a directory", file=sys.stderr)
            return 1
        
        # Check if output path is specified for multiple files
        if len(files_to_process) > 1 and args.output:
            print("Error: Cannot specify --output when processing multiple files", file=sys.stderr)
            return 1
        
        # Check if clipboard requested for multiple files
        if len(files_to_process) > 1 and args.clipboard:
            print("Error: Cannot use --clipboard when processing multiple files", file=sys.stderr)
            return 1
        
        # Process all files
        processed_count = 0
        cached_count = 0
        error_count = 0
        
        for excalidraw_path in files_to_process:
            try:
                # Process the file
                extracted_text, was_processed, content_hash = process_excalidraw_file(
                    excalidraw_path,
                    output_path=args.output,
                    model=args.model,
                    force=args.force
                )
                
                # Determine output file path using helper
                output_file = get_excalidraw_output_path(excalidraw_path, args.output)
                
                # Save the result with metadata if it was newly processed
                if was_processed:
                    save_with_metadata(output_file, extracted_text, content_hash, str(excalidraw_path))
                    print(f"✓ Text saved to {output_file}", file=sys.stderr)
                    processed_count += 1
                # If from cache, file already exists - just confirm it
                else:
                    print(f"✓ Using cached result: {output_file}", file=sys.stderr)
                    cached_count += 1
                
                # Copy to clipboard if requested (only for single file)
                if args.clipboard:
                    copy_to_clipboard(extracted_text)
                    print("✓ Text copied to clipboard", file=sys.stderr)
                
                # Add blank line between files when processing multiple
                if len(files_to_process) > 1:
                    print("", file=sys.stderr)
                    
            except Exception as e:
                print(f"✗ Error processing {excalidraw_path.name}: {str(e)}", file=sys.stderr)
                error_count += 1
                if len(files_to_process) > 1:
                    print("", file=sys.stderr)
                    continue
                else:
                    return 1
        
        # Print summary for multiple files
        if len(files_to_process) > 1:
            print("=" * 60, file=sys.stderr)
            print(f"Summary: {processed_count} processed, {cached_count} cached, {error_count} errors", file=sys.stderr)
        
        return 0 if error_count == 0 else 1
    
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
