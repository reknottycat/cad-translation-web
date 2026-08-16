# Uploads a file as an asset to a CNB Git Release.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/upload_release_asset.ps1 `
#     -Repo "star_fu/cad-translation-web" `
#     -Tag "v1.0.0" `
#     -File "scale_release_exe.zip" `
#     -AssetName "cad-translation-web-v1.0.0-windows-exe.zip" `
#     -Token "<CNB_TOKEN>"
#
# Environment:
#   CNB_WEB_ENDPOINT  CNB 站点地址，默认 https://cnb.cool
#   CNB_TOKEN         构建令牌（流水线中自动注入）
#
# Flow (CNB Releases REST API):
#   1. GET  /{repo}/-/releases/tags/{tag}            -> release_id
#   2. POST /{repo}/-/releases/{id}/asset-upload-url -> 上传地址
#   3. PUT  上传地址（流式上传文件内容）
#   4. POST /{repo}/-/releases/{id}/asset-upload-confirmation/{token}/{path} -> 确认
#
# 该脚本是"尽力而为"：失败时打印警告并返回 0，不阻塞流水线主流程。

Param(
    [string]$Repo,
    [string]$Tag,
    [string]$File,
    [string]$AssetName,
    [string]$Token
)

$ErrorActionPreference = "Stop"

$endpoint = $env:CNB_WEB_ENDPOINT
if (-not $endpoint) { $endpoint = "https://cnb.cool" }
$endpoint = $endpoint.TrimEnd("/")

if (-not $Token) { $Token = $env:CNB_TOKEN }
if (-not $Repo) { throw "Repo is required (e.g. org/repo)." }
if (-not $Tag) { throw "Tag is required." }
if (-not $File) { throw "File is required." }
if (-not $AssetName) { $AssetName = [System.IO.Path]::GetFileName($File) }
if (-not (Test-Path -LiteralPath $File)) { throw "File not found: $File" }

if (-not $Token) {
    Write-Host "WARN: CNB_TOKEN not set; skip upload." -ForegroundColor Yellow
    exit 0
}

$fileSize = (Get-Item -LiteralPath $File).Length

function Invoke-CnbApi([string]$Method, [string]$Path, [object]$Body = $null) {
    $headers = @{
        "Authorization" = "Bearer $Token"
        "Accept"        = "application/json"
    }
    $params = @{
        Uri     = "$endpoint$Path"
        Method  = $Method
        Headers = $headers
    }
    if ($null -ne $Body) {
        $params["Body"] = ($Body | ConvertTo-Json -Depth 10)
        $params["ContentType"] = "application/json"
    }
    $resp = Invoke-WebRequest @params -UseBasicParsing
    if ($resp.Content) {
        return ($resp.Content | ConvertFrom-Json)
    }
    return $null
}

function Get-DataField($obj) {
    # 兼容返回 { data: {...} } 或直接 {...} 的结构
    if ($null -eq $obj) { return $null }
    if ($obj.data -ne $null) { return $obj.data }
    return $obj
}

# 1. 按 Tag 查找 Release
Write-Host "Locating release for tag '$Tag' ..."
$release = $null
try {
    $releaseResp = Invoke-CnbApi "GET" "/$Repo/-/releases/tags/$([uri]::EscapeDataString($Tag))"
    $release = Get-DataField $releaseResp
} catch {
    Write-Warning "get-release-by-tag failed: $_"
}
if (-not $release) {
    Write-Warning "Release for tag '$Tag' not found; upload skipped."
    exit 0
}

$releaseId = $release.id
if (-not $releaseId) { $releaseId = $release.release_id }
if (-not $releaseId) {
    Write-Warning "Could not resolve release_id; upload skipped."
    exit 0
}
Write-Host "Found release id=$releaseId"

# 2. 请求上传地址
$uploadBody = @{
    asset_name = $AssetName
    size       = $fileSize
    overwrite  = $true
}
$uploadResp = Invoke-CnbApi "POST" "/$Repo/-/releases/$releaseId/asset-upload-url" $uploadBody
if (-not $uploadResp) { throw "Failed to get upload URL." }
$uploadData = Get-DataField $uploadResp

# 上传地址：优先 upload_url，其次 verify_url
$uploadUrl = $null
if ($uploadData.upload_url) { $uploadUrl = $uploadData.upload_url }
elseif ($uploadData.verify_url) { $uploadUrl = $uploadData.verify_url }
elseif ($uploadResp.upload_url) { $uploadUrl = $uploadResp.upload_url }
elseif ($uploadResp.verify_url) { $uploadUrl = $uploadResp.verify_url }
if (-not $uploadUrl) {
    Write-Warning "No upload_url/verify_url returned; upload skipped."
    exit 0
}

# 3. 流式上传
Write-Host "Uploading to: $uploadUrl"
$authHeader = @{ "Authorization" = "Bearer $Token" }
try {
    $up = Invoke-WebRequest -Uri $uploadUrl -Method "PUT" -Headers $authHeader `
        -InFile $File -ContentType "application/octet-stream" -UseBasicParsing
    Write-Host "Upload PUT status: $($up.StatusCode)"
} catch {
    Write-Warning "Upload PUT failed: $_"
    exit 0
}

# 4. 确认上传：从 verify_url 提取 upload_token / asset_path
$verifyUrl = $uploadData.verify_url
if (-not $verifyUrl) { $verifyUrl = $uploadResp.verify_url }

$uploadToken = $null
$assetPath = $null
if ($verifyUrl) {
    if ($verifyUrl -match "[?&]upload_token=([^&]+)") { $uploadToken = [uri]::UnescapeDataString($Matches[1]) }
    if ($verifyUrl -match "[?&]asset_path=([^&]+)") { $assetPath = [uri]::UnescapeDataString($Matches[1]) }
}
if (-not $uploadToken) { $uploadToken = $uploadData.upload_token }
if (-not $assetPath) { $assetPath = $uploadData.asset_path }

if ($uploadToken -and $assetPath) {
    try {
        Invoke-CnbApi "POST" "/$Repo/-/releases/$releaseId/asset-upload-confirmation/$([uri]::EscapeDataString($uploadToken))/$([uri]::EscapeDataString($assetPath))"
        Write-Host "Upload confirmed."
    } catch {
        Write-Warning "Upload confirmation failed: $_"
    }
} else {
    Write-Warning "Could not parse upload_token/asset_path; confirmation skipped."
}

Write-Host "Done. Asset '$AssetName' attached to release '$Tag'." -ForegroundColor Green
