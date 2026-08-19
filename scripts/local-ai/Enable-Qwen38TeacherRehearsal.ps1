param(
    [string]$ConfigPath,
    [ValidateSet("Enable", "Disable")]
    [string]$Mode = "Enable"
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $repositoryRoot ".env.local-ai" }
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Local configuration was not found: $ConfigPath"
}

$enabled = if ($Mode -eq "Enable") { "true" } else { "false" }
$updates = [ordered]@{
    "LOCAL_QWEN38_ENABLED" = "true"
    "LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED" = $enabled
    "LOCAL_QWEN38_GRADING_ENABLED" = $enabled
    "LOCAL_REFERENCE_EXTRACTION_ENABLED" = $enabled
    "LOCAL_SCRIPT_PREPARATION_ENABLED" = $enabled
    "LOCAL_SINGLE_ANSWER_GRADING_ENABLED" = $enabled
    "COHORT_MODEL_GRADING_ENABLED" = "false"
    "COHORT_PROVIDER_RETRY_COUNT" = "0"
}

$lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $ConfigPath)
foreach ($name in $updates.Keys) {
    $replacement = "$name=$($updates[$name])"
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ("^" + [regex]::Escape($name) + "=")) { $index = $i; break }
    }
    if ($index -ge 0) { $lines[$index] = $replacement } else { $lines.Add($replacement) }
}
[IO.File]::WriteAllLines($ConfigPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Qwen3.8 teacher-rehearsal permissions are $($Mode.ToLowerInvariant())d."
Write-Host "Cohort model grading remains disabled. Start the model explicitly with Start-LocalAi.ps1 -Mode Qwen38."
