# Check for Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python is not found. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

# Create venv if it doesn't exist
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

# Activate venv
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.\.venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt

# Start Server
Write-Host "Starting Search Backend..." -ForegroundColor Green
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
