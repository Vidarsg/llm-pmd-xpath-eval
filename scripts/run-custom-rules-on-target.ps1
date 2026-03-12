<#
run-custom-rules-on-target.ps1 - Run custom PMD XPath rules from JSON/JSONL against a target codebase.

DESCRIPTION:
Loads custom rules from a JSON or JSONL file, extracts each rule's xpath, and
executes it against a target using pmd-xpath-check.ps1. Intended for rule sets
like jpinpoint-rule-xpaths.jsonl where only ruleKey/id and xpath are required.

SUPPORTED INPUT SHAPES:
  - JSONL: one object per line with at least { "xpath": "..." }
  - JSON: a single object with an xpath field
  - JSON: an array of objects with xpath fields

OPTIONAL FIELDS:
  - ruleKey or id
  - description, message, category, ref, sourceFiles

EXAMPLE USAGE:
  .\scripts\run-custom-rules-on-target.ps1 `
    -PmdBin "path\to\pmd.bat" `
    -RepoPath "path\to\target\repo" `
    -RulesPath "path\to\rules.jsonl"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$PmdBin,
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,
    [Parameter(Mandatory = $true)]
    [string]$RulesPath,
    [string]$XPathCheckScript = ".\scripts\pmd-xpath-check.ps1",
    [string]$OutDir = "",
    [ValidateSet("json")]
    [string]$Format = "json",
    [string]$RuleRegex = "",
    [int]$MaxRules = 0,
    [string]$RepoTargetSubPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

function New-Dir([string]$p) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-Timestamp() {
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function ConvertTo-SafeFileName([string]$s) {
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($c in $invalid) { $s = $s.Replace([string]$c, "_") }
    return $s
}

function Get-OptionalProperty([object]$Obj, [string]$Name) {
    if ($null -eq $Obj) { return $null }
    $prop = $Obj.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function New-RuleRecord([object]$Obj, [string]$FallbackRuleKey) {
    if ($null -eq $Obj) {
        throw "Encountered null rule record"
    }

    $xpath = Get-OptionalProperty -Obj $Obj -Name "xpath"
    if ($null -eq $xpath -or [string]$xpath -eq "") {
        throw "Rule record is missing xpath"
    }

    $explicitRuleKey = Get-OptionalProperty -Obj $Obj -Name "ruleKey"
    $idValue = Get-OptionalProperty -Obj $Obj -Name "id"
    $ruleKey = if ($null -ne $explicitRuleKey -and [string]$explicitRuleKey -ne "") {
        [string]$explicitRuleKey
    }
    elseif ($null -ne $idValue -and [string]$idValue -ne "") {
        [string]$idValue
    }
    else {
        $FallbackRuleKey
    }

    return [pscustomobject]@{
        ruleKey     = $ruleKey
        xpath       = [string]$xpath
        category    = Get-OptionalProperty -Obj $Obj -Name "category"
        ref         = Get-OptionalProperty -Obj $Obj -Name "ref"
        sourceFiles = Get-OptionalProperty -Obj $Obj -Name "sourceFiles"
        message     = Get-OptionalProperty -Obj $Obj -Name "message"
        description = Get-OptionalProperty -Obj $Obj -Name "description"
    }
}

function Get-RuleRecords([string]$Path) {
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()

    if ($extension -eq ".jsonl") {
        $records = @()
        $lineNumber = 0
        Get-Content -Path $Path -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if (-not $line) { return }
            $lineNumber++
            $obj = $line | ConvertFrom-Json
            $records += New-RuleRecord -Obj $obj -FallbackRuleKey ([string]$lineNumber)
        }
        return $records
    }

    if ($extension -eq ".json") {
        $json = Get-Content $Path -Raw | ConvertFrom-Json

        if ($json -is [System.Collections.IEnumerable] -and -not ($json -is [string])) {
            $records = @()
            $index = 0
            foreach ($item in $json) {
                $index++
                $records += New-RuleRecord -Obj $item -FallbackRuleKey ([string]$index)
            }
            return $records
        }

        if ($null -ne (Get-OptionalProperty -Obj $json -Name "xpath")) {
            return @(New-RuleRecord -Obj $json -FallbackRuleKey "1")
        }

        throw "Unsupported JSON rule source shape in $Path. Expected an object or array with xpath fields."
    }

    throw "Unsupported rule source format: $Path"
}

if (-not (Test-Path $RepoPath)) { throw "RepoPath does not exist: $RepoPath" }
if (-not (Test-Path $RulesPath)) { throw "RulesPath does not exist: $RulesPath" }
if (-not (Test-Path $XPathCheckScript)) { throw "XPathCheckScript does not exist: $XPathCheckScript" }
if (-not (Test-Path $PmdBin)) { throw "PmdBin does not exist: $PmdBin" }

$repoItem = Get-Item $RepoPath
$repoName = if ($repoItem.PSIsContainer) { $repoItem.Name } else { [System.IO.Path]::GetFileNameWithoutExtension($repoItem.Name) }

if (-not $OutDir) {
    $baseOut = Join-Path (Get-Location) "out"
    $OutDir = Join-Path $baseOut ("custom-run_{0}_{1}" -f $repoName, (Get-Timestamp))
}

$reportsDir = Join-Path $OutDir "reports"
New-Dir $OutDir
New-Dir $reportsDir

$resultsPath = Join-Path $OutDir "results.jsonl"
$metaPath = Join-Path $OutDir "run-metadata.json"

$targetPath = $RepoPath
if ($RepoTargetSubPath) {
    $candidate = Join-Path $RepoPath $RepoTargetSubPath
    if (-not (Test-Path $candidate)) { throw "RepoTargetSubPath does not exist under repo: $candidate" }
    $targetPath = $candidate
}

$ruleRecords = @(Get-RuleRecords -Path $RulesPath)

if ($RuleRegex) {
    Write-Host "Filtering rules by regex: $RuleRegex" -ForegroundColor Cyan
    $ruleRecords = @($ruleRecords | Where-Object { $_.ruleKey -match $RuleRegex })
    Write-Host "After filtering: $($ruleRecords.Count) rule(s) to process" -ForegroundColor Cyan
}

if ($MaxRules -gt 0) {
    Write-Host "Limiting to first $MaxRules rule(s)" -ForegroundColor Cyan
    $ruleRecords = @($ruleRecords | Select-Object -First $MaxRules)
}

$metaObj = [ordered]@{
    timestamp         = (Get-Date).ToString("o")
    repoPath          = $RepoPath
    analyzedTarget    = $targetPath
    rulesPath         = (Resolve-Path $RulesPath).Path
    xpathCheckScript  = (Resolve-Path $XPathCheckScript).Path
    pmdBin            = $PmdBin
    ruleRegex         = $RuleRegex
    maxRules          = $MaxRules
    outDir            = (Resolve-Path $OutDir).Path
    format            = $Format
    totalPlannedRules = @($ruleRecords).Count
}
Write-Utf8NoBom -Path $metaPath -Content (($metaObj | ConvertTo-Json -Depth 6))
Write-Host "Metadata written to: $metaPath" -ForegroundColor Green

$processed = 0
foreach ($rule in $ruleRecords) {
    $ruleKey = [string]$rule.ruleKey
    $xpath = [string]$rule.xpath
    if ($rule.xpath -is [System.Array]) {
        throw "Rule '$ruleKey' has multiple xpath values. Each rule must provide exactly one xpath string."
    }
    $safeName = ConvertTo-SafeFileName $ruleKey
    $perRuleReport = Join-Path $reportsDir ($safeName + ".json")

    $checkerJson = & $XPathCheckScript `
        -PmdBin $PmdBin `
        -Target $targetPath `
        -XPath $xpath `
        -Format $Format `
        -OutReport $perRuleReport | Out-String

    $checkerObj = $checkerJson | ConvertFrom-Json

    $outObj = [ordered]@{
        ruleKey                    = $ruleKey
        status                     = $checkerObj.status
        syntacticValid             = $checkerObj.syntacticValid
        exitCode                   = $checkerObj.exitCode
        violationCount             = $checkerObj.violationCount
        hadConfigErrors            = $checkerObj.hadConfigErrors
        configErrorCount           = $checkerObj.configErrorCount
        hadProcessingErrors        = $checkerObj.hadProcessingErrors
        processingErrorCountReport = $checkerObj.processingErrorCountReport
        processingErrorCountStderr = $checkerObj.processingErrorCountStderr
        reportPath                 = $perRuleReport
        rulesetPath                = $checkerObj.rulesetPath
        stdoutSnippet              = $checkerObj.stdoutSnippet
        stderrSnippet              = $checkerObj.stderrSnippet
    }

    Add-Content -Path $resultsPath -Value ($outObj | ConvertTo-Json -Depth 10 -Compress)
    $processed++
    if (($processed % 25) -eq 0) {
        Write-Host ("Processed {0}/{1} rules..." -f $processed, @($ruleRecords).Count) -ForegroundColor Cyan
    }
}

$stopwatch.Stop()
Write-Host ("Runtime: {0:c}" -f $stopwatch.Elapsed) -ForegroundColor Green
