<#
.SYNOPSIS
    Retired unsafe Qwen3.8 visual-smoke entry point.

.DESCRIPTION
    This file is deliberately retained only to stop an old operator command
    from transmitting image data directly to llama.cpp without a database
    model lease.  Visual preparation must use Qwen38VisualTranscriptionService
    through the supervised workflow, where mapping, ownership, hashes,
    confirmation gates, and the provider lease are all enforced.

    It makes no model or network request and does not write an artifact.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

throw (
    'Test-Qwen38VisionSmoke.ps1 is retired because direct image calls bypass ' +
    'the mandatory local-model lease. Use the supervised visual-preparation ' +
    'workflow or the curated evaluation instead.'
)
