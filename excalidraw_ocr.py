#!/usr/bin/env python3
"""
Excalidraw OCR Script
Extracts text from Excalidraw drawings using AI OCR via OpenRouter.
Requires cairo system libraries - run ./install_cairo.sh first.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
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

# Configuration constants
SVG_RENDER_SCALE = 2  # 2x scale for better OCR accuracy
NODE_RENDER_TIMEOUT = 30  # Seconds
NPM_INSTALL_TIMEOUT = 120  # Seconds

# Watch mode configuration
WATCH_DEBOUNCE_SECONDS = 1.0  # Minimum time between processing same file
WATCH_FILE_STABILITY_MS = 500  # Wait time to check file size stability
WATCH_MAX_CONCURRENT = 3  # Maximum concurrent file processing
WATCH_MAX_DEBOUNCE_ENTRIES = 1000  # Maximum debounce entries before cleanup
WATCH_EXTENSIONS = {'.excalidraw.md', '.excalidraw'}  # File extensions to watch
WATCH_IGNORE_PATTERNS = {'.swp', '~', '.tmp', '.bak'}  # Temp file patterns to ignore

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


def render_excalidraw_to_svg(compressed_data: str, output_svg_path: str) -> dict:
    """
    Call Node.js script to render Excalidraw to SVG.
    
    Args:
        compressed_data: Base64-compressed Excalidraw JSON data
        output_svg_path: Path where SVG file should be written
    
    Returns:
        Dict with render info (width, height, elementCount, success, outputPath)
    
    Raises:
        FileNotFoundError: If renderer script or Node.js not found
        Exception: If rendering fails or times out
    """
    script_dir = Path(__file__).parent
    renderer_script = script_dir / "excalidraw_renderer.js"
    
    if not renderer_script.exists():
        raise FileNotFoundError(f"Renderer script not found: {renderer_script}")
    
    # Validate SVG output path for security (allow temp directory for temporary files)
    safe_svg_path = validate_output_path(output_svg_path, allow_temp=True)
    logger.info(f"Rendering Excalidraw to SVG: {safe_svg_path.name}")
    
    try:
        # Call Node.js renderer, passing data via stdin
        result = subprocess.run(
            ['node', str(renderer_script), str(safe_svg_path)],
            input=compressed_data,
            capture_output=True,
            text=True,
            timeout=NODE_RENDER_TIMEOUT
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            try:
                error_data = json.loads(error_msg)
                raise Exception(error_data.get('error', 'Unknown rendering error'))
            except json.JSONDecodeError:
                raise Exception(f"Rendering failed: {error_msg}")
        
        # Parse success output
        output_data = json.loads(result.stdout)
        return output_data
        
    except subprocess.TimeoutExpired:
        raise Exception(f"Rendering timed out after {NODE_RENDER_TIMEOUT} seconds")
    except FileNotFoundError:
        raise Exception(
            "Node.js not found. Please ensure Node.js is installed.\n"
            "Install from: https://nodejs.org/"
        )
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


def check_node_dependencies():
    """
    Check if required Node.js dependencies are installed, install if missing.
    
    Raises:
        Exception: If npm not found or installation fails
    """
    script_dir = Path(__file__).parent
    node_modules = script_dir / "node_modules"
    
    if not node_modules.exists():
        print("Installing Node.js dependencies...", file=sys.stderr)
        try:
            subprocess.run(
                ['npm', 'install'],
                cwd=script_dir,
                capture_output=True,
                check=True,
                timeout=NPM_INSTALL_TIMEOUT
            )
            print("✓ Node.js dependencies installed", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            raise Exception(
                f"Failed to install Node.js dependencies: {e.stderr.decode()}\n"
                f"Try running manually: cd {script_dir} && npm install"
            )
        except FileNotFoundError:
            raise Exception(
                "npm not found. Please ensure Node.js and npm are installed.\n"
                "Install from: https://nodejs.org/"
            )


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
    
    # Check Node.js dependencies
    check_node_dependencies()
    
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


class ExcalidrawWatcher(FileSystemEventHandler):
    """
    File system event handler for Excalidraw files.
    
    Monitors directory for new/modified .excalidraw.md files and processes
    them with OCR. Includes debouncing, thread-safety, and security validation.
    
    Args:
        model: OCR model to use (optional)
        force: Force reprocessing even if cached
        
    Attributes:
        processed_count: Number of files processed
        cached_count: Number of files served from cache
        error_count: Number of processing errors
    """
    
    def __init__(self, model: str | None = None, force: bool = False) -> None:
        super().__init__()
        self.model = model
        self.force = force
        
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
                self.process_file(path)
                return
        
        # If still unstable after retries, log warning
        logger.warning(f"File unstable after retries: {path.name}")
    
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
        
        self.process_file(path)
    
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
    force: bool = False
) -> None:
    """
    Watch a folder for Excalidraw file changes and process them automatically.
    
    Args:
        folder_path: Path to folder to watch
        model: OCR model to use (optional)
        force: Force reprocessing even if cached
        
    Raises:
        ImportError: If watchdog library is not installed
    """
    if not HAS_WATCHDOG:
        raise ImportError(
            "watchdog library is required for watch mode.\n"
            "Install it with: pip install watchdog"
        )
    
    print(f"Initializing watch mode for: {folder_path}", file=sys.stderr)
    
    # Initial scan: process all existing files
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
                    print(f"✓ {file_path.name} → {output_file.name}", file=sys.stderr)
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
    event_handler = ExcalidrawWatcher(model=model, force=force)
    observer = Observer()
    observer.schedule(event_handler, str(folder_path), recursive=False)
    observer.start()
    
    print(f"\n👀 Watching {folder_path} for changes... (Ctrl+C to stop)\n", file=sys.stderr)
    
    # Set up signal handlers for graceful shutdown
    shutdown_event = threading.Event()
    
    def signal_handler(signum, frame):
        print("\n\nReceived shutdown signal...", file=sys.stderr)
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    
    print("Stopping watch mode...", file=sys.stderr)
    observer.stop()
    observer.join()
    
    # Print final statistics
    stats = event_handler.get_stats()
    print(f"\n✓ Watch mode stopped", file=sys.stderr)
    print(f"  Final stats: {stats['processed']} processed, {stats['cached']} cached, {stats['errors']} errors", file=sys.stderr)


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

Note: Output is automatically saved to a file with the same name but without
      the .excalidraw part (e.g., "name.excalidraw.md" -> "name.md").
      Intermediate files (SVG, PNG) are automatically cleaned up.
      
      Results are cached - if the Excalidraw content hasn't changed, the
      cached output is used instead of reprocessing. Use -f to force.
      
      Batch Processing: When given a folder path, processes all .excalidraw.md
      files in that folder. Shows summary at the end.
      
      Watch Mode: Use --watch to continuously monitor a folder for new or changed
      .excalidraw.md files. Automatically processes them as they're created or modified.

Environment Variables:
  OPENAI_API_KEY        Your OpenAI API key (preferred if set)
  OPENAI_MODEL          OpenAI model to use (default: gpt-4o)
  OPENROUTER_API_KEY    Your OpenRouter API key (fallback)
  OPENROUTER_MODEL      OpenRouter model to use (default: google/gemini-flash-1.5)

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
            
            try:
                watch_folder(input_path, model=args.model, force=args.force)
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
