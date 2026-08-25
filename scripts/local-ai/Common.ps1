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

function Get-Qwen38LaunchConfiguration {
    <#
    .SYNOPSIS
        Parse and validate the host-specific Qwen3.8 performance settings.

    .DESCRIPTION
        The publisher-pinned model, projector, context, loopback binding and
        single-slot safety contract are not configurable here. These settings
        only control CPU/GPU placement and the optional publisher MTP draft
        head. Defaults preserve the measured build-10249 launch profile.
    #>

    $gpuLayers = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_GPU_LAYERS")
    if ([string]::IsNullOrWhiteSpace($gpuLayers)) { $gpuLayers = "34" }
    $gpuLayers = $gpuLayers.Trim().ToLowerInvariant()
    if ($gpuLayers -ne "auto") {
        $parsedGpuLayers = 0
        if (-not [int]::TryParse($gpuLayers, [ref]$parsedGpuLayers) -or
            $parsedGpuLayers -lt 1 -or $parsedGpuLayers -gt 65) {
            throw "LOCAL_QWEN38_GPU_LAYERS must be 'auto' or an integer between 1 and 65."
        }
        $gpuLayers = [string]$parsedGpuLayers
    }

    $fitTargetRaw = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_FIT_TARGET_MIB")
    $fitTargetExplicit = -not [string]::IsNullOrWhiteSpace($fitTargetRaw)
    if (-not $fitTargetExplicit) { $fitTargetRaw = "1024" }
    $fitTargetMib = 0
    if (-not [int]::TryParse($fitTargetRaw, [ref]$fitTargetMib) -or
        $fitTargetMib -lt 768 -or $fitTargetMib -gt 4096) {
        throw "LOCAL_QWEN38_FIT_TARGET_MIB must be between 768 and 4096."
    }
    if ($gpuLayers -ne "auto" -and $fitTargetExplicit) {
        throw "LOCAL_QWEN38_FIT_TARGET_MIB is only valid when LOCAL_QWEN38_GPU_LAYERS=auto."
    }

    $specDraftRaw = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_SPEC_DRAFT_TOKENS")
    if ([string]::IsNullOrWhiteSpace($specDraftRaw)) { $specDraftRaw = "0" }
    $specDraftTokens = 0
    if (-not [int]::TryParse($specDraftRaw, [ref]$specDraftTokens) -or
        $specDraftTokens -notin @(0, 2, 3)) {
        throw "LOCAL_QWEN38_SPEC_DRAFT_TOKENS must be 0, 2, or 3."
    }

    $mtpModelPath = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_MTP_MODEL_PATH")
    $mtpSha256 = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_MTP_SHA256")
    $hasMtpPath = -not [string]::IsNullOrWhiteSpace($mtpModelPath)
    $hasMtpHash = -not [string]::IsNullOrWhiteSpace($mtpSha256)
    if ($hasMtpPath -xor $hasMtpHash) {
        throw "LOCAL_QWEN38_MTP_MODEL_PATH and LOCAL_QWEN38_MTP_SHA256 must be configured together."
    }
    if ($hasMtpPath) {
        $mtpModelPath = $mtpModelPath.Trim()
        $mtpSha256 = $mtpSha256.Trim().ToLowerInvariant()
        if (-not (Test-Path -LiteralPath $mtpModelPath -PathType Leaf)) {
            throw "Qwen3.8 MTP model file is missing: $mtpModelPath"
        }
        if ($mtpSha256 -notmatch '^[0-9a-f]{64}$') {
            throw "LOCAL_QWEN38_MTP_SHA256 must be a 64-character hexadecimal SHA-256."
        }
        $publisherMtpSha256 = '051a1764cff8c4f3ee6ae8b00593a0364c7539c67fa50ffc58f3f96509fca38e'
        if ($mtpSha256 -ne $publisherMtpSha256) {
            throw "LOCAL_QWEN38_MTP_SHA256 must match the publisher-pinned Qwen3.8 MTP Q4_0 SHA-256."
        }
    }
    if ($specDraftTokens -gt 0) {
        if (-not $hasMtpPath) {
            throw "Qwen3.8 MTP is enabled but its model path and SHA-256 are not configured."
        }
        if ($gpuLayers -ne "auto") {
            throw "Qwen3.8 MTP requires LOCAL_QWEN38_GPU_LAYERS=auto so llama.cpp can fit both models safely."
        }
    }

    function Get-BoundedIntegerSetting {
        param(
            [Parameter(Mandatory = $true)][string]$Name,
            [Parameter(Mandatory = $true)][int]$Default,
            [Parameter(Mandatory = $true)][int]$Minimum,
            [Parameter(Mandatory = $true)][int]$Maximum
        )
        $raw = [Environment]::GetEnvironmentVariable($Name)
        if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
        $parsed = 0
        if (-not [int]::TryParse($raw, [ref]$parsed) -or
            $parsed -lt $Minimum -or $parsed -gt $Maximum) {
            throw "$Name must be between $Minimum and $Maximum."
        }
        return $parsed
    }

    $threads = Get-BoundedIntegerSetting -Name "LOCAL_QWEN38_THREADS" -Default 12 -Minimum 1 -Maximum 256
    $threadsBatch = Get-BoundedIntegerSetting -Name "LOCAL_QWEN38_THREADS_BATCH" -Default $threads -Minimum 1 -Maximum 256
    $batchSize = Get-BoundedIntegerSetting -Name "LOCAL_QWEN38_BATCH_SIZE" -Default 256 -Minimum 32 -Maximum 2048
    $ubatchSize = Get-BoundedIntegerSetting -Name "LOCAL_QWEN38_UBATCH_SIZE" -Default 256 -Minimum 32 -Maximum 2048
    if ($ubatchSize -gt $batchSize) {
        throw "LOCAL_QWEN38_UBATCH_SIZE cannot exceed LOCAL_QWEN38_BATCH_SIZE."
    }

    $cpuMask = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_CPU_MASK")
    $cpuMaskBatch = [Environment]::GetEnvironmentVariable("LOCAL_QWEN38_CPU_MASK_BATCH")
    foreach ($maskSetting in @(
        @{ Name = "LOCAL_QWEN38_CPU_MASK"; Value = $cpuMask },
        @{ Name = "LOCAL_QWEN38_CPU_MASK_BATCH"; Value = $cpuMaskBatch }
    )) {
        if (-not [string]::IsNullOrWhiteSpace($maskSetting.Value) -and
            $maskSetting.Value.Trim() -notmatch '^(?:0x)?[0-9a-fA-F]+(?:,(?:0x)?[0-9a-fA-F]+)*$') {
            throw "$($maskSetting.Name) must be a hexadecimal CPU mask."
        }
    }

    return [pscustomobject]@{
        GpuLayers = $gpuLayers
        FitTargetMib = $fitTargetMib
        MtpModelPath = if ($hasMtpPath) { $mtpModelPath } else { $null }
        MtpSha256 = if ($hasMtpHash) { $mtpSha256 } else { $null }
        SpecDraftTokens = $specDraftTokens
        Threads = $threads
        ThreadsBatch = $threadsBatch
        BatchSize = $batchSize
        UbatchSize = $ubatchSize
        CpuMask = if ([string]::IsNullOrWhiteSpace($cpuMask)) { $null } else { $cpuMask.Trim() }
        CpuMaskBatch = if ([string]::IsNullOrWhiteSpace($cpuMaskBatch)) { $null } else { $cpuMaskBatch.Trim() }
    }
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

function Test-PaddleOcrManagedProcess {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$ExpectedLauncher
    )

    $modulePattern = '(?i)(?:^|\s)-m\s+packages\.local_ocr_sidecar\.server(?:\s|$)'
    if ([string]::IsNullOrWhiteSpace([string]$Process.CommandLine) -or
        [string]$Process.CommandLine -notmatch $modulePattern) {
        return $false
    }

    # Windows venv launchers normally remain as a small parent process while
    # the base Python interpreter owns the listening socket. Accept either
    # shape, but only when the exact venv launcher is the process itself or its
    # immediate parent and the command line names this repository's sidecar.
    if (Test-LocalAiExecutablePath `
        -ActualPath ([string]$Process.ExecutablePath) `
        -ExpectedPath $ExpectedLauncher) {
        return $true
    }
    $parent = Get-CimInstance Win32_Process `
        -Filter "ProcessId=$([int]$Process.ParentProcessId)" `
        -ErrorAction SilentlyContinue
    return (
        $null -ne $parent -and
        (Test-LocalAiExecutablePath `
            -ActualPath ([string]$parent.ExecutablePath) `
            -ExpectedPath $ExpectedLauncher)
    )
}

