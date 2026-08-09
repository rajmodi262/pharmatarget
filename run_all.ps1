<#
.SYNOPSIS
    PharmaTarget end-to-end runner. Resumable, dependency-aware, logged.

.DESCRIPTION
    Runs every remaining pipeline stage, builds the frontend, runs the tests and
    prints a summary of the findings.

    RESUMABLE BY DESIGN. Each stage declares the artifact it produces. A stage is
    skipped when that artifact exists AND is newer than the source module that
    writes it. So:

      * interrupting the script loses only the stage in flight
      * editing src/models/sizing.py re-runs sizing and nothing else
      * re-running after a completed pass is a no-op that takes seconds

    Everything is appended to data/run.log with timestamps, so a stage that fails
    while nobody is watching can still be diagnosed afterwards.

.PARAMETER Force
    Re-run every stage regardless of existing artifacts.

.PARAMETER Only
    Run just the named stages, comma-separated.
    e.g. -Only sizing,territory

.PARAMETER SkipWeb
    Skip the frontend build (useful if Node is unavailable).

.PARAMETER Serve
    Start the API on :8000 when the pipeline finishes.

.EXAMPLE
    .\run_all.ps1
    .\run_all.ps1 -Only sizing,territory,segmentation,response
    .\run_all.ps1 -Force -Serve
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string[]]$Only,
    [switch]$SkipWeb,
    [switch]$Serve
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$LogFile  = Join-Path $PSScriptRoot "data\run.log"
$Python   = "python"
$NodeDir  = Join-Path $PSScriptRoot ".tools\node-v22.20.0-win-x64"

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $stamp = (Get-Date).ToString("HH:mm:ss")
    $line  = "{0}  {1,-7} {2}" -f $stamp, $Level, $Message
    $color = switch ($Level) {
        "OK"    { "Green" }
        "SKIP"  { "DarkGray" }
        "WARN"  { "Yellow" }
        "FAIL"  { "Red" }
        "STAGE" { "Cyan" }
        default { "Gray" }
    }
    Write-Host $line -ForegroundColor $color
    Add-Content -Path $LogFile -Value $line
}

function Test-Stale {
    <#
      A stage needs to run when its artifact is missing, or when the module that
      produces it has been edited since. That second condition is what makes
      "fix a bug, re-run the script" do the right thing without anyone having to
      remember which downstream stages were affected.
    #>
    param([string]$Artifact, [string[]]$Sources)

    if (-not (Test-Path $Artifact)) { return $true }
    $artifactTime = (Get-Item $Artifact).LastWriteTime
    foreach ($src in $Sources) {
        if (Test-Path $src) {
            if ((Get-Item $src).LastWriteTime -gt $artifactTime) { return $true }
        }
    }
    return $false
}

$script:Failures = @()
$script:Ran      = @()
$script:Skipped  = @()

function Invoke-Stage {
    param(
        [string]$Name,
        [string]$Command,
        [string]$Artifact,
        [string[]]$Sources = @(),
        [switch]$Critical      # a failure here stops the whole run
    )

    if ($Only -and ($Only -notcontains $Name)) { return }

    if (-not $Force -and $Artifact -and -not (Test-Stale $Artifact $Sources)) {
        Write-Log "$Name -- artifact current, skipping" "SKIP"
        $script:Skipped += $Name
        return
    }

    Write-Log "=== $Name ===" "STAGE"
    $sw = [Diagnostics.Stopwatch]::StartNew()

    # Capture stdout+stderr so a failure is diagnosable from the log alone.
    $output = & cmd /c "$Command 2>&1"
    $code = $LASTEXITCODE
    $sw.Stop()

    foreach ($line in $output) { Add-Content -Path $LogFile -Value "    $line" }

    if ($code -ne 0) {
        Write-Log "$Name FAILED (exit $code) after $([math]::Round($sw.Elapsed.TotalSeconds))s" "FAIL"
        $output | Select-Object -Last 12 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkRed }
        $script:Failures += $Name
        if ($Critical) {
            Write-Log "stage is critical -- stopping. See $LogFile" "FAIL"
            exit 1
        }
        return
    }

    # Surface the lines that actually carry findings, not the whole firehose.
    $output |
        Select-String -Pattern "GATE|H2 |H3 |suppression:|disagreement|top driver|BASELINE|OPTIMISED @60|capacity cut|call plan @|unconstrained|selected k|PRE-TREND|DiD:|SELECTION GAP|CHALLENGER|CHAMPION|GAMED|tornado:|frontier fit|SFA cross" |
        Select-Object -Last 8 |
        ForEach-Object { Write-Host "    $_" -ForegroundColor DarkCyan }

    Write-Log "$Name OK in $([math]::Round($sw.Elapsed.TotalSeconds))s" "OK"
    $script:Ran += $Name
}

