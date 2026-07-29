Param(
    [string]$Root = (Get-Location).Path,
    [string]$OutFile = 'docs/modern/AUTO_FILE_INDEX.md'
)

$rootPath = (Resolve-Path $Root).Path
$outPath = Join-Path $rootPath $OutFile

$exclude = @('node_modules', 'frontend/node_modules', 'backend/outputs', '__pycache__', '.git', '.conda', '.trae', 'logs', 'scale_release')

function IsExcluded([string]$p) {
    $n = $p.Replace('/', '\\')
    foreach ($x in $exclude) {
        $xe = $x.Replace('/', '\\')
        if ($n -like "*\\$xe\\*" -or $n -like "*\\$xe") { return $true }
    }
    return $false
}

$lines = @('# Auto File Index', '', "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", '')

Get-ChildItem -Path $rootPath -Recurse -Force | ForEach-Object {
    if ($_.PSIsContainer) { return }
    if (IsExcluded $_.FullName) { return }
    if ($_.Extension -eq '.zip') { return }
    $rel = $_.FullName.Substring($rootPath.Length).TrimStart('\\')
    $lines += "- ``$rel``"
}

$dir = Split-Path $outPath -Parent
New-Item -ItemType Directory -Force $dir | Out-Null
$lines | Set-Content -Encoding UTF8 $outPath
Write-Host "Generated: $outPath"
