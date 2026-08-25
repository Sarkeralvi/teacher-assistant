param(
    [string]$ConfigPath,
    [ValidateSet("PaddleOcr", "Qwen", "Qwen38")]
    [string]$Mode = "Qwen"
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$definition = Get-LocalAiServiceDefinition -Mode $Mode
$port = $definition.Port
$alias = $definition.Alias
$qwenBinary = Assert-RequiredEnvironmentValue -Name $definition.BinaryVariable
$qwenModel = Assert-RequiredEnvironmentValue -Name $definition.ModelVariable
$null = Assert-RequiredEnvironmentValue -Name $definition.KeyVariable

$requiredFiles = if ($Mode -eq "PaddleOcr") { @($qwenBinary) } else { @($qwenBinary, $qwenModel) }
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required local AI file is missing: $requiredFile"
    }
}

$qwen38LaunchConfig = $null
if ($Mode -eq "Qwen38") {
    $qwen38LaunchConfig = Get-Qwen38LaunchConfiguration
    if ($qwen38LaunchConfig.MtpModelPath) {
        $mtpFile = Get-Item -LiteralPath $qwen38LaunchConfig.MtpModelPath
        if ($mtpFile.Length -ne 1680271648) {
            throw "Qwen3.8 MTP byte size does not match the publisher-pinned Q4_0 file."
        }
        $mtpHeader = [byte[]]::new(4)
        $mtpStream = [IO.File]::OpenRead($qwen38LaunchConfig.MtpModelPath)
        try {
            [void]$mtpStream.Read($mtpHeader, 0, $mtpHeader.Length)
        } finally {
            $mtpStream.Dispose()
        }
        if ([Text.Encoding]::ASCII.GetString($mtpHeader) -ne 'GGUF') {
            throw "Qwen3.8 MTP file does not have GGUF magic bytes."
        }
        $actualMtpHash = (Get-FileHash `
            -LiteralPath $qwen38LaunchConfig.MtpModelPath `
            -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualMtpHash -ne $qwen38LaunchConfig.MtpSha256) {
            throw "Qwen3.8 MTP SHA256 does not match LOCAL_QWEN38_MTP_SHA256."
        }
    }
}

if ($Mode -eq "PaddleOcr") {
    $layoutModel = Assert-RequiredEnvironmentValue -Name $definition.LayoutModelVariable
    if (-not (Test-Path -LiteralPath $qwenModel -PathType Container)) {
        throw "Required PaddleOCR model directory is missing: $qwenModel"
    }
    if (-not (Test-Path -LiteralPath $layoutModel -PathType Container)) {
        throw "Required PaddleOCR layout model directory is missing: $layoutModel"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $qwenModel "model.safetensors") -PathType Leaf)) {
        throw "PaddleOCR-VL native model is incomplete (model.safetensors missing)."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $layoutModel "inference.pdiparams") -PathType Leaf)) {
        throw "PP-DocLayoutV3 native model is incomplete (inference.pdiparams missing)."
    }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $versionOutput = & $qwenBinary --version 2>&1 | ForEach-Object { $_.ToString() }
    $versionExitCode = $LASTEXITCODE
    if ($versionExitCode -eq 0) {
        $packageProbe = & $qwenBinary -c "import paddle, paddleocr, paddlex; assert paddle.__version__ == '3.2.1'; assert paddleocr.__version__ == '3.7.0'; print('paddle=' + paddle.__version__ + '; paddleocr=' + paddleocr.__version__ + '; paddlex=' + paddlex.__version__)" 2>&1 | ForEach-Object { $_.ToString() }
        $versionExitCode = $LASTEXITCODE
        if ($versionExitCode -eq 0) { $versionOutput += $packageProbe }
    }
    $ErrorActionPreference = $previousErrorActionPreference
} else {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $versionOutput = & $qwenBinary --version 2>&1 | ForEach-Object { $_.ToString() }
    $versionExitCode = $LASTEXITCODE
    if ($versionExitCode -eq 0 -and $Mode -eq "Qwen38" -and
        $qwen38LaunchConfig.SpecDraftTokens -gt 0) {
        $helpOutput = & $qwenBinary --help 2>&1 | ForEach-Object { $_.ToString() }
        $versionExitCode = $LASTEXITCODE
        if ($versionExitCode -eq 0 -and ($helpOutput -join "`n") -notmatch 'draft-mtp') {
            throw "The configured llama.cpp runtime does not support Qwen3.8 MTP draft decoding."
        }
    }
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($versionExitCode -ne 0) {
    throw "$Mode runtime version check failed."
}

# A separately launched Qwen coding bridge normally occupies 8080. It is not
# repository-owned and must never be killed by this workflow, but on this host
# it consumes enough RAM/VRAM that PaddleOCR, Qwen3.6, or Qwen3.8 can fail while
# loading (Windows error 1455) or destabilize PostgreSQL. Refuse before loading
# any second model and give the operator an actionable, non-destructive reason.
$codingBridgeListeners = @(Get-LocalAiListenerInfo -Port 8080)
foreach ($listener in $codingBridgeListeners) {
    $codingBridgeProcess = Get-CimInstance Win32_Process `
        -Filter "ProcessId=$($listener.ProcessId)" `
        -ErrorAction SilentlyContinue
    if ($null -ne $codingBridgeProcess -and `
        [IO.Path]::GetFileName($codingBridgeProcess.ExecutablePath) -ieq "llama-server.exe") {
        throw (
            "A separate Qwen coding server is running on port 8080. Pause that server before " +
            "teacher local-AI work. This project will not terminate an unmanaged process."
        )
    }
}

foreach ($port in @($port)) {
    $listeners = @(Get-LocalAiListenerInfo -Port $port)
    if ($listeners.Count -gt 0) {
        $binding = if (@($listeners | Where-Object { -not $_.IsLoopback }).Count -gt 0) {
            "an unsafe non-loopback binding"
        } else {
            "an existing loopback binding"
        }
        throw "Port $port already has $binding. Stop or identify that process before startup."
    }
}

Write-Host "Local AI preflight passed."
if ($Mode -eq "PaddleOcr") {
    $versionText = $versionOutput -join "`n"
    $pythonVersion = [regex]::Match($versionText, "Python\s+\d+\.\d+\.\d+").Value
    $packageVersions = [regex]::Match(
        $versionText,
        "paddle=\d+\.\d+\.\d+; paddleocr=\d+\.\d+\.\d+; paddlex=\d+\.\d+\.\d+"
    ).Value
    Write-Host "PaddleOCR Python: $pythonVersion"
    Write-Host "PaddleOCR packages: $packageVersions"
    Write-Host "PaddleOCR model alias: $alias"
} else {
    Write-Host "llama.cpp: $($versionOutput | Select-Object -First 1)"
    Write-Host "Qwen model alias: $alias"
    if ($Mode -eq "Qwen38") {
        Write-Host ("Qwen38 launch profile: gpu-layers=$($qwen38LaunchConfig.GpuLayers); " +
            "fit-target=$($qwen38LaunchConfig.FitTargetMib) MiB; " +
            "MTP draft tokens=$($qwen38LaunchConfig.SpecDraftTokens).")
    }
}
