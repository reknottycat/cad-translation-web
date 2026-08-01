Param(
    [string]$Root = (Get-Location).Path,
    [string]$OutDirName = "scale_release",
    [string]$ZipName = "scale_release.zip",
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path $Root).Path
$outDir = Join-Path $rootPath $OutDirName
$zipPath = Join-Path $rootPath $ZipName

function Remove-IfExists([string]$PathValue) {
    if (Test-Path -LiteralPath $PathValue) {
        Remove-Item -LiteralPath $PathValue -Recurse -Force
    }
}

function Copy-DirectoryContents([string]$SourceDir, [string]$DestinationDir, [string[]]$ExcludePatterns = @()) {
    if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
        return
    }

    Get-ChildItem -LiteralPath $SourceDir -Recurse -Force | ForEach-Object {
        $item = $_
        $relative = $item.FullName.Substring($SourceDir.Length).TrimStart('\')
        if ([string]::IsNullOrWhiteSpace($relative)) {
            return
        }

        foreach ($pattern in $ExcludePatterns) {
            if ($relative -match $pattern) {
                return
            }
        }

        $target = Join-Path $DestinationDir $relative
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Force $target | Out-Null
            return
        }

        $targetDir = Split-Path $target -Parent
        New-Item -ItemType Directory -Force $targetDir | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $target -Force
    }
}

function Build-Frontend([string]$WorkspaceRoot) {
    if ($SkipFrontendBuild) {
        Write-Host "Skipping frontend build because -SkipFrontendBuild was provided."
        return
    }

    $frontendDir = Join-Path $WorkspaceRoot "frontend"
    $packageJson = Join-Path $frontendDir "package.json"
    if (-not (Test-Path -LiteralPath $packageJson)) {
        Write-Host "Frontend package.json not found. Skipping frontend build."
        return
    }

    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $npmCommand) {
        throw "npm was not found. Install Node.js or rerun with -SkipFrontendBuild."
    }

    Write-Host "Building frontend dist..."
    Push-Location $frontendDir
    try {
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed."
        }
    }
    finally {
        Pop-Location
    }
}

function Write-DeliveryLauncher([string]$DestinationPath) {
    @'
@echo off
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON=py -3"
    ) else (
        echo Python was not found. Please install Python 3.10+ and try again.
        pause
        exit /b 1
    )
)

set "DELIVERY_ROOT=%CD%"
set "BACKEND_ENTRY=%DELIVERY_ROOT%\backend\run_server.py"
set "FRONTEND_DIST=%DELIVERY_ROOT%\frontend\dist"
set "APP_URL=http://127.0.0.1:8000/"

echo ============================================================
echo CAD Translation Delivery Launcher
echo ============================================================
echo Delivery root: %DELIVERY_ROOT%
echo Backend entry: %BACKEND_ENTRY%
echo Frontend dist: %FRONTEND_DIST%
echo Service URL: %APP_URL%
echo ============================================================

if not exist "%BACKEND_ENTRY%" (
    echo Backend entry was not found.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIST%\index.html" (
    echo Frontend dist was not found.
    pause
    exit /b 1
)

set "ASYNC_TASKS_MODE=local"
set "HOST=127.0.0.1"
set "PORT=8000"
set "DEBUG=false"

start "" cmd /c "timeout /t 3 /nobreak >nul && start \"\" \"%APP_URL%\""
%PYTHON% "%BACKEND_ENTRY%"

endlocal
'@ | Set-Content -Encoding ascii -LiteralPath $DestinationPath
}

function Write-DeliveryReadme([string]$DestinationPath) {
    @'
# CAD Translation Runtime Bundle

`scale_release/` is the runtime bundle for end users.

It is a runnable delivery package, not a source checkout. The bundle keeps the backend runtime, the built frontend static files, the required tools, and the one-click launcher.

## Included

- `backend/`: backend runtime code
- `frontend/dist/`: built frontend assets
- `tools/`: runtime helper tools
- `docs/modern/`: cleaned release documentation
- `start_delivery.bat`: one-click launcher
- `requirements.txt`: Python dependency list

## Start

- Install Python 3.10 or newer.
- Install dependencies with `pip install -r requirements.txt`.
- Double-click `start_delivery.bat`.
- The launcher opens `http://127.0.0.1:8000/` in your browser.

## Notes

- The launcher runs the backend in single-process mode.
- The frontend is served from the packaged `frontend/dist` folder.
- This runtime bundle intentionally excludes development-only files such as frontend source, tests, and `agent-harness`.
'@ | Set-Content -Encoding utf8 -LiteralPath $DestinationPath
}

Remove-IfExists $outDir
Remove-IfExists $zipPath
New-Item -ItemType Directory -Force $outDir | Out-Null

Build-Frontend -WorkspaceRoot $rootPath

$backendSource = Join-Path $rootPath "backend"
$frontendDistSource = Join-Path $rootPath "frontend\dist"
$toolsSource = Join-Path $rootPath "tools"
$docsModernSource = Join-Path $rootPath "docs\modern"

if (-not (Test-Path -LiteralPath $backendSource -PathType Container)) {
    throw "backend directory not found at $backendSource"
}

if (-not (Test-Path -LiteralPath $frontendDistSource -PathType Container)) {
    throw "frontend/dist directory not found at $frontendDistSource"
}

Copy-DirectoryContents -SourceDir $backendSource -DestinationDir (Join-Path $outDir "backend") -ExcludePatterns @(
    '(^|\\)__pycache__(\\|$)',
    '(^|\\)\.pytest_cache(\\|$)',
    '(^|\\)tests(\\|$)',
    '(^|\\)outputs(\\|$)',
    '(^|\\)uploads(\\|$)',
    '(^|\\)temp(\\|$)',
    '(^|\\)\.env$',
    '(^|\\)\.env\.(?!example$)',
    '(^|\\)runtime_config\.local\.json$',
    '\.db$',
    '(^|\\)README_MODERN\.md$',
    '(^|\\)test_.*\.py$',
    '(^|\\)simple_test\.py$',
    '(^|\\)setup_and_test\.py$',
    '(^|\\)quick_start\.py$',
    '(^|\\)run_celery\.py$'
)

Copy-DirectoryContents -SourceDir $frontendDistSource -DestinationDir (Join-Path $outDir "frontend\dist")
Copy-DirectoryContents -SourceDir $toolsSource -DestinationDir (Join-Path $outDir "tools")
Copy-DirectoryContents -SourceDir $docsModernSource -DestinationDir (Join-Path $outDir "docs\modern") -ExcludePatterns @(
    '(^|\\)AUTO_FILE_INDEX\.md$'
)

foreach ($fileName in @("requirements.txt")) {
    $sourcePath = Join-Path $rootPath $fileName
    if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $outDir $fileName) -Force
    }
}

$secretFiles = Get-ChildItem -LiteralPath $outDir -Recurse -Force -File -ErrorAction Stop |
    Where-Object { $_.Name -eq '.env' -or $_.Name -eq 'runtime_config.local.json' }
if ($secretFiles) {
    throw "Refusing to package secret files: $($secretFiles.FullName -join ', ')"
}

Write-DeliveryLauncher -DestinationPath (Join-Path $outDir "start_delivery.bat")
Write-DeliveryReadme -DestinationPath (Join-Path $outDir "README.md")

Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zipPath -Force

Write-Host "Scale release generated: $outDir"
Write-Host "Zip package generated: $zipPath"
