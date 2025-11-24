#!/usr/bin/env node
/**
 * Excalidraw Renderer
 * Decompresses Excalidraw data and creates SVG (to be converted to PNG by Python)
 */

const { decompressFromBase64 } = require('lz-string');
const fs = require('fs');
const path = require('path');

function parseArgs() {
    const args = process.argv.slice(2);
    if (args.length < 1) {
        console.error('Usage: node excalidraw_renderer.js <output-svg>');
        console.error('  Reads compressed Excalidraw data from stdin');
        console.error('  output-svg: Path to output SVG file');
        process.exit(1);
    }
    return {
        outputPath: args[0]
    };
}

function decompressExcalidraw(compressedData) {
    try {
        const decompressed = decompressFromBase64(compressedData);
        if (!decompressed) {
            throw new Error('Decompression failed - no data returned');
        }
        return JSON.parse(decompressed);
    } catch (error) {
        throw new Error(`Failed to decompress Excalidraw data: ${error.message}`);
    }
}

function createSVGFromExcalidraw(excalidrawData) {
    const elements = excalidrawData.elements || [];
    
    if (elements.length === 0) {
        throw new Error('No elements found in Excalidraw data');
    }

    // Calculate bounding box
    let minX = Infinity, minY = Infinity;
    let maxX = -Infinity, maxY = -Infinity;

    elements.forEach(element => {
        if (element.isDeleted) return;
        if (element.x !== undefined && element.y !== undefined) {
            minX = Math.min(minX, element.x);
            minY = Math.min(minY, element.y);
            maxX = Math.max(maxX, element.x + (element.width || 0));
            maxY = Math.max(maxY, element.y + (element.height || 0));
        }
    });

    // Add padding
    const padding = 40;
    minX -= padding;
    minY -= padding;
    maxX += padding;
    maxY += padding;

    const width = maxX - minX;
    const height = maxY - minY;

    // Create SVG
    let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
    svg += `<rect width="${width}" height="${height}" fill="white"/>`;
    svg += '<g>';

    // Render each element
    elements.forEach(element => {
        if (element.isDeleted) return;
        
        const x = element.x - minX;
        const y = element.y - minY;
        const strokeColor = element.strokeColor || '#000000';
        const fillColor = element.backgroundColor === 'transparent' ? 'none' : (element.backgroundColor || 'none');
        const strokeWidth = element.strokeWidth || 1;
        const opacity = (element.opacity || 100) / 100;
        
        let strokeDasharray = '';
        if (element.strokeStyle === 'dashed') {
            strokeDasharray = 'stroke-dasharray="12,8"';
        } else if (element.strokeStyle === 'dotted') {
            strokeDasharray = 'stroke-dasharray="2,6"';
        }

        switch (element.type) {
            case 'freedraw':
                if (element.points && element.points.length > 1) {
                    let path = `M ${x + element.points[0][0]} ${y + element.points[0][1]}`;
                    for (let i = 1; i < element.points.length; i++) {
                        path += ` L ${x + element.points[i][0]} ${y + element.points[i][1]}`;
                    }
                    svg += `<path d="${path}" stroke="${strokeColor}" stroke-width="${strokeWidth}" fill="none" opacity="${opacity}" ${strokeDasharray}/>`;
                }
                break;

            case 'line':
            case 'arrow':
                if (element.points && element.points.length > 1) {
                    let path = `M ${x + element.points[0][0]} ${y + element.points[0][1]}`;
                    for (let i = 1; i < element.points.length; i++) {
                        path += ` L ${x + element.points[i][0]} ${y + element.points[i][1]}`;
                    }
                    svg += `<path d="${path}" stroke="${strokeColor}" stroke-width="${strokeWidth}" fill="none" opacity="${opacity}" ${strokeDasharray}/>`;
                    
                    // Add arrow head
                    if (element.type === 'arrow' && element.points.length >= 2) {
                        const lastIdx = element.points.length - 1;
                        const p1 = element.points[lastIdx - 1];
                        const p2 = element.points[lastIdx];
                        const angle = Math.atan2(p2[1] - p1[1], p2[0] - p1[0]);
                        const arrowLength = 15;
                        const arrowAngle = Math.PI / 6;
                        
                        const x2 = x + p2[0];
                        const y2 = y + p2[1];
                        
                        const arrowPath = `M ${x2} ${y2} L ${x2 - arrowLength * Math.cos(angle - arrowAngle)} ${y2 - arrowLength * Math.sin(angle - arrowAngle)} M ${x2} ${y2} L ${x2 - arrowLength * Math.cos(angle + arrowAngle)} ${y2 - arrowLength * Math.sin(angle + arrowAngle)}`;
                        svg += `<path d="${arrowPath}" stroke="${strokeColor}" stroke-width="${strokeWidth}" fill="none" opacity="${opacity}"/>`;
                    }
                }
                break;

            case 'rectangle':
                svg += `<rect x="${x}" y="${y}" width="${element.width}" height="${element.height}" stroke="${strokeColor}" stroke-width="${strokeWidth}" fill="${fillColor}" opacity="${opacity}" ${strokeDasharray}/>`;
                break;

            case 'ellipse':
                const cx = x + element.width / 2;
                const cy = y + element.height / 2;
                const rx = element.width / 2;
                const ry = element.height / 2;
                svg += `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" stroke="${strokeColor}" stroke-width="${strokeWidth}" fill="${fillColor}" opacity="${opacity}" ${strokeDasharray}/>`;
                break;

            case 'text':
                if (element.text) {
                    const fontSize = element.fontSize || 20;
                    const fontFamily = element.fontFamily || 'Arial, sans-serif';
                    const lines = element.text.split('\n');
                    const lineHeight = fontSize * 1.2;
                    
                    lines.forEach((line, i) => {
                        svg += `<text x="${x}" y="${y + fontSize + (i * lineHeight)}" font-size="${fontSize}" font-family="${fontFamily}" fill="${strokeColor}" opacity="${opacity}">${escapeXml(line)}</text>`;
                    });
                }
                break;
        }
    });

    svg += '</g></svg>';
    
    return {
        svg,
        width,
        height,
        elementCount: elements.filter(e => !e.isDeleted).length
    };
}