# --------------------------------------------------------------------------- #

Write-Host ""
Write-Log "PharmaTarget run started -- log: $LogFile" "STAGE"
if ($Force)  { Write-Log "-Force: every stage will re-run" "WARN" }
if ($Only)   { Write-Log "-Only: $($Only -join ', ')" "WARN" }

$P = "data\processed"
$R = "data\raw"

# --------------------------------------------------------------------------- #
# 1. ingest  (only runs if data/raw is incomplete)
# --------------------------------------------------------------------------- #

Invoke-Stage -Name "geography" `
    -Command "$Python -m src.ingest.geo_build --local-dir dataset" `
    -Artifact "$R\zip3_units.csv" `
    -Sources @("src\ingest\geo_build.py")

Invoke-Stage -Name "ingest" `
    -Command "$Python -m src.ingest.download --local-dir dataset" `
    -Artifact "$R\open_payments_2024.csv" `
    -Sources @("src\ingest\download.py")

# --------------------------------------------------------------------------- #
# 2. marts
# --------------------------------------------------------------------------- #

Invoke-Stage -Name "marts" -Critical `
    -Command "$Python -m src.etl.build_marts" `
    -Artifact "$P\mart_hcp_metrics.parquet" `
    -Sources @("src\etl\build_marts.py",
               "src\sql\01_stg_prescribers.sql",
               "src\sql\02_stg_scripts.sql",
               "src\sql\03_suppression_recon.sql",
               "src\sql\04_mart_hcp_metrics.sql",
               "src\sql\05_mart_payments.sql",
               "config\params.yaml")

# --------------------------------------------------------------------------- #
# 3. models
# --------------------------------------------------------------------------- #

Invoke-Stage -Name "opportunity" -Critical `
    -Command "$Python -m src.models.opportunity" `
    -Artifact "$P\hcp_scored.parquet" `
    -Sources @("src\models\opportunity.py", "$P\mart_hcp_metrics.parquet")

Invoke-Stage -Name "callplan" -Critical `
    -Command "$Python -m src.models.callplan" `
    -Artifact "$P\hcp_call_plan.parquet" `
    -Sources @("src\models\callplan.py", "$P\hcp_scored.parquet", "config\economics.yaml")

Invoke-Stage -Name "backtest" `
    -Command "$Python -m src.models.backtest" `
    -Artifact "$P\backtest_decile_lift.parquet" `
    -Sources @("src\models\backtest.py", "$P\hcp_scored.parquet")

Invoke-Stage -Name "challenger" `
    -Command "$Python -m src.models.challenger" `
    -Artifact "$P\challenger_results.parquet" `
    -Sources @("src\models\challenger.py", "$P\hcp_scored.parquet")

Invoke-Stage -Name "sizing" `
    -Command "$Python -m src.models.sizing" `
    -Artifact "$P\sizing_tornado.parquet" `
    -Sources @("src\models\sizing.py", "$P\hcp_call_plan.parquet", "config\economics.yaml")

