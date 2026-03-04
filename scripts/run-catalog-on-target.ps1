<# 
run-catalog-on-target.ps1 - Run the official PMD catalog rules against a target codebase, using pmd-xpath-check.ps1, validating their XPath expressions and collecting results.

DESCRIPTION:
Core validation engine that iterates through the catalog of official PMD rules, extracts their XPath expressions,
and executes them against target code. For each rule, calls pmd-xpath-check.ps1 to run the XPath query and collect results.
Aggregates findings into a summary report + per-rule reports for analysis.

HOW IT WORKS:
  1. Load pmd-catalog.json and extract all rule keys
  2. Apply RuleRegex filter and MaxRules limit (if specified)
  3. For each rule:
     - Extract XPath from rule definition
     - Call pmd-xpath-check.ps1 to execute XPath against target code
     - Collect PMD output (violation count, errors, report JSON)
     - Enrich with metadata (category, description, etc.)
     - Append result to results.jsonl
  4. Write run-metadata.json with configuration snapshot for reproducibility
  5. Output paths to results and rule reports directories

OUTPUTS:
  results.jsonl             - One JSON object per rule with execution results and metadata
  reports/<RuleKey>.json    - Individual PMD JSON reports for each rule
  run-metadata.json         - Summary of the run configuration

USEFUL FEATURES:
  - Filtering: process only matching rules via -RuleRegex "pattern"
  - Limiting: restrict rule count via -MaxRules N for testing
  - Metadata: captures full run configuration
  - Error handling: Handles missing XPath, config errors, processing errors

