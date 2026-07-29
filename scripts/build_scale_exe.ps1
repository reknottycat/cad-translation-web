Param(
    [string]$Root = (Get-Location).Path,
    [string]$OutDirName = "scale_release_exe",
    [switch]$SkipFrontendBuild,
    [switch]$SkipPyInstaller,
    [switch]$CleanPyInstaller
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path $Root).Path
$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $rootPath $OutDirName
$buildDir = Join-Path $outDir "_build"
$runtimeStageDir = Join-Path $buildDir "runtime_stage"
$payloadPath = Join-Path $outDir "runtime_payload.zip"
$launcherSource = Join-Path $repoRoot "release_exe\launcher.py"
$pyinstallerManifestSource = Join-Path $repoRoot "release_exe\pyinstaller_manifest.py"
$pyinstallerRoot = Join-Path $env:TEMP "cad_scale_release_exe_pyinstaller"
$pyinstallerDistDir = Join-Path $pyinstallerRoot "dist"
$pyinstallerWorkDir = Join-Path $pyinstallerRoot "work"
$pyinstallerSpecDir = Join-Path $pyinstallerRoot "spec"

function Remove-IfExists([string]$PathValue) {
    if (Test-Path -LiteralPath $PathValue) {
        Remove-Item -LiteralPath $PathValue -Recurse -Force
    }
}

