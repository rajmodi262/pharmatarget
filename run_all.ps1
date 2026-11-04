<#
.SYNOPSIS
    PharmaTarget end-to-end runner (Windows wrapper).

.DESCRIPTION
    Thin wrapper over the cross-platform runner, src/run.py, which holds every
    stage, the staleness logic and the logging. Run it directly on any OS:

        python -m src.run [--only STAGE ...] [--force] [--skip-web] [--serve] [--list]

    The stage list used to live here. Windows paths inside PowerShell strings
    were corrupted into control characters three times ("\v", "\f", "\t"), each
    silently breaking a staleness check, so the logic moved to Python.

.EXAMPLE
    .\run_all.ps1
    .\run_all.ps1 -Only sizing,territory
    .\run_all.ps1 -Force -Serve
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string[]]$Only,
    [switch]$SkipWeb,
    [switch]$Serve,
    [switch]$List
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$runArgs = @()
if ($Force)   { $runArgs += "--force" }
if ($Only)    { $runArgs += "--only"; $runArgs += ($Only -join ",").Split(",") }
if ($SkipWeb) { $runArgs += "--skip-web" }
if ($Serve)   { $runArgs += "--serve" }
if ($List)    { $runArgs += "--list" }

& python -m src.run @runArgs
exit $LASTEXITCODE
