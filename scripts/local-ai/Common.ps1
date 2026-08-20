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

function Get-LocalAiServiceDefinition {
    <#
    .SYNOPSIS
        Resolve one local model phase's port, alias, PID file and binary.

    .DESCRIPTION
        The port is parsed from the phase's *_BASE_URL rather than kept as a
        separate setting, so the operator scripts and the backend cannot drift
        onto different ports and fight over one listener.

        Qwen3.6 deliberately does NOT default to 8080. A separate Qwen3.6
        coding-assistant bridge commonly runs there with the same
        llama-server.exe, and Stop-LocalAi's port sweep would match its
        executable and force-kill it.
    #>
    param([Parameter(Mandatory = $true)][ValidateSet("Qwen", "Qwen38")][string]$Mode)

    if ($Mode -eq "Qwen") {
        $baseUrlName = "LOCAL_QWEN_BASE_URL"
        $defaultPort = 8086
        $definition = @{
            Name = "Qwen"
            Alias = "qwen3.6-35b-a3b-q4km"
            PidFileName = "qwen.pid"
            BinaryVariable = "LOCAL_QWEN_BINARY_PATH"
            ModelVariable = "LOCAL_QWEN_MODEL_PATH"
            KeyVariable = "LOCAL_QWEN_API_KEY"
        }
    } else {
        $baseUrlName = "LOCAL_QWEN38_BASE_URL"
        $defaultPort = 8085
        $definition = @{
            Name = "Qwen38"
            Alias = "qwen3.8-27b-q4km"
            PidFileName = "qwen38.pid"
            BinaryVariable = "LOCAL_QWEN38_BINARY_PATH"
            ModelVariable = "LOCAL_QWEN38_MODEL_PATH"
            KeyVariable = "LOCAL_QWEN38_API_KEY"
        }
    }

    $port = $defaultPort
    $baseUrl = [Environment]::GetEnvironmentVariable($baseUrlName)
    if (-not [string]::IsNullOrWhiteSpace($baseUrl)) {
        $parsed = $null
        if (-not [Uri]::TryCreate($baseUrl, [UriKind]::Absolute, [ref]$parsed)) {
            throw "$baseUrlName is not a valid absolute URL."
        }
        if (-not (Test-LocalAiLoopbackAddress -Address $parsed.Host)) {
            throw "$baseUrlName must point at a loopback address; got '$($parsed.Host)'."
        }
        if ($parsed.IsDefaultPort) {
            throw "$baseUrlName must name an explicit port."
        }
        $port = [int]$parsed.Port
    }
    $definition["Port"] = $port
    return [pscustomobject]$definition
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
