# Microsoft Edge Add-ons Store Deployment & Packaging Script

param (
    [string]$Version
)

$ErrorActionPreference = "Stop"

# Configuration
$ExtensionDir = Join-Path $PSScriptRoot "Chrome Plugin"
$EnvFile = Join-Path $PSScriptRoot ".env"
$ArtifactsDir = Join-Path $ExtensionDir "artifacts"
$TempBuildDir = Join-Path $PSScriptRoot "Chrome_Plugin_Build_Temp"

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

Write-Host "Checking prerequisites..." -ForegroundColor Cyan

# Get original manifest content
$ManifestPath = Join-Path $ExtensionDir "manifest.json"
if (-not (Test-Path $ManifestPath)) {
    Write-Error "manifest.json not found at '$ManifestPath'!"
    Exit 1
}
$OriginalContent = Get-Content $ManifestPath -Raw

# Determine new version
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
$NewVersion = $null

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    if ($Version -match "^\d+\.\d+\.\d+$") {
        $NewVersion = $Version
        Write-Host "Using command line override version: $NewVersion" -ForegroundColor Cyan
    } else {
        Write-Error "Invalid version format '$Version'. Expected format: X.Y.Z"
        Exit 1
    }
} else {
    # Auto-increment manifest version
    Write-Host "Auto-incrementing manifest version..." -ForegroundColor Cyan
    if ($OriginalContent -match '"version"\s*:\s*"(\d+)\.(\d+)\.(\d+)"') {
        $CurrentVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
        $Major = [int]$Matches[1]
        $Minor = [int]$Matches[2]
        $Patch = [int]$Matches[3]
        $NewPatch = $Patch + 1
        $NewVersion = "$Major.$Minor.$NewPatch"
    } else {
        Write-Error "Could not find or parse version string in $ManifestPath (expected format: '""version"": ""X.Y.Z""')"
        Exit 1
    }
}

# Update manifest version in file
$NewContent = $OriginalContent -replace '"version"\s*:\s*"\d+\.\d+\.\d+"', ('"version": "' + $NewVersion + '"')
[System.IO.File]::WriteAllText($ManifestPath, $NewContent, $utf8WithoutBom)

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    Write-Host "Set manifest version to $NewVersion" -ForegroundColor Green
} else {
    Write-Host "Successfully incremented manifest version from $CurrentVersion to $NewVersion" -ForegroundColor Green
}

# Helper to revert manifest if something fails
function Revert-Manifest {
    param ($Reason)
    Write-Host "Reverting manifest version to original because: $Reason" -ForegroundColor Yellow
    [System.IO.File]::WriteAllText($ManifestPath, $OriginalContent, $utf8WithoutBom)
}

# Prepare Clean Temporary Packaging Directory
Write-Host "Preparing clean source files for packaging..." -ForegroundColor Cyan
if (Test-Path $TempBuildDir) {
    Remove-Item -Path $TempBuildDir -Recurse -Force | Out-Null
}
New-Item -ItemType Directory -Path $TempBuildDir | Out-Null

try {
    # Copy source files to the temporary build folder, excluding artifacts/build directories
    Get-ChildItem -Path $ExtensionDir | Where-Object {
        $_.Name -ne "artifacts" -and $_.Name -ne "Chrome_Plugin_Build_Temp" -and $_.Name -ne ".git"
    } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $TempBuildDir -Recurse -Force
    }

    # Ensure artifacts directory exists
    if (-not (Test-Path $ArtifactsDir)) {
        New-Item -ItemType Directory -Path $ArtifactsDir | Out-Null
    }

    $ZipName = "chrome-plugin-v$NewVersion.zip"
    $ZipPath = Join-Path $ArtifactsDir $ZipName

    if (Test-Path $ZipPath) {
        Remove-Item -Path $ZipPath -Force | Out-Null
    }

    # Zip the temporary directory
    Write-Host "Compressing extension into ZIP archive..." -ForegroundColor Cyan
    Compress-Archive -Path "$TempBuildDir\*" -DestinationPath $ZipPath -Force
    Write-Host "Zipped package successfully created: $ZipPath" -ForegroundColor Green
}
catch {
    Revert-Manifest "An error occurred during packaging: $_"
    Write-Error "Failed to package extension. Error: $_"
    Exit 1
}
finally {
    # Cleanup temporary directory
    Write-Host "Cleaning up temporary build folder..." -ForegroundColor Cyan
    if (Test-Path $TempBuildDir) {
        Remove-Item -Path $TempBuildDir -Recurse -Force | Out-Null
    }
}

# 5. Handle Store Submission / Publication
$ProductID = Get-EnvVariable "EDGE_PRODUCT_ID"
$ClientID = Get-EnvVariable "EDGE_CLIENT_ID"
$ApiKey = Get-EnvVariable "EDGE_API_KEY"

