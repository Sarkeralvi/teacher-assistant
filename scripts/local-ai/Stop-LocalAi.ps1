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
        Port = 8080
    },
    @{
        Name = "PaddleOCR"
        PidPath = Join-Path $runtimeDirectory "ocr.pid"
        ExpectedExecutable = (Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_PYTHON_PATH")
        Port = 8090
    }
)

foreach ($service in $services) {
    $stoppedProcessIds = [Collections.Generic.HashSet[int]]::new()
    if (Test-Path -LiteralPath $service.PidPath -PathType Leaf) {
        $processId = 0
        $rawProcessId = (Get-Content -LiteralPath $service.PidPath -Raw).Trim()
        if (-not [int]::TryParse($rawProcessId, [ref]$processId) -or $processId -le 0) {
            throw "$($service.Name) PID file is invalid; refusing to stop a process."
        }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            if (-not (Test-LocalAiExecutablePath `
                -ActualPath $process.ExecutablePath `
                -ExpectedPath $service.ExpectedExecutable)) {
                throw "$($service.Name) PID now belongs to a different executable; refusing to stop it."
            }
            Stop-Process -Id $processId -Force
            $null = $stoppedProcessIds.Add($processId)
            # Wait before the missing-PID recovery scan. Windows can retain a
            # listener row briefly after the process path has disappeared;
            # treating that transient row as a foreign executable would turn
            # a successful managed stop into a false safety failure.
            Wait-Process -Id $processId -Timeout 15 -ErrorAction SilentlyContinue
            $portReleaseDeadline = [DateTime]::UtcNow.AddSeconds(5)
            while (
                [DateTime]::UtcNow -lt $portReleaseDeadline -and
                @(
                    Get-LocalAiListenerInfo -Port $service.Port |
                        Where-Object { $_.ProcessId -eq $processId }
                ).Count -gt 0
            ) {
                Start-Sleep -Milliseconds 100
            }
        }
        Remove-Item -LiteralPath $service.PidPath -Force
    }

    # Recover safely from a missing/stale PID record, but only for the exact
    # configured executable listening on this service's dedicated port.
    foreach ($listener in @(Get-LocalAiListenerInfo -Port $service.Port)) {
        if (-not (Test-LocalAiExecutablePath `
            -ActualPath $listener.ExecutablePath `
            -ExpectedPath $service.ExpectedExecutable)) {
            throw "$($service.Name) port belongs to an unexpected executable; refusing to stop it."
        }
        Stop-Process -Id $listener.ProcessId -Force
        $null = $stoppedProcessIds.Add([int]$listener.ProcessId)
    }
    foreach ($stoppedProcessId in $stoppedProcessIds) {
        Wait-Process -Id $stoppedProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
    if (@(Get-LocalAiListenerInfo -Port $service.Port).Count -gt 0) {
        throw "$($service.Name) listener on port $($service.Port) did not stop."
    }
    if ($stoppedProcessIds.Count -gt 0) {
        Write-Host "$($service.Name) stopped."
    } else {
        Write-Host "$($service.Name) is already stopped."
    }
}
