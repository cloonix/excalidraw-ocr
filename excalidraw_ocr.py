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
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Import OCR functions from existing script
from ocr import encode_image_to_base64, perform_ocr, copy_to_clipboard
from PIL import Image

# Try to import cairosvg
try:
    import cairosvg
    HAS_CAIROSVG = True
except ImportError:
    HAS_CAIROSVG = False


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
    # Create YAML frontmatter
    frontmatter = [
        "---",
        f"excalidraw-ocr-hash: {content_hash}",
        f"excalidraw-ocr-source: {source_file}",
        f"excalidraw-ocr-date: {datetime.now().isoformat()}",
        "---",
        "",  # Empty line after frontmatter
    ]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(frontmatter))
        f.write(text.strip())  # Strip to avoid extra whitespace
        f.write('\n')  # End with newline


def extract_compressed_data(excalidraw_file_path: Path) -> str:
    """Extract compressed JSON data from Excalidraw markdown file."""
    try:
        with open(excalidraw_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the compressed-json block
        pattern = r'```compressed-json\s*([\s\S]*?)\s*```'
        match = re.search(pattern, content)
        
        if not match:
            raise ValueError("No compressed-json block found in file")
        
        # Extract and clean the compressed data
        compressed_data = match.group(1)
        compressed_data = ''.join(compressed_data.split())  # Remove all whitespace
        
        return compressed_data
        
    except FileNotFoundError:
        raise FileNotFoundError(f"Excalidraw file not found: {excalidraw_file_path}")
    except Exception as e:
        raise Exception(f"Failed to extract compressed data: {str(e)}")


def render_excalidraw_to_svg(compressed_data: str, output_svg_path: str) -> dict:
    """Call Node.js script to render Excalidraw to SVG."""
    script_dir = Path(__file__).parent
    renderer_script = script_dir / "excalidraw_renderer.js"
    
    if not renderer_script.exists():
        raise FileNotFoundError(f"Renderer script not found: {renderer_script}")
    
    try:
        # Call Node.js renderer, passing data via stdin
        result = subprocess.run(
            ['node', str(renderer_script), output_svg_path],
            input=compressed_data,
            capture_output=True,
            text=True,
            timeout=30
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
        raise Exception("Rendering timed out after 30 seconds")
    except FileNotFoundError:
        raise Exception(
            "Node.js not found. Please ensure Node.js is installed.\n"
            "Install from: https://nodejs.org/"
        )
    except Exception as e:
        raise Exception(f"Failed to render Excalidraw: {str(e)}")


def svg_to_png(svg_path: str, png_path: str):
    """Convert SVG to PNG using cairosvg."""
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
        # Convert SVG to PNG with 2x scale for better OCR quality
        cairosvg.svg2png(url=svg_path, write_to=png_path, scale=2.0)
    except Exception as e:
        raise Exception(f"Failed to convert SVG to PNG: {str(e)}")


def check_node_dependencies():
    """Check if required Node.js dependencies are installed."""
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
                timeout=120
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
    
    # Determine output path
    if output_path:
        output_file = Path(output_path)
    else:
        # Auto-generate output filename by removing .excalidraw from the name
        filename = excalidraw_path.name
        if '.excalidraw.' in filename:
            output_filename = filename.replace('.excalidraw.', '.')
        elif filename.endswith('.excalidraw'):
            output_filename = filename.replace('.excalidraw', '.txt')
        else:
            output_filename = excalidraw_path.stem + '.txt'
        output_file = excalidraw_path.parent / output_filename
    
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
    
    # Render to SVG first
    print("Rendering to SVG...", file=sys.stderr)
    temp_svg = tempfile.NamedTemporaryFile(suffix='.svg', delete=False)
    svg_path = temp_svg.name
    temp_svg.close()
    
    try:
        render_info = render_excalidraw_to_svg(compressed_data, svg_path)
        print(f"✓ SVG rendered: {render_info['width']:.0f}x{render_info['height']:.0f} px, "
              f"{render_info['elementCount']} elements", file=sys.stderr)
        
        # Convert SVG to PNG (always use temp file)
        print("Converting to PNG...", file=sys.stderr)
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        png_path = temp_file.name
        temp_file.close()
        
        try:
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
            
        finally:
            # Always clean up temp PNG
            if os.path.exists(png_path):
                os.unlink(png_path)
                
    finally:
        # Clean up temp SVG
        if os.path.exists(svg_path):
            os.unlink(svg_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from Excalidraw drawings using AI OCR (OpenRouter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s drawing.excalidraw.md                    # Auto-save to drawing.md
  %(prog)s drawing.excalidraw.md -o output.txt      # Save to custom file
  %(prog)s drawing.excalidraw.md -m MODEL           # Use specific OCR model
  %(prog)s drawing.excalidraw.md -c                 # Also copy to clipboard
  %(prog)s drawing.excalidraw.md -f                 # Force reprocessing

Note: Output is automatically saved to a file with the same name but without
      the .excalidraw part (e.g., "name.excalidraw.md" -> "name.md").
      Intermediate files (SVG, PNG) are automatically cleaned up.
      
      Results are cached - if the Excalidraw content hasn't changed, the
      cached output is used instead of reprocessing. Use -f to force.

Environment Variables:
  OPENROUTER_API_KEY    Your OpenRouter API key (required)
  OPENROUTER_MODEL      Default model to use (default: google/gemini-flash-1.5)

Requirements:
  - Node.js and npm (for Excalidraw rendering)
  - Cairo system library (for SVG to PNG conversion)
  
  Run ./install_cairo.sh to install cairo dependencies.
        """
    )
    
    parser.add_argument(
        "excalidraw_file",
        help="Path to Excalidraw file (.excalidraw.md)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: auto-generate from input filename)",
    )
    parser.add_argument(
        "-m", "--model",
        help="OpenRouter model to use (overrides OPENROUTER_MODEL env var)",
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
    
    args = parser.parse_args()
    
    try:
        # Process the file
        excalidraw_path = Path(args.excalidraw_file).resolve()
        extracted_text, was_processed, content_hash = process_excalidraw_file(
            excalidraw_path,
            output_path=args.output,
            model=args.model,
            force=args.force
        )
        
        # Determine output file path (same logic as in process_excalidraw_file)
        if args.output:
            output_file = Path(args.output)
        else:
            # Auto-generate output filename by removing .excalidraw from the name
            filename = excalidraw_path.name
            if '.excalidraw.' in filename:
                output_filename = filename.replace('.excalidraw.', '.')
            elif filename.endswith('.excalidraw'):
                output_filename = filename.replace('.excalidraw', '.txt')
            else:
                output_filename = excalidraw_path.stem + '.txt'
            output_file = excalidraw_path.parent / output_filename
        
        # Save the result with metadata if it was newly processed
        if was_processed:
            save_with_metadata(output_file, extracted_text, content_hash, str(excalidraw_path))
            print(f"✓ Text saved to {output_file}", file=sys.stderr)
        # If from cache, file already exists - just confirm it
        else:
            print(f"✓ Using cached result: {output_file}", file=sys.stderr)
        
        # Copy to clipboard if requested
        if args.clipboard:
            copy_to_clipboard(extracted_text)
            print("✓ Text copied to clipboard", file=sys.stderr)
        
        return 0
    
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
