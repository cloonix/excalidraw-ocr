#!/bin/bash
# Install cairo system dependencies for Excalidraw OCR

echo "Installing cairo system dependencies..."
echo "This requires sudo privileges."
echo ""

# Detect OS
if [ -f /etc/debian_version ]; then
    echo "Detected Debian/Ubuntu-based system"
    sudo apt-get update
    sudo apt-get install -y libcairo2-dev pkg-config python3-dev
    echo "✓ System dependencies installed"
elif [ -f /etc/redhat-release ]; then
    echo "Detected RedHat/Fedora-based system"
    sudo dnf install -y cairo-devel pkg-config python3-devel
    echo "✓ System dependencies installed"
elif [ "$(uname)" == "Darwin" ]; then
    echo "Detected macOS"
    brew install cairo pkg-config
    echo "✓ System dependencies installed"
else
    echo "Unknown OS. Please install cairo manually:"
    echo "  Ubuntu/Debian: sudo apt-get install libcairo2-dev pkg-config python3-dev"
    echo "  Fedora/RHEL: sudo dnf install cairo-devel pkg-config python3-devel"
    echo "  macOS: brew install cairo pkg-config"
    exit 1
fi

echo ""
echo "Installing Python cairosvg package..."
pip install cairosvg

echo ""
echo "✓ Installation complete!"
echo "You can now run: python excalidraw_ocr.py <file.excalidraw.md>"
