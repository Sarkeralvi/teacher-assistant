<#
.SYNOPSIS
    Download and verify the publisher Qwen3.8-27B Q4_0 MTP draft head.

.DESCRIPTION
    The main Q4_K_M model and vision projector are not modified. The verified
    draft head is stored beside them and an ignored local manifest records the
    source, byte size and SHA-256. Speculative decoding remains disabled until
    LOCAL_QWEN38_SPEC_DRAFT_TOKENS is explicitly set to 2 or 3.
#>

param(
    [string]$TargetDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($TargetDirectory)) {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    Import-LocalAiEnvironment -Path (Join-Path $repositoryRoot '.env.local-ai')
    $mainModelPath = Assert-RequiredEnvironmentValue -Name 'LOCAL_QWEN38_MODEL_PATH'
    $TargetDirectory = Split-Path -Parent $mainModelPath
}

$sourceUrl = 'https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/main/mtp-Qwen3.8-27B-Q4_0.gguf'
$expectedBytes = 1680271648
$expectedSha256 = '051a1764cff8c4f3ee6ae8b00593a0364c7539c67fa50ffc58f3f96509fca38e'
$targetFile = Join-Path $TargetDirectory 'mtp-Qwen3.8-27B-Q4_0.gguf'
$manifestDirectory = Join-Path $repositoryRoot '.local-ai\runtime'
$manifestPath = Join-Path $manifestDirectory 'qwen38-mtp-manifest.json'

New-Item -ItemType Directory -Path $TargetDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null

if (-not (Test-Path -LiteralPath $targetFile -PathType Leaf) -or
    (Get-Item -LiteralPath $targetFile).Length -ne $expectedBytes) {
    Write-Host 'Downloading the official Qwen3.8 MTP Q4_0 draft head...'
    curl.exe -L -C - -o $targetFile $sourceUrl
    if ($LASTEXITCODE -ne 0) { throw "MTP download failed with exit code $LASTEXITCODE." }
}

$actualBytes = (Get-Item -LiteralPath $targetFile).Length
if ($actualBytes -ne $expectedBytes) {
    throw "MTP size mismatch: expected $expectedBytes bytes, got $actualBytes."
}

$header = [byte[]]::new(4)
$stream = [IO.File]::OpenRead($targetFile)
try { [void]$stream.Read($header, 0, 4) } finally { $stream.Dispose() }
if ([Text.Encoding]::ASCII.GetString($header) -ne 'GGUF') {
    throw 'MTP file does not have GGUF magic bytes.'
}

$actualSha256 = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $expectedSha256) {
    throw "MTP SHA-256 mismatch: expected $expectedSha256, got $actualSha256."
}

$manifest = [ordered]@{
    schema_version = 1
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    source_url = $sourceUrl
    target_path = $targetFile
    byte_size = $actualBytes
    sha256 = $actualSha256
    gguf_magic_ok = $true
    speculative_decoding_enabled = $false
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host 'Qwen3.8 MTP draft head verified.' -ForegroundColor Green
Write-Host "File: $targetFile"
Write-Host "Manifest: $manifestPath"
