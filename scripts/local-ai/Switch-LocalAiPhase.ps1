param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Concurrent", "OcrGpu", "OcrCpu", "Qwen")]
    [string]$Phase,
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 600
)

$stopArguments = @{}
$startArguments = @{
    Mode = $Phase
    HealthTimeoutSeconds = $HealthTimeoutSeconds
}
if ($ConfigPath) {
    $stopArguments.ConfigPath = $ConfigPath
    $startArguments.ConfigPath = $ConfigPath
}

& (Join-Path $PSScriptRoot "Stop-LocalAi.ps1") @stopArguments
& (Join-Path $PSScriptRoot "Start-LocalAi.ps1") @startArguments
