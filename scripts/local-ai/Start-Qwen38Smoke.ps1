<#
.SYNOPSIS
    Retired unsafe Qwen3.8 smoke entry point.

.DESCRIPTION
    This file is deliberately retained only to stop an old operator command
    from sending raw ``/v1/chat/completions`` requests outside the application
    lease.  A local model request is valid only when the production provider
    has acquired the durable lease and its in-process guard.

    It starts no server, makes no network request, and changes no state.
    Start a managed phase with Switch-LocalAiPhase.ps1, then exercise the
    supervised production workflow or the curated-evaluation CLI documented
    in docs/LOCAL_CURATED_EVAL_RUNBOOK.md.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

throw (
    'Start-Qwen38Smoke.ps1 is retired because direct model calls bypass the ' +
    'mandatory local-model lease. Use Switch-LocalAiPhase.ps1 and a ' +
    'production supervised workflow instead.'
)
