# Check if Docker is running by executing a docker command
docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Docker is not running or not in PATH. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Check for .env file
if (-not (Test-Path .env)) {
    Write-Host "Creating .env file from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "Please update .env with your desired password." -ForegroundColor Yellow
}

# Start the container
Write-Host "Starting Postgres with pgvector..." -ForegroundColor Cyan
docker compose up -d

# Wait for healthcheck
Write-Host "Waiting for database to be ready..." -ForegroundColor Cyan
$retries = 10
while ($retries -gt 0) {
    $status = docker inspect --format='{{json .State.Health.Status}}' bookmark_db | ConvertFrom-Json
    if ($status -eq "healthy") {
        Write-Host "Database is ready!" -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 2
    $retries--
}

Write-Host "Warning: Database startup timed out or is still initializing." -ForegroundColor Yellow