Invoke-Stage -Name "territory" `
    -Command "$Python -m src.models.territory" `
    -Artifact "$P\territory_stats.parquet" `
    -Sources @("src\models\territory.py", "$P\hcp_call_plan.parquet", "src\utils\geo.py")

Invoke-Stage -Name "segmentation" `
    -Command "$Python -m src.models.segmentation" `
    -Artifact "$P\segment_profiles.parquet" `
    -Sources @("src\models\segmentation.py", "$P\hcp_scored.parquet")

# Response writes no parquet when the saturation curve is unidentifiable -- which
# is a legitimate outcome, not a failure -- so it is keyed off the balance table
# and simply re-runs when that is absent. It is cheap.
Invoke-Stage -Name "response" `
    -Command "$Python -m src.models.response" `
    -Artifact "$P\response_balance.parquet" `
    -Sources @("src\models\response.py", "$P\mart_hcp_metrics.parquet")

# --------------------------------------------------------------------------- #
# 4. quality
# --------------------------------------------------------------------------- #

# Gates G2 and G4 are evaluated by src/pipeline.py, which run_all.ps1 does not
# call -- it runs each module directly so stages stay independently resumable.
# Without this, only G3 (recorded inside backtest.py) ever reaches the manifest,
# and the summary silently reports one gate instead of three.
Invoke-Stage -Name "gates" `
    -Command "$Python -m src.utils.gates" `
    -Artifact "" `

Invoke-Stage -Name "assets" `
    -Command "$Python -m src.report.make_assets" `
    -Artifact "outputs\PharmaTarget_Recommendations.pdf" `
    -Sources @("src\report\make_assets.py", "$P\territory_stats.parquet",
               "$P\challenger_results.parquet", "data\manifest.json")

Invoke-Stage -Name "lint" `
    -Command "$Python -m ruff check src api tests" `
    -Artifact ""

Invoke-Stage -Name "tests" `
    -Command "$Python -m pytest tests -q" `
    -Artifact ""

# --------------------------------------------------------------------------- #
# 5. frontend
# --------------------------------------------------------------------------- #

if (-not $SkipWeb) {
    $npm = $null
    if (Test-Path "$NodeDir\npm.cmd") {
        $env:Path = "$NodeDir;$env:Path"
        $npm = "$NodeDir\npm.cmd"
    } elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        $npm = "npm"
    }

    if (-not $npm) {
        Write-Log "npm not found -- skipping the frontend build. The API will serve web/static instead." "WARN"
    } else {
        if (-not (Test-Path "web\node_modules")) {
            Invoke-Stage -Name "web-install" `
                -Command "cd web && `"$npm`" install --no-fund --no-audit" `
                -Artifact "web\node_modules\.package-lock.json"
        }
        Invoke-Stage -Name "web-build" `
            -Command "cd web && `"$npm`" run build" `
            -Artifact "web\dist\index.html" `
            -Sources @("web\src", "web\package.json", "web\vite.config.ts")
    }
}

# --------------------------------------------------------------------------- #
# 6. summary
# --------------------------------------------------------------------------- #

Write-Host ""
Write-Log "=== SUMMARY ===" "STAGE"
Write-Log ("ran: {0}" -f ($(if ($script:Ran) { $script:Ran -join ', ' } else { 'nothing' })))
if ($script:Skipped) { Write-Log ("skipped (current): {0}" -f ($script:Skipped -join ', ')) "SKIP" }
if ($script:Failures) { Write-Log ("FAILED: {0}" -f ($script:Failures -join ', ')) "FAIL" }

if (Test-Path "data\manifest.json") {
    Write-Host ""
    # Rendered by src/utils/summary.py, not embedded here: Python inside a
    # PowerShell here-string needs quote escaping that silently yields invalid
    # Python, and a summary that crashes after a two-hour run is worse than none.
    & $Python -m src.utils.summary
}

Write-Host ""
if ($script:Failures) {
    Write-Log "finished WITH FAILURES -- see $LogFile" "FAIL"
} else {
    Write-Log "finished cleanly" "OK"
}

if ($Serve) {
    Write-Host ""
    Write-Log "starting the API on http://127.0.0.1:8000  (Ctrl+C to stop)" "STAGE"
    & $Python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
}
