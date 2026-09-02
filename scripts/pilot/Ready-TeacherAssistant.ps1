<#
.SYNOPSIS
    One-click bring-up for the Teacher Assistant pilot.

.DESCRIPTION
    Starts PostgreSQL, Redis, the API, the RQ worker and the frontend through
    the supported pilot scripts, then reports the safety-relevant configuration
    the operator needs to see before running anything.

    The local model is deliberately NOT started here. It is on-demand: the
    worker starts it when a job needs it and releases the single GPU slot
    afterwards. Starting it eagerly holds ~11 GiB of VRAM for nothing.

    Nothing in this script grades, approves, or exports. It only brings the
    host up and prints what state it is in.
#>

[CmdletBinding()]
param(
    [switch]$RebuildFrontend
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $repositoryRoot

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 64) -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 64) -ForegroundColor DarkCyan
}

function Clear-PreBootPidFiles {
    <#
        A PID file written before the current boot cannot describe a running
        managed process, because nothing survives a restart. After a reboot the
        operating system reissues those numbers, so a stale file eventually
        names an unrelated process and the pilot refuses to touch it -- correct,
        but it leaves a one-click start dead until someone deletes the file by
        hand. Comparing against boot time is exact: a file newer than boot
        belongs to a process this pilot really did start, and is never removed.
    #>
    param([string]$PidRoot)

    if (-not (Test-Path -LiteralPath $PidRoot)) { return }
    $bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    foreach ($file in Get-ChildItem -LiteralPath $PidRoot -Filter *.pid -File -ErrorAction SilentlyContinue) {
        if ($file.LastWriteTime -lt $bootTime) {
            Write-Host ("  clearing pre-boot PID file: {0}" -f $file.Name) -ForegroundColor DarkGray
            Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    Write-Section "Starting the Teacher Assistant host"
    Write-Host "Repository: $repositoryRoot" -ForegroundColor Gray
    Write-Host "This takes a minute on a cold boot." -ForegroundColor Gray

    Clear-PreBootPidFiles -PidRoot (Join-Path $repositoryRoot ".local-ai\pilot")

    $startArgs = @{}
    if ($RebuildFrontend) { $startArgs["RebuildFrontend"] = $true }
    & (Join-Path $PSScriptRoot "Start-TeacherPilot.ps1") @startArgs

    Write-Section "Service health"
    & (Join-Path $PSScriptRoot "Get-TeacherPilotStatus.ps1")

    Write-Section "Active configuration"
    $envFile = Join-Path $repositoryRoot ".env"
    $localAiFile = Join-Path $repositoryRoot ".env.local-ai"
    $settings = @{}
    foreach ($file in @($localAiFile, $envFile)) {
        if (Test-Path -LiteralPath $file) {
            foreach ($line in Get-Content -LiteralPath $file) {
                $trimmed = $line.Trim()
                if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
                $parts = $trimmed.Split("=", 2)
                $settings[$parts[0].Trim()] = $parts[1].Trim()
            }
        }
    }

    function Show-Setting {
        param([string]$Key, [string]$Expected, [string]$Label)
        $value = $settings[$Key]
        if (-not $value) { $value = "(unset)" }
        $ok = (-not $Expected) -or ($value -eq $Expected)
        $colour = if ($ok) { "Green" } else { "Yellow" }
        $mark = if ($ok) { "OK  " } else { "  ! " }
        Write-Host ("  {0}{1,-34} {2}" -f $mark, $Label, $value) -ForegroundColor $colour
    }

    Show-Setting -Key "BRAIN_PROVIDER" -Expected "llama_cpp_qwen38" -Label "Brain provider"
    Show-Setting -Key "LOCAL_QWEN38_MODEL" -Expected "" -Label "Model"
    Show-Setting -Key "LOCAL_QWEN38_PAGE_READ_ENABLED" -Expected "true" -Label "Page-read (one call per page)"
    Show-Setting -Key "LOCAL_QWEN38_TRANSCRIPTION_ENABLED" -Expected "true" -Label "Transcription"
    Show-Setting -Key "LOCAL_QWEN38_GRADING_ENABLED" -Expected "true" -Label "Grading"
    Show-Setting -Key "BULK_SUPERVISED_ENABLED" -Expected "true" -Label "Bulk supervised"
    Show-Setting -Key "BULK_MAX_SUBMISSIONS" -Expected "" -Label "Max scripts per run"
    Show-Setting -Key "BULK_MAX_PROVIDER_CALLS" -Expected "" -Label "Max model calls per run"

    Write-Host ""
    Show-Setting -Key "COHORT_MODEL_GRADING_ENABLED" -Expected "false" -Label "Cohort auto-grading (must be false)"

    Write-Section "Host stability"
    $os = Get-CimInstance Win32_OperatingSystem
    $uptime = New-TimeSpan -Start $os.LastBootUpTime -End (Get-Date)
    Write-Host ("  Booted {0}  (up {1:dd}d {1:hh}h {1:mm}m)" -f $os.LastBootUpTime, $uptime) -ForegroundColor Gray
    $crashes = @(Get-WinEvent -FilterHashtable @{LogName = "System"; Id = 1001; StartTime = (Get-Date).AddDays(-7) } -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -like "*bugcheck*" })
    if ($crashes.Count -eq 0) {
        Write-Host "  No bugchecks in the last 7 days." -ForegroundColor Green
    }
    else {
        $latest = ($crashes | Sort-Object TimeCreated -Descending | Select-Object -First 1).TimeCreated
        Write-Host ("  {0} bugcheck(s) in the last 7 days; most recent {1}." -f $crashes.Count, $latest) -ForegroundColor Yellow
        Write-Host "  A long unattended run on this host may not complete." -ForegroundColor Yellow
    }

    Write-Section "Ready"
    Write-Host "  Teacher Assistant : http://localhost:3000" -ForegroundColor White
    Write-Host "  API health        : http://localhost:8000/health" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  The local model starts on demand when a run needs it." -ForegroundColor Gray
    Write-Host "  Every score stays a draft until you approve it." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  To shut down:  scripts\pilot\Stop-TeacherPilot.ps1" -ForegroundColor DarkGray
}
catch {
    Write-Host ""
    Write-Host ("STARTUP FAILED: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host ""
    Write-Host "Common causes:" -ForegroundColor Yellow
    Write-Host "  - The host was not shut down cleanly; try running this again." -ForegroundColor Gray
    Write-Host "  - Another Postgres or Redis is already using 5432 / 6379." -ForegroundColor Gray
    Write-Host "  - A previous worker is still holding the queue name." -ForegroundColor Gray
    Write-Host ""
    Write-Host "Press Enter to close." -ForegroundColor DarkGray
    [void][System.Console]::ReadLine()
    exit 1
}

Write-Host ""
Write-Host "Press Enter to close this window (services keep running)." -ForegroundColor DarkGray
[void][System.Console]::ReadLine()