function validateOutputPath(outputPath) {
    /**
     * Validate output path to prevent path traversal attacks.
     * @param {string} outputPath - The output path to validate
     * @returns {string} Resolved safe path
     * @throws {Error} If path is unsafe
     */
    const os = require('os');
    const fs = require('fs');
    
    // Resolve to absolute path
    const resolved = path.resolve(outputPath);
    const cwd = process.cwd();
    
    // Resolve temp directory to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
    const tempDir = fs.realpathSync(os.tmpdir());
    
    // Check for suspicious patterns
    if (outputPath.includes('..')) {
        throw new Error('Path traversal detected in output path');
    }
    
    // Ensure it's within current working directory or temp directory
    if (!resolved.startsWith(cwd) && !resolved.startsWith(tempDir)) {
        throw new Error(`Output path must be within working directory or temp: ${outputPath}`);
    }
    
    // Block sensitive directories (but allow temp)
    const sensitiveDirs = ['/etc/', '/usr/', '/bin/', '/sbin/', '/boot/', '/sys/', '/proc/'];
    for (const sensitive of sensitiveDirs) {
        if (resolved.startsWith(sensitive)) {
            throw new Error(`Writing to ${sensitive} is not allowed`);
        }
    }
    
    return resolved;
}

function escapeXml(unsafe) {
    return unsafe.replace(/[<>&'"]/g, (c) => {
        switch (c) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            case '\'': return '&apos;';
            case '"': return '&quot;';
        }
    });
}

async function readStdin() {
    return new Promise((resolve, reject) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        
        process.stdin.on('data', chunk => {
            data += chunk;
        });
        
        process.stdin.on('end', () => {
            resolve(data.trim());
        });
        
        process.stdin.on('error', reject);
    });
}

async function main() {
    try {
        const { outputPath } = parseArgs();
        
        // Validate output path for security
        const safeOutputPath = validateOutputPath(outputPath);
        
        // Read compressed data from stdin
        const compressedData = await readStdin();
        
        if (!compressedData) {
            throw new Error('No data received from stdin');
        }
        
        // Validate input size (10MB limit)
        const MAX_INPUT_SIZE = 10 * 1024 * 1024; // 10MB
        if (compressedData.length > MAX_INPUT_SIZE) {
            throw new Error(`Input data too large (${(compressedData.length / 1024 / 1024).toFixed(2)}MB > 10MB)`);
        }
        
        // Validate base64 format
        if (!/^[A-Za-z0-9+/=\s]+$/.test(compressedData)) {
            throw new Error('Invalid compressed data format (expected base64)');
        }
        
        // Decompress the data
        const excalidrawData = decompressExcalidraw(compressedData);
        
        // Validate decompressed size
        const jsonSize = JSON.stringify(excalidrawData).length;
        const MAX_DECOMPRESSED_SIZE = 50 * 1024 * 1024; // 50MB
        if (jsonSize > MAX_DECOMPRESSED_SIZE) {
            throw new Error(`Decompressed data too large: ${(jsonSize / 1024 / 1024).toFixed(2)}MB (max: 50MB)`);
        }
        
        // Validate structure
        if (!excalidrawData || typeof excalidrawData !== 'object') {
            throw new Error('Invalid Excalidraw data structure');
        }
        
        if (!Array.isArray(excalidrawData.elements)) {
            throw new Error('Excalidraw data missing elements array');
        }
        
        // Limit number of elements to prevent DoS
        const MAX_ELEMENTS = 10000;
        if (excalidrawData.elements.length > MAX_ELEMENTS) {
            throw new Error(`Too many elements: ${excalidrawData.elements.length} (max: ${MAX_ELEMENTS})`);
        }
        
        // Create SVG from Excalidraw data
        const { svg, width, height, elementCount } = createSVGFromExcalidraw(excalidrawData);
        
        // Save SVG to file
        fs.writeFileSync(safeOutputPath, svg);
        
        // Output success info as JSON
        console.log(JSON.stringify({
            success: true,
            width,
            height,
            elementCount,
            outputPath: safeOutputPath
        }));
        
    } catch (error) {
        console.error(JSON.stringify({
            success: false,
            error: error.message
        }));
        process.exit(1);
    }
}

if (require.main === module) {
    main().catch(error => {
        console.error(JSON.stringify({
            success: false,
            error: error.message
        }));
        process.exit(1);
    });
}

module.exports = { decompressExcalidraw, createSVGFromExcalidraw };
