param([string]$ConfigPath)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$runtimeDirectory = Join-Path $repositoryRoot ".local-ai"
$services = @(
    @{
        Name = "Qwen"
        PidPath = Join-Path $runtimeDirectory "qwen.pid"
        ExpectedExecutable = (Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_BINARY_PATH")
    },
    @{
        Name = "PaddleOCR"
        PidPath = Join-Path $runtimeDirectory "ocr.pid"
        ExpectedExecutable = (Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_PYTHON_PATH")
    }
)

foreach ($service in $services) {
    if (-not (Test-Path -LiteralPath $service.PidPath -PathType Leaf)) {
        Write-Host "$($service.Name) PID file is absent; nothing to stop."
        continue
    }
    $processId = 0
    $rawProcessId = (Get-Content -LiteralPath $service.PidPath -Raw).Trim()
    if (-not [int]::TryParse($rawProcessId, [ref]$processId) -or $processId -le 0) {
        throw "$($service.Name) PID file is invalid; refusing to stop a process."
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $service.PidPath -Force
        Write-Host "$($service.Name) is already stopped."
        continue
    }
    $expectedPath = (Resolve-Path -LiteralPath $service.ExpectedExecutable).Path
    if (-not [string]::Equals($process.Path, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$($service.Name) PID now belongs to a different executable; refusing to stop it."
    }
    Stop-Process -Id $processId -Force
    Remove-Item -LiteralPath $service.PidPath -Force
    Write-Host "$($service.Name) stopped."
}