EXAMPLE USAGE:
  # All rules, full repo
  .\scripts\run-catalog-on-target.ps1 `
    -PmdBin "path\to\pmd.bat" `
    -RepoPath "path\to\target\repo" `
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$PmdBin,
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,
    [string]$CatalogPath = ".\config\pmd-catalog.json",
    [string]$XPathCheckScript = ".\scripts\pmd-xpath-check.ps1",
    [string]$OutDir = "",
    [ValidateSet("json")]
    [string]$Format = "json",
    [string]$RuleRegex = "",
    [int]$MaxRules = 0,
    [string]$RepoTargetSubPath = ""
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

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    # Write UTF-8 text without a Byte Order Mark (BOM).
    # PMD's XML parser is strict about BOM. If a UTF-8 file contains the 3-byte BOM (\xEF\xBB\xBF),
    # the parser may reject the file as invalid, causing ruleset loading to fail.
    # By explicitly using UTF8Encoding(false), we ensure no BOM is written, guaranteeing PMD can parse our ruleset.
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-Timestamp() {
    # Get current timestamp in YYYYmmdd-HHmmss format
    # Used for auto-generating timestamp-based output directory names
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function ConvertTo-SafeFileName([string]$s) {
    # Replace invalid filename characters with underscores
    # This prevents "filename invalid" errors when writing per-rule report files
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($c in $invalid) { $s = $s.Replace([string]$c, "_") }
    return $s
}

# Check that critical paths exist before starting the run.
if (-not (Test-Path $RepoPath)) { throw "RepoPath does not exist: $RepoPath" }
if (-not (Test-Path $CatalogPath)) { throw "CatalogPath does not exist: $CatalogPath" }
if (-not (Test-Path $XPathCheckScript)) { throw "XPathCheckScript does not exist: $XPathCheckScript" }

$repoItem = Get-Item $RepoPath
# Extract a clean name: use folder name for directories, filename stem for files
$repoName = if ($repoItem.PSIsContainer) { $repoItem.Name } else { [System.IO.Path]::GetFileNameWithoutExtension($repoItem.Name) }

# If OutDir not specified by user, auto-generate descriptive name
# Format: out/catalog-run_<RepoBaseName>_<YYYYmmdd-HHmmss>
if (-not $OutDir) {
    $baseOut = Join-Path (Get-Location) "out"
    $OutDir = Join-Path $baseOut ("catalog-run_{0}_{1}" -f $repoName, (Get-Timestamp))
}

# Create reports subdirectory for per-rule PMD JSON reports
$reportsDir = Join-Path $OutDir "reports"
New-Dir $OutDir
New-Dir $reportsDir

# Define paths to main output files
$resultsPath = Join-Path $OutDir "results.jsonl"
$metaPath = Join-Path $OutDir "run-metadata.json"

# Default: analyze entire RepoPath (which could be folder or single file)
$targetPath = $RepoPath
# If RepoTargetSubPath specified, verify it exists and analyze only that subfolder
# Useful for projects where only specific source folder matters
if ($RepoTargetSubPath) {
    $candidate = Join-Path $RepoPath $RepoTargetSubPath
    if (-not (Test-Path $candidate)) { throw "RepoTargetSubPath does not exist under repo: $candidate" }
    $targetPath = $candidate
}

# Load pmd-catalog.json file
$catalog = Get-Content $CatalogPath -Raw | ConvertFrom-Json
# Verify top-level structure
if ($null -eq $catalog.rules) { throw "Catalog JSON missing top-level 'rules' object: $CatalogPath" }

# Extract all rule names (keys) from rules object and sort alphabetically
# PSObject.Properties gives key-value pairs; .Name extracts just the keys
$ruleKeys = @($catalog.rules.PSObject.Properties.Name | Sort-Object)

# Apply regex filter if specified (e.g., -RuleRegex "Avoid|System")
if ($RuleRegex) {
    Write-Host "Filtering rules by regex: $RuleRegex" -ForegroundColor Cyan
    $ruleKeys = $ruleKeys | Where-Object { $_ -match $RuleRegex }
    Write-Host "After filtering: $($ruleKeys.Count) rule(s) to process" -ForegroundColor Cyan
}

# Apply rule count limit if specified (e.g., -MaxRules 10)
if ($MaxRules -gt 0) {
    Write-Host "Limiting to first $MaxRules rule(s)" -ForegroundColor Cyan
    $ruleKeys = $ruleKeys | Select-Object -First $MaxRules
}

# Create ordered dictionary with all run parameters for metadata recording
#   - When exactly the run was executed
#   - What filters were applied (regex, max rules, etc.)
#   - Where inputs came from (paths to catalog, script, PMD)
#   - Where outputs are stored (absolute path to OutDir)
#   - How many rules will be processed (after filtering)
$metaObj = [ordered]@{
    timestamp         = (Get-Date).ToString("o")               # Get current timestamp
    repoPath          = $RepoPath                              # Intended path to repo (may be relative)
    analyzedTarget    = $targetPath                            # Actual path analyzed (may include RepoTargetSubPath)
    catalogPath       = (Resolve-Path $CatalogPath).Path       # Absolute path to pmd-catalog.json
    xpathCheckScript  = (Resolve-Path $XPathCheckScript).Path  # Absolute path to pmd-xpath-check.ps1
    pmdBin            = $PmdBin                                # PMD binary location (may be relative path)
    ruleRegex         = $RuleRegex                             # Applied regex filter (empty string if no filter)
    maxRules          = $MaxRules                              # Rule limit applied (0 = no limit)
    outDir            = (Resolve-Path $OutDir).Path            # Output directory (absolute path)
    format            = $Format                                # Report format (currently always "json")
    totalPlannedRules = @($ruleKeys).Count                     # Total rules to process after all filters applied
}
# Write metadata as JSON file for reproducibility and debugging
Write-Utf8NoBom -Path $metaPath -Content (($metaObj | ConvertTo-Json -Depth 6))
Write-Host "Metadata written to: $metaPath" -ForegroundColor Green


# MAIN PROCESSING LOOP: iterate through each rule key, execute XPath check, and collect results

$processed = 0 # Counter for processed rules, used for progress reporting
foreach ($ruleKey in $ruleKeys) {
    # Look up the rule object in catalog (extract full rule metadata)
    $rule = $catalog.rules.$ruleKey
    # Sanity check: if rule not found in catalog, skip it (shouldn't happen, but edge case if catalog is malformed)
    if ($null -eq $rule) { continue }

    # Extract XPath expression from rule definition
    $xpath = [string]$rule.xpath
    
    # Sanitize rule name for safe filename (replace invalid chars with underscores)
    $safeName = ConvertTo-SafeFileName $ruleKey
    # Construct path to per-rule PMD report: reports/<RuleKey>.json
    $perRuleReport = Join-Path $reportsDir ($safeName + ".json")

    # CALL pmd-xpath-check.ps1 to execute the XPath against target code
    # This script:
    #   1. Generates a temporary minimal ruleset XML with the XPath rule
    #   2. Runs PMD with -format json to get structured output
    #   3. Extracts violation count, syntax validity, errors from PMD output
    #   4. Returns JSON object with: status, syntacticValid, exitCode, violationCount,
    #      hadConfigErrors, hadProcessingErrors, reportPath, stdoutSnippet, stderrSnippet
    # Parameters:
    #   -PmdBin: Full path to pmd.bat/pmd.sh
    #   -Target: Folder or file to analyze
    #   -XPath: The XPath expression to test
    #   -Format: Output format ("json")
    #   -OutReport: Where to write per-rule PMD report
    $checkerJson = & $XPathCheckScript `
        -PmdBin $PmdBin `
        -Target $targetPath `
        -XPath $xpath `
        -Format $Format `
        -OutReport $perRuleReport | Out-String

    # Parse the JSON response from pmd-xpath-check.ps1 into a PowerShell object for easier access to properties
    $checkerObj = $checkerJson | ConvertFrom-Json
    
    # Create comprehensive result object combining:
    #   1. Rule identification (ruleKey + catalog metadata)
    #   2. Execution results from pmd-xpath-check.ps1
    $outObj = [ordered]@{
        # Rule identification and metadata from catalog
        ruleKey                    = $ruleKey                          # Rule name
        category                   = $rule.category                    # Category (Best Practices, Performance, etc.)
        ref                        = $rule.ref                         # Reference URL to PMD documentation
        sourceFiles                = $rule.sourceFiles                 # Source file(s)
        message                    = $rule.message                     # Rule message template
        description                = $rule.description                 # Full rule description

        # Execution status and results from pmd-xpath-check.ps1
        status                     = $checkerObj.status                # "ok", "invalid", or "error"
        syntacticValid             = $checkerObj.syntacticValid        # Boolean: XPath syntax is valid
        exitCode                   = $checkerObj.exitCode              # PMD process exit code (0 = success)
        violationCount             = $checkerObj.violationCount        # Number of violations found (-1 if error)

        # Configuration and processing error information
        hadConfigErrors            = $checkerObj.hadConfigErrors             # Boolean: ruleset XML had config errors
        configErrorCount           = $checkerObj.configErrorCount            # Count of config errors
        hadProcessingErrors        = $checkerObj.hadProcessingErrors         # Boolean: PMD had runtime errors
        processingErrorCountReport = $checkerObj.processingErrorCountReport  # Error count from PMD JSON report
        processingErrorCountStderr = $checkerObj.processingErrorCountStderr  # Error count from stderr

        # Output paths and diagnostic snippets
        reportPath                 = $perRuleReport                    # (Absolute) path to per-rule PMD JSON
        rulesetPath                = $checkerObj.rulesetPath           # Path to temporary ruleset XML used
        stdoutSnippet              = $checkerObj.stdoutSnippet         # First 500 chars of PMD stdout (violations or logs)
        stderrSnippet              = $checkerObj.stderrSnippet         # First 500 chars of PMD stderr (errors)
    }
    
    # Append result as JSON object (one per line) to results.jsonl
    # JSONL format (JSON lines) allows analysis tools to process one line at a time
    Add-Content -Path $resultsPath -Value ($outObj | ConvertTo-Json -Depth 10)

    # Increment rule counter
    $processed++
    # Every 25 rules processed, print progress status
    # Useful for long runs to see that processing is ongoing and get a sense of how many rules are left
    if (($processed % 25) -eq 0) {
        Write-Host ("Processed {0}/{1} rules..." -f $processed, @($ruleKeys).Count) -ForegroundColor Cyan
    }
}

$stopwatch.Stop()
Write-Host ("Runtime: {0:c}" -f $stopwatch.Elapsed) -ForegroundColor Green
