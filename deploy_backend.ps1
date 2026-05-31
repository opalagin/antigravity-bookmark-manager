$ErrorActionPreference = "Stop"

# Load environment variables from .env
if (Test-Path .env)
{
    Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } | ForEach-Object {
        $name, $value = $_.Split('=', 2)
        [Environment]::SetEnvironmentVariable($name, $value)
    }
}

$DOCKER_USERNAME = [Environment]::GetEnvironmentVariable("DOCKER_USERNAME")

if ([string]::IsNullOrWhiteSpace($DOCKER_USERNAME))
{
    Write-Error "DOCKER_USERNAME is not set in .env or environment variables."
}

$IMAGE_NAME = "ai-bookmanager-backend"
$TAG = "latest"
$FULL_IMAGE_NAME = "${DOCKER_USERNAME}/${IMAGE_NAME}:${TAG}"

Write-Host "--------------------------------------------------"
Write-Host "Deploying Search Backend"
Write-Host "Docker Username: $DOCKER_USERNAME"
Write-Host "Image: $FULL_IMAGE_NAME"
Write-Host "--------------------------------------------------"

# 1. Verification of Login (Optional, but good practice)
# We assume user is logged in, but we can try to check or just proceed.

# 2. Build
Write-Host "`n[1/2] Building Docker Image..."
docker build -t $FULL_IMAGE_NAME "./Search Backend"

if ($LASTEXITCODE -ne 0)
{
    Write-Error "Docker build failed."
}

# 3. Push
Write-Host "`n[2/3] Pushing to Docker Hub..."
docker push $FULL_IMAGE_NAME

if ($LASTEXITCODE -ne 0)
{
    Write-Error "Docker push failed. Make sure you are logged in using 'docker login' and have access to the repository."
}

# 4. Redeploy on Railway (Railway does not auto-pull on push — manual trigger required)
Write-Host "`n[3/3] Triggering Railway redeploy for service 'search-backend'..."
railway link --project ai-bookmark-manager --service search-backend
railway redeploy --service search-backend --yes

if ($LASTEXITCODE -ne 0)
{
    Write-Error "Railway redeploy failed. Make sure 'railway' CLI is installed and you are linked to the project ('railway link')."
}

Write-Host "`nSuccess! Image pushed to $FULL_IMAGE_NAME and Railway redeploy triggered."
