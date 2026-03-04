# Minimal validator for LLM-generated PMD XPath rules.
# Reads llm-generated-xpaths and runs pmd-xpath-check.ps1 for each xpath expression.
#
# Usage:
#   .\scripts\validate-llm-generated-xpaths.ps1 `
#     -GeneratedJsonl path\to\llm-generated-xpaths.jsonl `
#     -PmdXPathCheck .\scripts\pmd-xpath-check.ps1 `
#     -PmdBin "path\to\pmd.bat" `
#     -Target "path\to\java\fileOrDir"
#
# Default output layout per run:
#   .\out\evaluated-llm-rules_<input-name>_<timestamp>\
#     results.jsonl
#     reports\<ruleKey>.json

param(
    [Parameter(Mandatory = $true)][string]$GeneratedJsonl,
    [Parameter(Mandatory = $true)][string]$PmdXPathCheck,
    [Parameter(Mandatory = $true)][string]$PmdBin,
    [Parameter(Mandatory = $true)][string]$Target,

    # Optional: base directory for one validation run.
    [string]$OutDir = "",
    # Optional: override path for JSONL results file.
    [string]$OutJsonl = "",
    # Optional: override path for per-rule PMD JSON reports.
    [string]$ReportsDir = ""
)

# Enable strict mode to catch undefined variables and other mistakes early that could lead to silent failures.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

# Create directory if it doesn't exist (like mkdir -p in Unix)
function New-Dir([string]$p) {
    # -Force: create if doesn't exist, or succeed if already exists (no error)
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}

function ConvertTo-SafeFileName([string]$s) {
    # Replace invalid filename characters with underscores
    # This prevents "filename invalid" errors when writing per-rule report files
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($c in $invalid) { $s = $s.Replace([string]$c, "_") }
    return $s
}

function Get-Timestamp() {
    # Get current timestamp in YYYYmmdd-HHmmss format for run folder names.
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

if (-not (Test-Path $GeneratedJsonl)) { throw "GeneratedJsonl does not exist: $GeneratedJsonl" }
if (-not (Test-Path $PmdXPathCheck)) { throw "PmdXPathCheck does not exist: $PmdXPathCheck" }
if (-not (Test-Path $Target)) { throw "Target does not exist: $Target" }

# Auto-generate a per-run output directory when one is not provided.
if (-not $OutDir) {
    $inputItem = Get-Item $GeneratedJsonl
    $inputName = [System.IO.Path]::GetFileNameWithoutExtension($inputItem.Name)
    $baseOut = Join-Path (Get-Location) "out"
    $OutDir = Join-Path $baseOut ("evaluated-llm-rules_{0}_{1}" -f $inputName, (Get-Timestamp))
}

New-Dir $OutDir

# Default results/report locations live under the run directory.
if (-not $OutJsonl) {
    $OutJsonl = Join-Path $OutDir "results.jsonl"
}
if (-not $ReportsDir) {
    $ReportsDir = Join-Path $OutDir "reports"
}

# Initialize output file (truncate if exists) so we always start fresh
"" | Set-Content -Path $OutJsonl -Encoding UTF8
# Ensure report output directory exists before processing
New-Dir $ReportsDir

# Line counter used for fallback report names when ruleKey is missing
$idx = 0
# Stream input JSONL line-by-line to avoid loading whole file into memory
Get-Content -Path $GeneratedJsonl -Encoding UTF8 | ForEach-Object {
    $idx++
    # Trim whitespace and skip empty lines to avoid JSON parse errors
    $line = $_.Trim()
    if (-not $line) { return }

    # Parse JSON line into object with ruleKey + xpath
    $rec = $line | ConvertFrom-Json
    $ruleKey = $rec.ruleKey
    $xpath = [string]$rec.xpath

    # Base output row:
    $row = [ordered]@{
        ruleKey = $ruleKey
        xpath   = $xpath
    }

    # Always pass a unique report path to avoid overwriting / empty shells
    $safeKey = ConvertTo-SafeFileName ([string]$ruleKey)
    if (-not $safeKey -or $safeKey -eq "null") { $safeKey = "rule-$idx" }
    $outReport = Join-Path $ReportsDir ($safeKey + ".json")

    try {
        # Execute PMD XPath check and capture its JSON output
        $jsonOut = & $PmdXPathCheck `
            -PmdBin $PmdBin `
            -Target $Target `
            -XPath $xpath `
            -Format json `
            -OutReport $outReport

        # Parse JSON output from pmd-xpath-check.ps1
        $pmd = $jsonOut | ConvertFrom-Json

        # Merge PMD output fields into the output row
        foreach ($p in $pmd.PSObject.Properties) {
            $row[$p.Name] = $p.Value
        }

        # Always include the report path in the output row, even if PMD fails to generate a report (e.g. due to invalid XPath), so the caller can check for the presence of a report file as needed.
        $row["reportPath"] = $outReport
    }
    catch {
        # Record a crash so the caller can distinguish PMD errors from XPath results
        $row["status"] = "validator_crash"
        $row["error"] = $_.Exception.Message
        $row["reportPath"] = $outReport
    }

    # Append the merged row as a single JSON line (JSONL format)
    ($row | ConvertTo-Json -Depth 20 -Compress) | Add-Content -Path $OutJsonl -Encoding UTF8
}

Write-Host "Validation output written to:" -ForegroundColor Green
Write-Host ("  Results JSONL: {0}" -f (Resolve-Path $OutJsonl).Path) -ForegroundColor Green
Write-Host ("  Per-rule reports: {0}" -f (Resolve-Path $ReportsDir).Path) -ForegroundColor Green
$stopwatch.Stop()
Write-Host ("  Runtime: {0:c}" -f $stopwatch.Elapsed) -ForegroundColor Green