if ([string]::IsNullOrWhiteSpace($ProductID) -or [string]::IsNullOrWhiteSpace($ClientID) -or [string]::IsNullOrWhiteSpace($ApiKey)) {
    Write-Host "`nMicrosoft Edge Add-ons Store API credentials are missing from environment / $EnvFile" -ForegroundColor Yellow
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "Zipped package was successfully generated for manual upload!" -ForegroundColor Green
    Write-Host "Zip File: $ZipPath" -ForegroundColor Green
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "To enable automated store submission in the future, follow these steps:"
    Write-Host "1. Create your extension and upload the first version manually at:"
    Write-Host "   https://partner.microsoft.com/dashboard/microsoftedge/public/login"
    Write-Host "2. Go to the 'Publish API' settings in Microsoft Partner Center and generate API credentials."
    Write-Host "3. Save the credentials to your local .env file using these keys:"
    Write-Host "   EDGE_PRODUCT_ID=<Your Product UUID>"
    Write-Host "   EDGE_CLIENT_ID=<Your Client ID>"
    Write-Host "   EDGE_API_KEY=<Your API Key>"
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Yellow
    Exit 0
}

# Credentials found! Attempting REST API Upload and Publish
Write-Host "`nEdge Store API credentials found! Triggering automated upload..." -ForegroundColor Cyan
Write-Host "Product ID: $ProductID" -ForegroundColor Gray
Write-Host "Client ID : $ClientID" -ForegroundColor Gray

$UploadUrl = "https://api.addons.microsoftedge.microsoft.com/v1/products/$ProductID/submissions/draft/package"
$Headers = @{
    "Authorization" = "ApiKey $ApiKey"
    "X-ClientID"    = $ClientID
}

try {
    # 1. Upload ZIP package
    Write-Host "Uploading package file to Partner Center..." -ForegroundColor Cyan
    $FileBytes = [System.IO.File]::ReadAllBytes($ZipPath)
    
    # Send request using Invoke-WebRequest to extract the Location response header
    $UploadResponse = Invoke-WebRequest -Uri $UploadUrl -Method Post -Headers $Headers -Body $FileBytes -ContentType "application/zip" -SkipHttpErrorCheck

    if ($UploadResponse.StatusCode -ne 202) {
        throw "Upload failed with status code $($UploadResponse.StatusCode): $($UploadResponse.Content)"
    }

    # Location header contains the operation URL to check status
    $OperationUrl = $UploadResponse.Headers["Location"]
    if ([string]::IsNullOrWhiteSpace($OperationUrl)) {
        throw "Location header was missing from the upload response. Cannot check operation status."
    }

    # If the URL is relative, prepend the base domain
    if ($OperationUrl -notmatch "^http") {
        $OperationUrl = "https://api.addons.microsoftedge.microsoft.com$OperationUrl"
    }

    Write-Host "Upload accepted. Tracking operation status..." -ForegroundColor Cyan
    Write-Host "Tracking URL: $OperationUrl" -ForegroundColor Gray

    # 2. Poll the upload status
    $OperationComplete = $false
    $RetryCount = 0
    $MaxRetries = 30 # Poll for up to 5 minutes
    
    while (-not $OperationComplete -and $RetryCount -lt $MaxRetries) {
        Start-Sleep -Seconds 10
        $RetryCount++
        
        Write-Host "Polling upload status (Attempt $RetryCount/$MaxRetries)..." -ForegroundColor Gray
        $StatusResponse = Invoke-RestMethod -Uri $OperationUrl -Method Get -Headers $Headers
        
        $Status = $StatusResponse.status
        Write-Host "Status: $Status" -ForegroundColor Cyan
        
        if ($Status -eq "Succeeded") {
            $OperationComplete = $true
            Write-Host "Package upload and validation succeeded!" -ForegroundColor Green
        }
        elseif ($Status -eq "Failed") {
            throw "Package processing failed on Microsoft servers. Message: $($StatusResponse.message)"
        }
        elseif ($Status -ne "InProgress") {
            throw "Unexpected operation status: $Status"
        }
    }

    if (-not $OperationComplete) {
        throw "Timed out waiting for package verification to complete."
    }

    # 3. Publish the submission draft
    Write-Host "Publishing the submission draft..." -ForegroundColor Cyan
    $PublishUrl = "https://api.addons.microsoftedge.microsoft.com/v1/products/$ProductID/submissions/draft/publish"
    
    $PublishResponse = Invoke-WebRequest -Uri $PublishUrl -Method Post -Headers $Headers -SkipHttpErrorCheck
    
    if ($PublishResponse.StatusCode -ne 202) {
        throw "Publish request failed with status code $($PublishResponse.StatusCode): $($PublishResponse.Content)"
    }

    Write-Host "Successfully requested publish! The extension is now undergoing Microsoft certification review." -ForegroundColor Green
}
catch {
    Revert-Manifest "Automated store deployment failed: $_"
    Write-Error "Store submission failed. Error: $_"
    Exit 1
}
