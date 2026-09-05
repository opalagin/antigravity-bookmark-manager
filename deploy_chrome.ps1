# Google Chrome Web Store Packaging & Deployment Script

param (
    [string]$Version,
    [switch]$NoIncrement
)

$ErrorActionPreference = "Stop"

# Configuration
$ExtensionDir = Join-Path $PSScriptRoot "Chrome Plugin"
$EnvFile = Join-Path $PSScriptRoot ".env"
$ArtifactsDir = Join-Path $ExtensionDir "artifacts"
$TempBuildDir = Join-Path $PSScriptRoot "Chrome_Plugin_Build_Temp"

# Excluded files and folders that should not be included in the Chrome Web Store ZIP package
$ExclusionList = @(
    "artifacts",
    "Chrome_Plugin_Build_Temp",
    ".git",
    ".gitignore",
    "INSTRUCTIONS.md",
    "*.zip",
    ".DS_Store",
    "Thumbs.db"
)

# Function to check if a command exists
function Test-CommandExists {
    param ($Command)
    (Get-Command $Command -ErrorAction SilentlyContinue) -ne $null
}

# Function to get env variable from process or .env file
function Get-EnvVariable {
    param ($Name)
    
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

# 1. Validate Manifest Path
$ManifestPath = Join-Path $ExtensionDir "manifest.json"
if (-not (Test-Path $ManifestPath)) {
    Write-Error "manifest.json not found at '$ManifestPath'!"
    Exit 1
}
$OriginalContent = Get-Content $ManifestPath -Raw

# 2. Determine Version
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
$NewVersion = $null
$CurrentVersion = $null

if ($OriginalContent -match '"version"\s*:\s*"(\d+)\.(\d+)\.(\d+)"') {
    $CurrentVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
    $Major = [int]$Matches[1]
    $Minor = [int]$Matches[2]
    $Patch = [int]$Matches[3]
} else {
    Write-Error "Could not find or parse version string in $ManifestPath (expected format: '""version"": ""X.Y.Z""')"
    Exit 1
}

if (-not [string]::IsNullOrWhiteSpace($Version)) {
    if ($Version -match "^\d+(\.\d+){1,3}$") {
        $NewVersion = $Version
        Write-Host "Using command line override version: $NewVersion" -ForegroundColor Cyan
    } else {
        Write-Error "Invalid version format '$Version'. Chrome Web Store requires 1 to 4 dot-separated integers (e.g. X.Y.Z)"
        Exit 1
    }
} elseif ($NoIncrement) {
    $NewVersion = $CurrentVersion
    Write-Host "Packaging existing manifest version: $NewVersion (NoIncrement flag specified)" -ForegroundColor Cyan
} else {
    # Auto-increment manifest patch version
    $NewPatch = $Patch + 1
    $NewVersion = "$Major.$Minor.$NewPatch"
    Write-Host "Auto-incrementing manifest version: $CurrentVersion -> $NewVersion" -ForegroundColor Cyan
}

# 3. Update manifest version in file if changed
if ($NewVersion -ne $CurrentVersion) {
    $NewContent = $OriginalContent -replace '"version"\s*:\s*"\d+\.\d+\.\d+"', ('"version": "' + $NewVersion + '"')
    [System.IO.File]::WriteAllText($ManifestPath, $NewContent, $utf8WithoutBom)
    Write-Host "Updated manifest version to $NewVersion" -ForegroundColor Green
}

# Helper to revert manifest if something fails
function Revert-Manifest {
    param ($Reason)
    if ($NewVersion -ne $CurrentVersion) {
        Write-Host "Reverting manifest version to original ($CurrentVersion) because: $Reason" -ForegroundColor Yellow
        [System.IO.File]::WriteAllText($ManifestPath, $OriginalContent, $utf8WithoutBom)
    }
}

# 4. Prepare Clean Temporary Packaging Directory
Write-Host "Preparing clean source files for packaging..." -ForegroundColor Cyan
if (Test-Path $TempBuildDir) {
    Remove-Item -Path $TempBuildDir -Recurse -Force | Out-Null
}
New-Item -ItemType Directory -Path $TempBuildDir | Out-Null

try {
    # Copy source files to the temporary build folder, excluding development files and artifacts
    Get-ChildItem -Path $ExtensionDir | Where-Object {
        $itemName = $_.Name
        $isExcluded = $false
        foreach ($pattern in $ExclusionList) {
            if ($itemName -like $pattern) {
                $isExcluded = $true
                break
            }
        }
        -not $isExcluded
    } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $TempBuildDir -Recurse -Force
    }

    # Verify manifest.json exists at root of temp build dir
    $StagedManifest = Join-Path $TempBuildDir "manifest.json"
    if (-not (Test-Path $StagedManifest)) {
        throw "manifest.json is missing from staging directory!"
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

    # Zip the temporary directory (contents at the root of the archive)
    Write-Host "Compressing extension into ZIP archive..." -ForegroundColor Cyan
    Compress-Archive -Path "$TempBuildDir\*" -DestinationPath $ZipPath -Force

    if (-not (Test-Path $ZipPath)) {
        throw "Failed to create archive at '$ZipPath'"
    }

    $ZipItem = Get-Item $ZipPath
    $ZipSizeKB = [Math]::Round($ZipItem.Length / 1KB, 2)
    Write-Host "Zipped package successfully created!" -ForegroundColor Green
    Write-Host "Package size: $ZipSizeKB KB" -ForegroundColor Gray
}
catch {
    Revert-Manifest "An error occurred during packaging: $_"
    Write-Error "Failed to package Chrome extension. Error: $_"
    Exit 1
}
finally {
    # Cleanup temporary directory
    Write-Host "Cleaning up temporary build folder..." -ForegroundColor Cyan
    if (Test-Path $TempBuildDir) {
        Remove-Item -Path $TempBuildDir -Recurse -Force | Out-Null
    }
}

# 5. Output Summary & Manual Upload Instructions
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "   Chrome Web Store Artifact Ready for Manual Upload" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host " Version : $NewVersion" -ForegroundColor Cyan
Write-Host " File    : $ZipPath" -ForegroundColor White
Write-Host " Size    : $ZipSizeKB KB" -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps (Manual Store Upload):" -ForegroundColor Yellow
Write-Host " 1. Open Google Chrome Web Store Developer Dashboard:"
Write-Host "    https://chrome.google.com/webstore/devconsole" -ForegroundColor Cyan
Write-Host " 2. Click your extension item (or click '+ New Item' if this is your first upload)."
Write-Host " 3. Click the 'Package' tab in the left sidebar."
Write-Host " 4. Click 'Upload new package' and select the ZIP file above:"
Write-Host "    $ZipPath" -ForegroundColor White
Write-Host " 5. Fill out or update the Store Listing, Privacy, and Distribution sections."
Write-Host " 6. Click 'Submit for review'."
Write-Host ""
Write-Host "Note: To automate uploads via Chrome Web Store API in the future, API credentials" -ForegroundColor Gray
Write-Host "      (CHROME_EXTENSION_ID, CHROME_CLIENT_ID, CHROME_CLIENT_SECRET, CHROME_REFRESH_TOKEN)" -ForegroundColor Gray
Write-Host "      can be configured in .env." -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Green