function Clear-DirectoryContents([string]$DirectoryPath, [string[]]$KeepNames = @()) {
    if (-not (Test-Path -LiteralPath $DirectoryPath -PathType Container)) {
        return
    }

    Get-ChildItem -LiteralPath $DirectoryPath -Force | ForEach-Object {
        if ($KeepNames -contains $_.Name) {
            return
        }
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
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

function Sanitize-RuntimeConfig([string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        return
    }

    @'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))

def scrub(obj):
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            key_lower = key.lower()
            if key_lower == "api_key" and isinstance(value, str):
                obj[key] = ""
            elif key_lower == "api_key_source":
                obj[key] = "none"
            elif key_lower == "api_key_configured":
                obj[key] = False
            else:
                scrub(value)
    elif isinstance(obj, list):
        for item in obj:
            scrub(item)

scrub(data)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'@ | python - $ConfigPath
}

function Write-Stage2Readme([string]$DestinationPath) {
    @'
# CAD Translation Portable EXE

`scale_release_exe/` is the second-stage portable launcher bundle.

- `launcher.exe` is the main user entrypoint.
- `_internal/` contains the Python runtime and collected libraries bundled by PyInstaller.
- `_build/` stores the local build cache for faster rebuilds and is not required for end-user delivery.
- `runtime_payload.zip` is a temporary sanitized payload kept only when PyInstaller is skipped or a build is interrupted.

This pipeline is separate from the stage-one `scale_release/` runtime package.
'@ | Set-Content -Encoding utf8 -LiteralPath $DestinationPath
}

New-Item -ItemType Directory -Force $outDir | Out-Null
New-Item -ItemType Directory -Force $buildDir | Out-Null
Clear-DirectoryContents -DirectoryPath $outDir -KeepNames @("_build")
Remove-IfExists $payloadPath
Remove-IfExists $runtimeStageDir
Remove-IfExists $pyinstallerDistDir
New-Item -ItemType Directory -Force $pyinstallerRoot | Out-Null
if ($CleanPyInstaller) {
    Remove-IfExists $pyinstallerWorkDir
    Remove-IfExists $pyinstallerSpecDir
}
New-Item -ItemType Directory -Force $runtimeStageDir | Out-Null

Build-Frontend -WorkspaceRoot $rootPath

$backendSource = Join-Path $rootPath "backend"
$frontendDistSource = Join-Path $rootPath "frontend\dist"
$toolsSource = Join-Path $rootPath "tools"

if (-not (Test-Path -LiteralPath $backendSource -PathType Container)) {
    throw "backend directory not found at $backendSource"
}
if (-not (Test-Path -LiteralPath $frontendDistSource -PathType Container)) {
    throw "frontend/dist directory not found at $frontendDistSource"
}
if (-not (Test-Path -LiteralPath $launcherSource -PathType Leaf)) {
    throw "launcher source not found at $launcherSource"
}
if (-not (Test-Path -LiteralPath $pyinstallerManifestSource -PathType Leaf)) {
    throw "PyInstaller manifest source not found at $pyinstallerManifestSource"
}

Copy-DirectoryContents -SourceDir $backendSource -DestinationDir (Join-Path $runtimeStageDir "backend") -ExcludePatterns @(
    '(^|\\)__pycache__(\\|$)',
    '(^|\\)\.pytest_cache(\\|$)',
    '(^|\\)tests(\\|$)',
    '(^|\\)outputs(\\|$)',
    '(^|\\)uploads(\\|$)',
    '(^|\\)temp(\\|$)',
    '(^|\\)\.env$',
    '(^|\\)\.env\.(?!example$)',
    '\.db$',
    '(^|\\)README_MODERN\.md$',
    '(^|\\)test_.*\.py$',
    '(^|\\)simple_test\.py$',
    '(^|\\)setup_and_test\.py$',
    '(^|\\)quick_start\.py$',
    '(^|\\)run_celery\.py$'
)
Copy-DirectoryContents -SourceDir $frontendDistSource -DestinationDir (Join-Path $runtimeStageDir "frontend\dist")
Copy-DirectoryContents -SourceDir $toolsSource -DestinationDir (Join-Path $runtimeStageDir "tools")

$runtimeConfigPath = Join-Path $runtimeStageDir "backend\config\runtime_config.local.json"
Sanitize-RuntimeConfig -ConfigPath $runtimeConfigPath

if (Test-Path -LiteralPath $payloadPath) {
    Remove-Item -LiteralPath $payloadPath -Force
}
Compress-Archive -Path (Join-Path $runtimeStageDir "*") -DestinationPath $payloadPath -Force

if ($SkipPyInstaller) {
    Set-Content -LiteralPath (Join-Path $outDir "launcher.exe") -Value "placeholder launcher" -Encoding ascii
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw "Python was not found for the PyInstaller build."
    }

    $pyArgs = @()
    if ($pythonCommand.Name -eq "py.exe" -or $pythonCommand.Name -eq "py") {
        $pyArgs += "-3"
    }
    $pyArgs += @(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "launcher",
        "--distpath",
        $pyinstallerDistDir,
        "--workpath",
        $pyinstallerWorkDir,
        "--specpath",
        $pyinstallerSpecDir,
        "--add-data",
        "$payloadPath;.",
        $launcherSource
    )
    if ($CleanPyInstaller) {
        $pyArgs += "--clean"
    }

    $manifestArgs = @()
    if ($pythonCommand.Name -eq "py.exe" -or $pythonCommand.Name -eq "py") {
        $manifestArgs += "-3"
    }
    $manifestArgs += @($pyinstallerManifestSource)

    $manifestJson = & $pythonCommand.Source @manifestArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load the PyInstaller manifest."
    }

    $manifest = $manifestJson | ConvertFrom-Json
    foreach ($item in $manifest.hidden_imports) {
        $pyArgs += @("--hidden-import", $item)
    }
    foreach ($item in $manifest.collect_submodules) {
        $pyArgs += @("--collect-submodules", $item)
    }
    foreach ($item in $manifest.collect_data) {
        $pyArgs += @("--collect-data", $item)
    }
    foreach ($item in $manifest.collect_all) {
        $pyArgs += @("--collect-all", $item)
    }

    & $pythonCommand.Source @pyArgs

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $bundleDir = Join-Path $pyinstallerDistDir "launcher"
    if (-not (Test-Path -LiteralPath $bundleDir -PathType Container)) {
        throw "PyInstaller bundle directory not found at $bundleDir"
    }
    Copy-DirectoryContents -SourceDir $bundleDir -DestinationDir $outDir

    if (Test-Path -LiteralPath $payloadPath) {
        Remove-Item -LiteralPath $payloadPath -Force
    }
    if (Test-Path -LiteralPath $runtimeStageDir) {
        Remove-Item -LiteralPath $runtimeStageDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $pyinstallerDistDir) {
        Remove-Item -LiteralPath $pyinstallerDistDir -Recurse -Force
    }
}

Write-Stage2Readme -DestinationPath (Join-Path $outDir "README.md")
Write-Host "Scale release EXE generated: $outDir"
