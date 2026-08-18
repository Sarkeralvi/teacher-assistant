param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Qwen", "Qwen38")]
    [string]$Phase,
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 600
)

$stopArguments = @{ Mode = $Phase }
$startArguments = @{ Mode = $Phase;
    HealthTimeoutSeconds = $HealthTimeoutSeconds
}
if ($ConfigPath) {
    $stopArguments.ConfigPath = $ConfigPath
    $startArguments.ConfigPath = $ConfigPath
}

& (Join-Path $PSScriptRoot "Stop-LocalAi.ps1") @stopArguments
& (Join-Path $PSScriptRoot "Start-LocalAi.ps1") @startArguments
