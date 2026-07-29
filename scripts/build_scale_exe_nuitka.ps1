Param(
    [string]$Root = (Get-Location).Path,
    [string]$OutDirName = "scale_release_exe_nuitka",
    [switch]$SkipFrontendBuild,
    [switch]$SkipNuitka,
    [switch]$CleanNuitka
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
$nuitkaOutputDir = Join-Path $buildDir "nuitka_output"
$nuitkaBundleDir = Join-Path $nuitkaOutputDir "launcher.dist"

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
# CAD Translation Portable EXE (Nuitka)

`scale_release_exe_nuitka/` is the Nuitka-based second-stage portable launcher bundle.

- `launcher.exe` is the main user entrypoint.
- Nuitka standalone dependencies are copied next to `launcher.exe`.
- `runtime_payload.zip` is the sanitized delivery copy of backend, frontend, and tools.
- `runtime/` is created on first launch from the payload.
- `_build/` stores local Nuitka and staging caches and is not required for end-user delivery.

This pipeline is separate from the stage-one `scale_release/` runtime package and from the legacy stage-two delivery chain.
'@ | Set-Content -Encoding utf8 -LiteralPath $DestinationPath
}

function Get-PythonCommand() {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw "Python was not found for the Nuitka build."
    }
    return $pythonCommand
}

function Get-PythonArgsPrefix([object]$PythonCommand) {
    if ($PythonCommand.Name -eq "py.exe" -or $PythonCommand.Name -eq "py") {
        return @("-3")
    }
    return @()
}

function Get-RuntimeManifest([object]$PythonCommand, [string[]]$PythonArgsPrefix) {
    if (-not (Test-Path -LiteralPath $pyinstallerManifestSource -PathType Leaf)) {
        throw "Runtime manifest source not found at $pyinstallerManifestSource"
    }

    $manifestJson = & $PythonCommand.Source @PythonArgsPrefix $pyinstallerManifestSource
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load the runtime manifest."
    }

    return $manifestJson | ConvertFrom-Json
}

New-Item -ItemType Directory -Force $outDir | Out-Null
New-Item -ItemType Directory -Force $buildDir | Out-Null
Clear-DirectoryContents -DirectoryPath $outDir -KeepNames @("_build")
Remove-IfExists $payloadPath
Remove-IfExists $runtimeStageDir
Remove-IfExists (Join-Path $outDir "runtime")
Remove-IfExists (Join-Path $outDir "launcher.exe")
Remove-IfExists (Join-Path $outDir "README.md")

if ($CleanNuitka) {
    Remove-IfExists $nuitkaOutputDir
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
    throw "Nuitka launcher source not found at $launcherSource"
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

Compress-Archive -Path (Join-Path $runtimeStageDir "*") -DestinationPath $payloadPath -Force

if ($SkipNuitka) {
    Set-Content -LiteralPath (Join-Path $outDir "launcher.exe") -Value "placeholder launcher" -Encoding ascii
} else {
    $pythonCommand = Get-PythonCommand
    $pythonArgsPrefix = Get-PythonArgsPrefix -PythonCommand $pythonCommand
    $runtimeManifest = Get-RuntimeManifest -PythonCommand $pythonCommand -PythonArgsPrefix $pythonArgsPrefix

    & $pythonCommand.Source @pythonArgsPrefix -m nuitka --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka is not installed in the active Python environment. Run `python -m pip install nuitka` and try again."
    }

    Remove-IfExists $nuitkaOutputDir
    New-Item -ItemType Directory -Force $nuitkaOutputDir | Out-Null

    $nuitkaArgs = @()
    $nuitkaArgs += $pythonArgsPrefix
    $nuitkaArgs += @(
        "-m",
        "nuitka",
        "--mode=standalone",
        "--windows-console-mode=force",
        "--assume-yes-for-downloads",
        "--output-filename=launcher",
        "--nofollow-import-to=run_server",
        "--nofollow-import-to=backend",
        "--output-dir=$nuitkaOutputDir",
        $launcherSource
    )
    if ($CleanNuitka) {
        $nuitkaArgs += "--remove-output"
    }
    foreach ($item in $runtimeManifest.hidden_imports) {
        $nuitkaArgs += "--include-module=$item"
    }
    foreach ($item in $runtimeManifest.collect_submodules) {
        $nuitkaArgs += "--include-package=$item"
    }
    foreach ($item in $runtimeManifest.collect_data) {
        $nuitkaArgs += "--include-package-data=$item"
    }
    foreach ($item in $runtimeManifest.collect_all) {
        $nuitkaArgs += "--include-package=$item"
        $nuitkaArgs += "--include-package-data=$item"
    }

    & $pythonCommand.Source @nuitkaArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka build failed."
    }
    if (-not (Test-Path -LiteralPath $nuitkaBundleDir -PathType Container)) {
        throw "Nuitka bundle directory not found at $nuitkaBundleDir"
    }

    Copy-DirectoryContents -SourceDir $nuitkaBundleDir -DestinationDir $outDir
}

Write-Stage2Readme -DestinationPath (Join-Path $outDir "README.md")
Write-Host "Scale release EXE (Nuitka) generated: $outDir"
