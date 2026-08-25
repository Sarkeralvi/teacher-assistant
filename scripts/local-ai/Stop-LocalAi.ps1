param(
    [string]$ConfigPath,
    [ValidateSet("PaddleOcr", "Qwen", "Qwen38")]
    [string]$Mode = "Qwen",
    # Off by default: without it this script only stops the process whose PID
    # this repository recorded. The port sweep it enables will kill ANY matching
    # llama-server on the port, including a separate coding-assistant bridge
    # that this repository did not start. Killing a process we did not launch
    # must be a deliberate, typed decision.
    [switch]$ForcePortSweep
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$runtimeDirectory = Join-Path $repositoryRoot ".local-ai"
$definition = Get-LocalAiServiceDefinition -Mode $Mode
$apiKeyFile = Join-Path $runtimeDirectory "$($Mode.ToLower()).api-key"
$paddleEnvironmentFile = Join-Path $runtimeDirectory "paddleocr.runtime.env"
$services = @(
    @{
        Name = $definition.Name
        Mode = $Mode
        PidPath = Join-Path $runtimeDirectory $definition.PidFileName
        ExpectedExecutable = (Assert-RequiredEnvironmentValue -Name $definition.BinaryVariable)
        Port = $definition.Port
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
            $managedProcess = if ($service.Mode -eq "PaddleOcr") {
                Test-PaddleOcrManagedProcess -Process $process -ExpectedLauncher $service.ExpectedExecutable
            } else {
                Test-LocalAiExecutablePath `
                    -ActualPath $process.ExecutablePath `
                    -ExpectedPath $service.ExpectedExecutable
            }
            if (-not $managedProcess) {
                throw "$($service.Name) PID now belongs to a different executable; refusing to stop it."
            }
            Stop-Process -Id $processId -Force
            $null = $stoppedProcessIds.Add($processId)
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
        Remove-Item -LiteralPath $service.PidPath -Force -ErrorAction SilentlyContinue
    }

    if ($ForcePortSweep) {
        foreach ($listener in @(Get-LocalAiListenerInfo -Port $service.Port)) {
            $listenerProcess = Get-CimInstance Win32_Process `
                -Filter "ProcessId=$($listener.ProcessId)" `
                -ErrorAction SilentlyContinue
            $managedListener = if ($service.Mode -eq "PaddleOcr") {
                $null -ne $listenerProcess -and (Test-PaddleOcrManagedProcess `
                    -Process $listenerProcess `
                    -ExpectedLauncher $service.ExpectedExecutable)
            } else {
                Test-LocalAiExecutablePath `
                    -ActualPath $listener.ExecutablePath `
                    -ExpectedPath $service.ExpectedExecutable
            }
            if (-not $managedListener) {
                throw "$($service.Name) port belongs to an unexpected executable; refusing to stop it."
            }
            Stop-Process -Id $listener.ProcessId -Force
            $null = $stoppedProcessIds.Add([int]$listener.ProcessId)
        }
    }
    foreach ($stoppedProcessId in $stoppedProcessIds) {
        Wait-Process -Id $stoppedProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
    $remaining = @(Get-LocalAiListenerInfo -Port $service.Port)
    if ($remaining.Count -gt 0) {
        if (-not $ForcePortSweep) {
            # Do not kill it. It may be a bridge this repository never started.
            throw ("$($service.Name) port $($service.Port) is still held by PID " +
                "$($remaining[0].ProcessId), which this repository did not start. " +
                "Stop it yourself, or re-run with -ForcePortSweep to kill any " +
                "matching llama-server on that port.")
        }
        throw "$($service.Name) listener on port $($service.Port) did not stop."
    }
    if ($stoppedProcessIds.Count -gt 0) {
        Write-Host "$($service.Name) stopped."
    } else {
        Write-Host "$($service.Name) is already stopped."
    }
    Remove-Item -LiteralPath $apiKeyFile -Force -ErrorAction SilentlyContinue
    if ($service.Mode -eq "PaddleOcr") {
        Remove-Item -LiteralPath $paddleEnvironmentFile -Force -ErrorAction SilentlyContinue
    }
}