function Assert-PaddleOcrListenerOwnership {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedLauncher,
        [Parameter(Mandatory = $true)][int]$ExpectedProcessId
    )

    $listeners = @(Get-LocalAiListenerInfo -Port $Port)
    if ($listeners.Count -eq 0) {
        throw "PaddleOCR did not create a listener on port $Port."
    }
    foreach ($listener in $listeners) {
        if (-not $listener.IsLoopback) {
            throw "PaddleOCR on port $Port is not loopback-only."
        }
        if ($listener.ProcessId -ne $ExpectedProcessId) {
            throw "PaddleOCR listener on port $Port is not owned by the recorded service process."
        }
        $process = Get-CimInstance Win32_Process `
            -Filter "ProcessId=$($listener.ProcessId)" `
            -ErrorAction SilentlyContinue
        if ($null -eq $process -or -not (Test-PaddleOcrManagedProcess `
            -Process $process `
            -ExpectedLauncher $ExpectedLauncher)) {
            throw "PaddleOCR listener on port $Port belongs to an unexpected process."
        }
    }
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
    param([Parameter(Mandatory = $true)][ValidateSet("PaddleOcr", "Qwen", "Qwen38")][string]$Mode)

    if ($Mode -eq "PaddleOcr") {
        $baseUrlName = "LOCAL_PADDLE_OCR_BASE_URL"
        $defaultPort = 8090
        $definition = @{
            Name = "PaddleOcr"
            Alias = "PaddleOCR-VL-1.6"
            PidFileName = "paddleocr.pid"
            BinaryVariable = "LOCAL_PADDLE_OCR_PYTHON_PATH"
            ModelVariable = "LOCAL_PADDLE_OCR_VL_MODEL_PATH"
            LayoutModelVariable = "LOCAL_PADDLE_OCR_LAYOUT_MODEL_PATH"
            KeyVariable = "LOCAL_PADDLE_OCR_API_KEY"
        }
    } elseif ($Mode -eq "Qwen") {
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
