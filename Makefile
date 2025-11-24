.PHONY: build run shell test clean help logs ocr excalidraw stop

IMAGE_NAME := ocr-app
CONTAINER_NAME := ocr-container

# Docker Compose command (auto-detect v1 or v2)
DOCKER_COMPOSE := $(shell command -v docker-compose 2>/dev/null && echo docker-compose || echo "docker compose")

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m # No Color

help:
	@echo "$(BLUE)OCR Docker Commands:$(NC)"
	@echo ""
	@echo "$(GREEN)Setup:$(NC)"
	@echo "  make build        - Build Docker image"
	@echo "  make setup        - Create input/output directories and copy .env.example"
	@echo ""
	@echo "$(GREEN)Running:$(NC)"
	@echo "  make run          - Run with $(DOCKER_COMPOSE) (shows help)"
	@echo "  make shell        - Open interactive shell in container"
	@echo "  make ocr          - Run OCR on image (IMAGE=/input/file.png)"
	@echo "  make excalidraw   - Run Excalidraw OCR (FILE=/input/drawing.excalidraw.md)"
	@echo ""
	@echo "$(GREEN)Testing:$(NC)"
	@echo "  make test         - Test installation and dependencies"
	@echo "  make list-models  - List available OCR models"
	@echo ""
	@echo "$(GREEN)Maintenance:$(NC)"
	@echo "  make logs         - View container logs"
	@echo "  make stop         - Stop running containers"
	@echo "  make clean        - Remove containers and volumes"
	@echo "  make clean-all    - Remove containers, volumes, and images"
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make ocr IMAGE=/input/handwriting.jpg"
	@echo "  make excalidraw FILE=/input/drawing.excalidraw.md"

build:
	@echo "$(GREEN)Building Docker image...$(NC)"
	$(DOCKER_COMPOSE) build
	@echo "$(GREEN)✓ Build complete$(NC)"

setup:
	@echo "$(GREEN)Setting up directories...$(NC)"
	mkdir -p input output
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "$(YELLOW)Created .env file from .env.example$(NC)"; \
		echo "$(YELLOW)⚠️  Please edit .env and add your OPENROUTER_API_KEY$(NC)"; \
	else \
		echo "$(GREEN)✓ .env already exists$(NC)"; \
	fi
	@echo "$(GREEN)✓ Setup complete$(NC)"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and add your API key"
	@echo "  2. Run 'make build' to build the image"
	@echo "  3. Place images in ./input/"
	@echo "  4. Run 'make ocr IMAGE=/input/yourimage.png'"

run:
	@echo "$(GREEN)Starting OCR container...$(NC)"
	$(DOCKER_COMPOSE) up

shell:
	@echo "$(GREEN)Opening shell in container...$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr /bin/bash

test:
	@echo "$(GREEN)Testing Docker setup...$(NC)"
	@echo "\n$(BLUE)Python version:$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr python --version
	@echo "\n$(BLUE)Node.js version:$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr node --version
	@echo "\n$(BLUE)Testing cairosvg import:$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr python -c "import cairosvg; print('✓ cairosvg OK')"
	@echo "\n$(BLUE)Testing lz-string:$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr node -e "const lz = require('lz-string'); console.log('✓ lz-string OK')"
	@echo "\n$(GREEN)✓ All tests passed$(NC)"

list-models:
	@echo "$(GREEN)Listing available OCR models...$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr python ocr.py --list-models

ocr:
	@if [ -z "$(IMAGE)" ]; then \
		echo "$(YELLOW)Usage: make ocr IMAGE=/input/yourimage.png [OUTPUT=/output/result.txt]$(NC)"; \
		exit 1; \
	fi
	@if [ -n "$(OUTPUT)" ]; then \
		$(DOCKER_COMPOSE) run --rm ocr python ocr.py $(IMAGE) -o $(OUTPUT); \
	else \
		$(DOCKER_COMPOSE) run --rm ocr python ocr.py $(IMAGE); \
	fi

excalidraw:
	@if [ -z "$(FILE)" ]; then \
		echo "$(YELLOW)Usage: make excalidraw FILE=/input/drawing.excalidraw.md$(NC)"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) run --rm ocr python excalidraw_ocr.py $(FILE)

logs:
	@echo "$(GREEN)Showing container logs...$(NC)"
	$(DOCKER_COMPOSE) logs -f

stop:
	@echo "$(GREEN)Stopping containers...$(NC)"
	$(DOCKER_COMPOSE) down
	@echo "$(GREEN)✓ Stopped$(NC)"

clean:
	@echo "$(YELLOW)Removing containers and volumes...$(NC)"
	$(DOCKER_COMPOSE) down -v
	@echo "$(GREEN)✓ Cleaned$(NC)"

clean-all: clean
	@echo "$(YELLOW)Removing Docker images...$(NC)"
	docker rmi $(IMAGE_NAME):latest 2>/dev/null || true
	@echo "$(GREEN)✓ All cleaned$(NC)"

# Development helpers
dev-build:
	@echo "$(GREEN)Building without cache...$(NC)"
	$(DOCKER_COMPOSE) build --no-cache

dev-logs:
	@echo "$(GREEN)Showing detailed logs...$(NC)"
	$(DOCKER_COMPOSE) logs --tail=100 -f

# Batch processing
batch-ocr:
	@echo "$(GREEN)Batch processing all images in ./input/...$(NC)"
	@for img in input/*.{png,jpg,jpeg,PNG,JPG,JPEG}; do \
		if [ -f "$$img" ]; then \
			echo "Processing $$img..."; \
			$(DOCKER_COMPOSE) run --rm ocr python ocr.py "/$$img" -o "/output/$$(basename $$img .png).txt" 2>/dev/null || \
			$(DOCKER_COMPOSE) run --rm ocr python ocr.py "/$$img" -o "/output/$$(basename $$img .jpg).txt" 2>/dev/null || \
			$(DOCKER_COMPOSE) run --rm ocr python ocr.py "/$$img" -o "/output/$$(basename $$img .jpeg).txt" 2>/dev/null; \
		fi; \
	done
	@echo "$(GREEN)✓ Batch processing complete$(NC)"

batch-excalidraw:
	@echo "$(GREEN)Batch processing all Excalidraw files in ./input/...$(NC)"
	$(DOCKER_COMPOSE) run --rm ocr python excalidraw_ocr.py /input/
	@echo "$(GREEN)✓ Batch processing complete$(NC)"
