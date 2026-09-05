# CNB Release upload facade. The Python uploader owns the API contract and errors.
Param(
    [string]$Repo,
    [string]$Tag,
    [string]$File,
    [string]$AssetName,
    [string]$Token
)
$ErrorActionPreference = "Stop"
if (-not $Repo -or -not $Tag -or -not $File) { throw "Repo, Tag and File are required." }
if (-not $AssetName) { $AssetName = [System.IO.Path]::GetFileName($File) }
if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { throw "Upload file not found: $File" }
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python is required for CNB asset upload." }
$uploadScript = Join-Path $PSScriptRoot "upload_artifact.py"
if (-not (Test-Path -LiteralPath $uploadScript -PathType Leaf)) { throw "Canonical upload script missing: $uploadScript" }
$uploadArgs = @()
if ($python.Name -eq "py.exe" -or $python.Name -eq "py") { $uploadArgs += "-3" }
$uploadArgs += @($uploadScript, "--repo", $Repo, "--tag", $Tag, "--file", $File, "--asset-name", $AssetName)
if ($env:CNB_API_ENDPOINT) { $uploadArgs += @("--endpoint", $env:CNB_API_ENDPOINT) }
elseif ($env:CNB_WEB_ENDPOINT) { $uploadArgs += @("--endpoint", $env:CNB_WEB_ENDPOINT) }
$priorToken = $env:CNB_TOKEN
try {
    if ($Token) { $env:CNB_TOKEN = $Token }
    & $python.Source @uploadArgs
    if ($LASTEXITCODE -ne 0) { throw "CNB asset upload failed; inspect the error above and retry after correcting it." }
} finally {
    $env:CNB_TOKEN = $priorToken
}
