.PHONY: fix test install dev clean

fix:
	@echo "Formatting code..."
	@command -v black >/dev/null 2>&1 && black src tests || echo "black not installed, skipping"
	@command -v isort >/dev/null 2>&1 && isort src tests || echo "isort not installed, skipping"

test:
	pytest tests/ -v

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
