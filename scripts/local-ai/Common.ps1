Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-LocalAiEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Local AI configuration was not found at $Path. Run Initialize-LocalAiConfig.ps1 first."
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2 -or -not $parts[0].Trim()) {
            throw "Invalid local AI configuration line."
        }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        Set-Item -LiteralPath "Env:$name" -Value $value
    }
}

function Assert-RequiredEnvironmentValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Name is required in the local AI configuration."
    }
    return $value
}

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Test-LocalAiLoopbackAddress {
    param([Parameter(Mandatory = $true)][string]$Address)

    $parsedAddress = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsedAddress)) {
        return $false
    }
    return [Net.IPAddress]::IsLoopback($parsedAddress)
}

function Get-LocalAiListenerInfo {
    param([Parameter(Mandatory = $true)][int]$Port)

    $seenProcessIds = @{}
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $processId = [int]$listener.OwningProcess
        $key = "$processId|$($listener.LocalAddress)"
        if ($seenProcessIds.ContainsKey($key)) {
            continue
        }
        $seenProcessIds[$key] = $true
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        [pscustomobject]@{
            Address = [string]$listener.LocalAddress
            Port = $Port
            ProcessId = $processId
            ExecutablePath = if ($null -ne $process) { [string]$process.ExecutablePath } else { $null }
            CommandLine = if ($null -ne $process) { [string]$process.CommandLine } else { $null }
            IsLoopback = Test-LocalAiLoopbackAddress -Address ([string]$listener.LocalAddress)
        }
    }
}

function Test-LocalAiExecutablePath {
    param(
        [AllowNull()][string]$ActualPath,
        [Parameter(Mandatory = $true)][string]$ExpectedPath
    )

    if ([string]::IsNullOrWhiteSpace($ActualPath)) {
        return $false
    }
    $resolvedExpectedPath = (Resolve-Path -LiteralPath $ExpectedPath).Path
    $resolvedActualPath = [IO.Path]::GetFullPath($ActualPath)
    return [string]::Equals(
        $resolvedActualPath,
        $resolvedExpectedPath,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-LocalAiListenerOwnership {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [int]$ExpectedProcessId = 0
    )

    $listeners = @(Get-LocalAiListenerInfo -Port $Port)
    if ($listeners.Count -eq 0) {
        throw "Local AI service did not create a listener on port $Port."
    }
    foreach ($listener in $listeners) {
        if (-not $listener.IsLoopback) {
            throw "Local AI service on port $Port is not loopback-only."
        }
        if (-not (Test-LocalAiExecutablePath `
            -ActualPath $listener.ExecutablePath `
            -ExpectedPath $ExpectedExecutable)) {
            throw "Local AI listener on port $Port belongs to an unexpected executable."
        }
        if ($ExpectedProcessId -gt 0 -and $listener.ProcessId -ne $ExpectedProcessId) {
            throw "Local AI listener on port $Port is not owned by the started process."
        }
    }
}
