# Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Error: uv is not found. Please install uv (https://github.com/astral-sh/uv)." -ForegroundColor Red
    Write-Host "Install command: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`"" -ForegroundColor Cyan
    exit 1
}

# Load .env file
$envFile = ".env"
if (-not (Test-Path $envFile)) {
    $envFile = "..\.env"
}

if (Test-Path $envFile) {
    Write-Host "Loading environment variables from $envFile..." -ForegroundColor Cyan
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $name, $value = $line.Split("=", 2)
            if ($name -and $value) {
                [System.Environment]::SetEnvironmentVariable($name, $value, [System.EnvironmentVariableTarget]::Process)
            }
        }
    }
}
else {
    Write-Host "Warning: .env file not found." -ForegroundColor Yellow
}

# Ensure venv exists and dependencies are synced
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment with uv..." -ForegroundColor Cyan
    uv venv --python 3.10 --quiet
}

Write-Host "Syncing dependencies with uv..." -ForegroundColor Cyan
uv pip install -r requirements.txt

# Start Server
Write-Host "Starting Search Backend with uv..." -ForegroundColor Green
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
