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
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($versionExitCode -ne 0) {
    throw "$Mode runtime version check failed."
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
}
