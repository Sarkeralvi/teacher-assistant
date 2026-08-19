param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Qwen", "Qwen38")]
    [string]$Phase,
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 600
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$otherPhase = if ($Phase -eq "Qwen") { "Qwen38" } else { "Qwen" }

# Stop the other phase if running to prevent VRAM or port conflicts
$stopOtherArgs = @{
    Mode = $otherPhase
    ConfigPath = $ConfigPath
}
& (Join-Path $PSScriptRoot "Stop-LocalAi.ps1") @stopOtherArgs

$targetPort = if ($Phase -eq "Qwen") { 8080 } else { 8085 }
$targetAlias = if ($Phase -eq "Qwen") { "qwen3.6-35b-a3b-q4km" } else { "qwen3.8-27b-q4km" }
$targetKey = if ($Phase -eq "Qwen") { $env:LOCAL_QWEN_API_KEY } else { $env:LOCAL_QWEN38_API_KEY }

# If target phase is already healthy on loopback, return immediately
$alreadyHealthy = $false
try {
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:$targetPort/v1/models" -Headers @{ Authorization = "Bearer $targetKey" } -TimeoutSec 3
    if (@($models.data.id) -contains $targetAlias) {
        $alreadyHealthy = $true
    }
} catch {
    $alreadyHealthy = $false
}

if ($alreadyHealthy) {
    Write-Host "$Phase is already healthy on loopback (Port $targetPort)."
    exit 0
}

$startArguments = @{
    Mode = $Phase
    HealthTimeoutSeconds = $HealthTimeoutSeconds
    ConfigPath = $ConfigPath
}
& (Join-Path $PSScriptRoot "Start-LocalAi.ps1") @startArguments

