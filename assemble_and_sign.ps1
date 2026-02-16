# Firefox Extension Assembly and Signing Script

$ErrorActionPreference = "Stop"

# Configuration
$ExtensionDir = "Firefox Plugin"
$EnvFile = ".env"
$ArtifactsDir = "$ExtensionDir\web-ext-artifacts"

# Function to check if a command exists
function Test-CommandExists {
    param ($Command)
    (Get-Command $Command -ErrorAction SilentlyContinue) -ne $null
}

# Function to get env variable from process or .env file
function Get-EnvVariable {
    param ($Name)
    
    # helper to read from .env if not in process
    if ([string]::IsNullOrWhiteSpace((Get-ChildItem Env:\$Name -ErrorAction SilentlyContinue).Value)) {
        if (Test-Path $EnvFile) {
            $lines = Get-Content $EnvFile
            foreach ($line in $lines) {
                if ($line -match "^$Name=(.*)$") {
                    return $matches[1].Trim()
                }
            }
        }
    }
    else {
        return (Get-ChildItem Env:\$Name).Value
    }
    return $null
}

# Function to append to .env file
function Set-EnvVariable {
    param ($Name, $Value)
    if (-not (Test-Path $EnvFile)) {
        New-Item -Path $EnvFile -ItemType File | Out-Null
    }
    Add-Content -Path $EnvFile -Value "$Name=$Value"
}

Write-Host "Checking prerequisites..." -ForegroundColor Cyan

# Check for web-ext
if (-not (Test-CommandExists "web-ext")) {
    Write-Host "web-ext not found. Installing globally via npm..." -ForegroundColor Yellow
    npm install --global web-ext
    if (-not (Test-CommandExists "web-ext")) {
        Write-Error "Failed to install web-ext. Please install it manually: npm install --global web-ext"
    }
}
else {
    Write-Host "web-ext is installed." -ForegroundColor Green
}

# Check for API Keys
$ApiKey = Get-EnvVariable "WEB_EXT_API_KEY"
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    $ApiKey = Get-EnvVariable "AMO_JWT_ISSUER"
}

$ApiSecret = Get-EnvVariable "WEB_EXT_API_SECRET"
if ([string]::IsNullOrWhiteSpace($ApiSecret)) {
    $ApiSecret = Get-EnvVariable "AMO_JWT_SECRET"
}

if ([string]::IsNullOrWhiteSpace($ApiKey) -or [string]::IsNullOrWhiteSpace($ApiSecret)) {
    Write-Host "Mozilla Add-ons API keys are missing from environment and $EnvFile" -ForegroundColor Yellow
    
    Write-Host "Please provide your Mozilla Add-ons API credentials."
    Write-Host "You can generate them at https://addons.mozilla.org/en-US/developers/addon/api/key/"
    
    $ApiKey = Read-Host "Enter your API Key (Issuer)"
    $ApiSecret = Read-Host "Enter your API Secret" 

    if ([string]::IsNullOrWhiteSpace($ApiKey) -or [string]::IsNullOrWhiteSpace($ApiSecret)) {
        Write-Error "API Key and Secret are required to sign the extension."
    }

    # Save to .env using standard names for consistency, or maybe just use what we have?
    # Let's save as WEB_EXT_* to standardise, but also maybe the user prefers AMO_*?
    # The script uses these variables for the command.
    Set-EnvVariable "WEB_EXT_API_KEY" $ApiKey
    Set-EnvVariable "WEB_EXT_API_SECRET" $ApiSecret
    Write-Host "API keys saved to $EnvFile" -ForegroundColor Green
}
else {
    Write-Host "API keys found." -ForegroundColor Green
}

# Build and Sign
Write-Host "Building and signing extension..." -ForegroundColor Cyan

# Verify ExtensionDir exists
if (-not (Test-Path $ExtensionDir)) {
    Write-Error "Extension directory '$ExtensionDir' not found!"
}

# Ensure artifacts dir exists
if (-not (Test-Path $ArtifactsDir)) {
    New-Item -ItemType Directory -Force -Path $ArtifactsDir | Out-Null
}

try {
    # We call web-ext directly. 
    # Note: web-ext sign requires the extension source.
    # We use --channel=unlisted for self-distribution.
    
    # Debug: Print arguments
    Write-Host "Executing: web-ext sign --source-dir '$ExtensionDir' --artifacts-dir '$ArtifactsDir' --api-key ... --channel unlisted" -ForegroundColor Gray
    
    # Use cmd /c to execute web-ext to avoid issues with .cmd/.ps1 wrappers and argument parsing
    # We manually quote the paths to ensure spaces are handled in the command string passed to cmd
    $cmdLine = "web-ext sign --source-dir ""$ExtensionDir"" --artifacts-dir ""$ArtifactsDir"" --api-key ""$ApiKey"" --api-secret ""$ApiSecret"" --channel unlisted"
    
    $process = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmdLine -PassThru -NoNewWindow -Wait
    
    if ($process.ExitCode -eq 0) {
        Write-Host "Extension successfully signed! Check $ArtifactsDir for the .xpi file." -ForegroundColor Green
    }
    else {
        Write-Error "web-ext exited with error code $($process.ExitCode). Command was: $cmdLine"
    }
}
catch {
    Write-Error "Failed to execute web-ext. Error: $_"
}
