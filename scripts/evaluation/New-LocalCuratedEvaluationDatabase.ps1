<#
.SYNOPSIS
Creates one empty, migration-current database for a local curated evaluation.

.DESCRIPTION
This operator-only helper is deliberately create-only. It refuses a name that
does not derive exactly from the supplied run ID, refuses to reuse an existing
database, and never drops or overwrites any database. It does not start a
model or enable grading.

Run it from the same PowerShell session used for the evaluation commands. On
success it sets DATABASE_URL only for that session and prints the database
name, never credentials.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]{3,48}$')]
    [string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\pilot\Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths

$databaseName = "teacher_assistant_eval_$RunId"
if ($databaseName -notmatch '^teacher_assistant_eval_[a-z0-9_]{3,48}$') {
    throw "Evaluation database name did not pass the safety guard."
}

$psql = Join-Path $paths.PostgresBin "psql.exe"
$postgresReady = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc "SELECT 1" 2>&1) -eq "1"
if (-not $postgresReady) {
    throw "Local PostgreSQL is not running. Start the teacher-pilot host services first."
}

$roleExists = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc `
    "SELECT 1 FROM pg_roles WHERE rolname='teacher_assistant'") -eq "1"
if (-not $roleExists) {
    throw "The local teacher_assistant PostgreSQL role is unavailable."
}

$exists = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc `
    "SELECT 1 FROM pg_database WHERE datname='$databaseName'") -eq "1"
if ($exists) {
    throw "Evaluation database already exists: $databaseName. Refusing to reuse or overwrite it."
}

& $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 `
    -c "CREATE DATABASE `"$databaseName`" OWNER teacher_assistant" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL did not create the evaluation database."
}

$baseDatabaseUrl = $env:DATABASE_URL
if ($baseDatabaseUrl -notmatch '/teacher_assistant$') {
    throw "Pilot DATABASE_URL did not name the expected base database."
}
$env:DATABASE_URL = $baseDatabaseUrl -replace '/teacher_assistant$', "/$databaseName"

Push-Location $paths.ApiDirectory
try {
    & $paths.ApiPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed. The newly created evaluation database was left intact."
    }
} finally {
    Pop-Location
}

Write-Host "Created empty evaluation database: $databaseName"
Write-Host "DATABASE_URL is set only in this PowerShell session. No model was started."
