# Security Audit for scale_release/
# Run from project root:
#   & .\.agents\skills\cad-translation-dev\scripts\security-audit.ps1 -ReleaseDir <bundle-path>
#
# This script is intentionally read-only. Fix the source or build script and
# rebuild a bundle instead of deleting files from the bundle during the audit.

param(
    [string]$ReleaseDir = "scale_release"
)

$ErrorActionPreference = "Stop"
$hasErrors = $false

function Write-Result {
    param(
        [string]$Label,
        [bool]$Pass,
        [object]$Detail = $null
    )

    $icon = if ($Pass) { "PASS" } else { "FAIL" }
    $color = if ($Pass) { "Green" } else { "Red" }
    Write-Host "[$icon] $Label" -ForegroundColor $color

    $items = @($Detail | Where-Object { $null -ne $_ -and "$($_)" -ne "" })
    foreach ($item in $items) {
        Write-Host "      $item" -ForegroundColor Gray
    }
}

function Convert-ToRelativePath {
    param(
        [string]$BasePath,
        [string]$ChildPath
    )

    $baseUri = [System.Uri]::new(($BasePath.TrimEnd('\') + '\'))
    $childUri = [System.Uri]::new($ChildPath)
    return [System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($childUri).ToString()
    ).Replace('/', '\')
}

if (-not (Test-Path -LiteralPath $ReleaseDir -PathType Container)) {
    Write-Error "Release directory not found: $ReleaseDir"
    exit 1
}

$releaseRoot = (Get-Item -LiteralPath $ReleaseDir -Force).FullName.TrimEnd('\')
$allFiles = @(Get-ChildItem -LiteralPath $releaseRoot -Recurse -Force -File)
$allDirectories = @(Get-ChildItem -LiteralPath $releaseRoot -Recurse -Force -Directory)
$relativeFiles = @(
    $allFiles | ForEach-Object {
        Convert-ToRelativePath -BasePath $releaseRoot -ChildPath $_.FullName
    }
)
$relativeDirectories = @(
    $allDirectories | ForEach-Object {
        Convert-ToRelativePath -BasePath $releaseRoot -ChildPath $_.FullName
    }
)
$allRelativePaths = @($relativeDirectories + $relativeFiles)

Write-Host ""
Write-Host "=== CAD Translation System Release Security Audit ==="
Write-Host "Target: $releaseRoot"
Write-Host ""

# 1. Recursively reject content that is never part of the runtime bundle.
# frontend/dist is intentionally allowed; generic dist is therefore not in
# this list, while Python packaging leftovers (.egg-info/build) are rejected.
$forbiddenChecks = @(
    [PSCustomObject]@{
        Label = "No database files"
        Pattern = '(^|\\)[^\\]+\.(db|sqlite|sqlite3)$'
    },
    [PSCustomObject]@{
        Label = "No local runtime secrets/config"
        Pattern = '(^|\\)(runtime_config\.local\.json|local_settings\.py)$'
    },
    [PSCustomObject]@{
        Label = "No non-example environment files"
        Pattern = '(^|\\)\.env(\.(?!example$)[^\\]*)?$'
    },
    [PSCustomObject]@{
        Label = "No virtual environments or dependency caches"
        Pattern = '(^|\\)(\.venv|venv|env|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.tox)(\\|$)'
    },
    [PSCustomObject]@{
        Label = "No packaging leftovers"
        Pattern = '(^|\\)(build|[^\\]+\.egg-info)(\\|$)'
    },
    [PSCustomObject]@{
        Label = "No generated logs or working data"
        Pattern = '(^|\\)(log|logs|output|outputs|upload|uploads|temp|tmp)(\\|$)'
    },
    [PSCustomObject]@{
        Label = "No test directories"
        Pattern = '(^|\\)(test|tests|testing)(\\|$)'
    },
    [PSCustomObject]@{
        Label = "No Python bytecode files"
        Pattern = '(^|\\)[^\\]+\.pyc$'
    }
)

foreach ($check in $forbiddenChecks) {
    $matches = @($allRelativePaths | Where-Object { $_ -match $check.Pattern })
    Write-Result -Label $check.Label -Pass ($matches.Count -eq 0) -Detail $matches
    if ($matches.Count -gt 0) {
        $hasErrors = $true
    }
}

# 2. Hardcoded API keys in text files that could be shipped or logged.
$keyPatterns = @(
    '(?i)\bsk-[a-zA-Z0-9]{20,}\b',
    '(?i)\bak-[a-zA-Z0-9]{20,}\b',
    '(?i)["'']api_key["'']\s*[:=]\s*["''][^"'']{20,}["'']'
)
$textExtensions = @('.py', '.json', '.md', '.bat', '.ps1', '.toml', '.ini', '.yaml', '.yml', '.txt')
$leaks = @()
foreach ($file in $allFiles) {
    if ($file.Extension.ToLowerInvariant() -notin $textExtensions) {
        continue
    }

    $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($null -eq $content) {
        continue
    }

    foreach ($pattern in $keyPatterns) {
        if ($content -match $pattern) {
            $relative = Convert-ToRelativePath -BasePath $releaseRoot -ChildPath $file.FullName
            $leaks += "${relative}: matched API-key pattern"
            break
        }
    }
}
Write-Result -Label "No hardcoded API keys in text files" -Pass ($leaks.Count -eq 0) -Detail $leaks
if ($leaks.Count -gt 0) {
    $hasErrors = $true
}

# 3. Source-only frontend files must not be shipped; the built dist is allowed.
$frontendSource = @($allRelativePaths | Where-Object { $_ -match '(^|\\)frontend\\src(\\|$)' })
Write-Result -Label "No frontend/src" -Pass ($frontendSource.Count -eq 0) -Detail $frontendSource
if ($frontendSource.Count -gt 0) {
    $hasErrors = $true
}

# 4. Test files can also appear outside a tests/ directory.
$testFiles = @($relativeFiles | Where-Object {
    $_ -match '(^|\\)(test_[^\\]*\.py|[^\\]+_test\.py|conftest\.py)$'
})
Write-Result -Label "No test Python files" -Pass ($testFiles.Count -eq 0) -Detail $testFiles
if ($testFiles.Count -gt 0) {
    $hasErrors = $true
}

# 5. Old Electron files are not part of the runtime bundle root.
$electronRootFiles = @("main.js", "preload.js", "package.json", "package-lock.json")
$foundElectron = @($electronRootFiles | Where-Object {
    Test-Path -LiteralPath (Join-Path $releaseRoot $_) -PathType Leaf
})
Write-Result -Label "No Electron artifacts in root" -Pass ($foundElectron.Count -eq 0) -Detail $foundElectron
if ($foundElectron.Count -gt 0) {
    $hasErrors = $true
}

# 6. The generated bundle has a fixed top-level contract.
$expectedTop = @(
    "backend", "cli", "docs", "frontend", "tools",
    "cad-cli.bat", "CLI.md", "install_cli.bat",
    "README.md", "requirements.txt", "start_delivery.bat"
)
$actualTop = @(
    Get-ChildItem -LiteralPath $releaseRoot -Force |
        Select-Object -ExpandProperty Name
)
$unexpected = @($actualTop | Where-Object { $_ -notin $expectedTop })
$missing = @($expectedTop | Where-Object { $_ -notin $actualTop })
$topLevelProblems = @($unexpected + $missing)
Write-Result -Label "Top-level only expected items" -Pass ($topLevelProblems.Count -eq 0) -Detail $topLevelProblems
if ($topLevelProblems.Count -gt 0) {
    $hasErrors = $true
}

# 7. Required runtime and CLI files must be present in every publishable bundle.
$requiredFiles = @(
    "backend\run_server.py",
    "backend\app\version.py",
    "frontend\dist\index.html",
    "tools\libredwg\0.13.3-win64\dwg2dxf.exe",
    "cli\cad_translate\cli.py",
    "cli\setup.py",
    "cad-cli.bat",
    "install_cli.bat",
    "CLI.md",
    "start_delivery.bat"
)
$missingFiles = @($requiredFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $releaseRoot $_) -PathType Leaf)
})
Write-Result -Label "Required runtime and CLI files" -Pass ($missingFiles.Count -eq 0) -Detail $missingFiles
if ($missingFiles.Count -gt 0) {
    $hasErrors = $true
}

Write-Host ""
if ($hasErrors) {
    Write-Host "AUDIT FAILED — fix the source/build process and rebuild before releasing." -ForegroundColor Red
    exit 1
}

Write-Host "AUDIT PASSED — release is clean." -ForegroundColor Green
exit 0
