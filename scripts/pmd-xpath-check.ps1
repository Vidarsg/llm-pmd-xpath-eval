<# 
pmd-xpath-check.ps1

Example:
  .\scripts\pmd-xpath-check.ps1 `
    -PmdBin "path\to\pmd.bat" `
    -Target "path\to\java\fileOrDir" `
    -XPath "//Some/Expression" `
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$PmdBin,

    [Parameter(Mandatory = $true)]
    [string]$Target,

    [Parameter(Mandatory = $true)]
    [string]$XPath,

    [ValidateSet("text", "json", "xml")]
    [string]$Format = "json",

    [string]$OutReport = ".\out"
)

# Enable strict mode to catch undefined variables and other mistakes early that could lead to silent failures.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-TempDirectory {
    # Each run gets its own temp workspace, to avoid cluttering the repo with generated files.
    $base = Join-Path ([System.IO.Path]::GetTempPath()) "pmd-xpath-check"
    $dir = Join-Path $base ([System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

function Read-FileOrEmpty([string]$Path) {
    # Safely read a file's content, returning an empty string if the file doesn't exist.
    # PMD may not produce certain output files if it crashes or encounters errors.
    # By returning an empty string instead of throwing an error,
    # we allow the script to continue and analyze other signals (like exit code and stderr) to determine what went wrong.
    if (Test-Path $Path) {
        return Get-Content $Path -Raw
    }
    return ""
}

function Snip([string]$s, [int]$n) {
    # Truncate output to prevent overwhelming JSON payloads.
    # PMD may print large stack traces or logs to stdout/stderr,
    # and including the full output in the JSON result can make the JSON file enormous and difficult to parse.
    if ($null -eq $s) { return "" }
    $s = [string]$s
    if ($s.Length -le $n) { return $s }
    return $s.Substring(0, $n)
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    # Write UTF-8 text without a Byte Order Mark (BOM).
    # PMD's XML parser is strict about BOM. If a UTF-8 file contains the 3-byte BOM (\xEF\xBB\xBF),
    # the parser may reject the file as invalid, causing ruleset loading to fail.
    # By explicitly using UTF8Encoding(false), we ensure no BOM is written, guaranteeing PMD can parse our ruleset.
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Remove-ViolationPriorityFromJsonReport([string]$Path) {
    # Removes the PMD-emitted priority property from the violation reports,
    # because it always resorts to a default value, and is not relevant to the validation of the XPath rule itself.
    if (-not (Test-Path $Path)) { return }

    try {
        $report = Get-Content $Path -Raw | ConvertFrom-Json
    }
    catch {
        return
    }

    foreach ($file in @($report.files)) {
        foreach ($v in @($file.violations)) {
            if ($null -ne $v -and $v.PSObject.Properties["priority"]) {
                $v.PSObject.Properties.Remove("priority")
            }
        }
    }

    Write-Utf8NoBom -Path $Path -Content ($report | ConvertTo-Json -Depth 100)
}

function Remove-UnhelpfulPmdJsonFields([string]$Path) {
    # PMD keeps these top-level arrays in the JSON schema even when they are empty.
    # For this workflow they are misleading, since config/processing issues are derived more reliably from stderr and surfaced via script-added fields.
    if (-not (Test-Path $Path)) { return }

    try {
        $report = Get-Content $Path -Raw | ConvertFrom-Json
    }
    catch {
        return
    }

    foreach ($name in @("suppressedViolations", "processingErrors", "configurationErrors")) {
        if ($report.PSObject.Properties[$name]) {
            $report.PSObject.Properties.Remove($name)
        }
    }

    Write-Utf8NoBom -Path $Path -Content ($report | ConvertTo-Json -Depth 100)
}

function Add-ScriptDetectedErrorsToJsonReport(
    [string]$Path,
    [bool]$HadConfigErrors,
    [int]$ConfigErrorCount,
    [bool]$HadProcessingErrors,
    [int]$ProcessingErrorCountReport,
    [int]$ProcessingErrorCountStderr,
    [bool]$HadProcessingErrorsExitCode,
    [string]$StdoutSnippet,
    [string]$StderrSnippet
) {
    # PMD's native JSON report does not always populate configurationErrors /
    # processingErrors consistently, even when stderr clearly shows them.
    # Add a top-level section with the script's diagnosis.
    if (-not (Test-Path $Path)) { return }

    try {
        $report = Get-Content $Path -Raw | ConvertFrom-Json
    }
    catch {
        return
    }

    $configSection = [pscustomobject]@{
        hadConfigErrors = $HadConfigErrors
        count           = $ConfigErrorCount
        stderrSnippet   = $StderrSnippet
    }
    $processingSection = [pscustomobject]@{
        hadProcessingErrors = $HadProcessingErrors
        countFromReport     = $ProcessingErrorCountReport
        countFromStderr     = $ProcessingErrorCountStderr
        detectedViaExitCode = $HadProcessingErrorsExitCode
        stdoutSnippet       = $StdoutSnippet
        stderrSnippet       = $StderrSnippet
    }

    if ($report.PSObject.Properties["scriptDetectedConfigurationErrors"]) {
        $report.scriptDetectedConfigurationErrors = $configSection
    }
    else {
        $report | Add-Member -NotePropertyName "scriptDetectedConfigurationErrors" -NotePropertyValue $configSection
    }

    if ($report.PSObject.Properties["scriptDetectedProcessingErrors"]) {
        $report.scriptDetectedProcessingErrors = $processingSection
    }
    else {
        $report | Add-Member -NotePropertyName "scriptDetectedProcessingErrors" -NotePropertyValue $processingSection
    }

    Write-Utf8NoBom -Path $Path -Content ($report | ConvertTo-Json -Depth 100)
}

# Validate the target upfront before passing to PMD.
if (-not (Test-Path $Target)) {
    throw "Target does not exist: $Target"
}
$item = Get-Item $Target
if ($item.PSIsContainer) {
    # A directory target must contain at least one Java file to be useful.
    $javaCount = (Get-ChildItem -Path $Target -Recurse -Filter *.java -File -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($javaCount -eq 0) {
        throw "No .java files found under target directory: $Target"
    }
}
else {
    # A file target must be a .java file.
    if ([System.IO.Path]::GetExtension($Target).ToLowerInvariant() -ne ".java") {
        throw "Target is a file but not a .java file: $Target"
    }
}


$work = New-TempDirectory
$rulesetPath = Join-Path $work "llm-rule.xml"
$stdoutPath = Join-Path $work "pmd.stdout.txt"
$stderrPath = Join-Path $work "pmd.stderr.txt"

# If OutReport is a directory, write a default filename inside it.
# If OutReport is empty, default to a report file inside the temp workspace.
$reportPath = $null

if (-not $OutReport) {
    $reportPath = Join-Path $work "report.$Format"
}
else {
    $resolvedOut = $OutReport

    # If the user passed a directory, place a file inside it
    if (Test-Path $resolvedOut -PathType Container) {
        $reportPath = Join-Path $resolvedOut ("report.{0}" -f $Format)
    }
    else {
        # If it doesn't exist yet, decide based on whether it looks like a directory path
        $endsWithSep = $resolvedOut.EndsWith("\") -or $resolvedOut.EndsWith("/")
        $hasExt = [System.IO.Path]::HasExtension($resolvedOut)

        if ($endsWithSep -or -not $hasExt) {
            New-Item -ItemType Directory -Force -Path $resolvedOut | Out-Null
            $reportPath = Join-Path $resolvedOut ("report.{0}" -f $Format)
        }
        else {
            # Treat as file path; ensure parent directory exists
            $parent = Split-Path $resolvedOut -Parent
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            $reportPath = $resolvedOut
        }
    }
}

# Generate a minimal but valid PMD 7.20.0 ruleset.
# Each run dynamically creates a ruleset containing only the user-provided XPath rule.
# This isolates the rule being tested from all other rules, ensuring clean validation.
$xml = @"
<?xml version="1.0" encoding="UTF-8"?>
<ruleset name="LLM Generated Rule" xmlns="http://pmd.sourceforge.net/ruleset/2.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://pmd.sourceforge.net/ruleset/2.0.0 https://pmd.github.io/schema/ruleset_2_0_0.xsd">

    <description>Minimal ruleset for validating a single XPath rule.</description>

    <rule name="LLMGeneratedRule" language="java" message="LLM-generated violation message" class="net.sourceforge.pmd.lang.rule.xpath.XPathRule">
        <properties>
            <property name="xpath">
                <value><![CDATA[$XPath]]></value>
            </property>
        </properties>
    </rule>
</ruleset>
"@

# Write the generated ruleset XML to disk without Byte Order Mark (BOM).
Write-Utf8NoBom -Path $rulesetPath -Content $xml

# Build PMD CLI arguments for a single check run.
# The --no-cache flag is included to make sure no files are skipped due to PMD's caching.
$pmdArgs = @(
    "check",
    "-d", $Target,
    "-R", $rulesetPath,
    "-f", $Format,
    "-r", $reportPath,
    "--no-cache"
)

# Wraps each argument in quotes to handle spaces and special characters, then constructs the full command line.
$quotedArgs = ($pmdArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
$cmdLine = '"' + $PmdBin + '" ' + $quotedArgs + ' 1>"' + $stdoutPath + '" 2>"' + $stderrPath + '"'

# Execution via cmd.exe
& $env:ComSpec /c $cmdLine
# After execution, PMD's exit code indicates the overall result
$exitCode = $LASTEXITCODE

# Normalize JSON report payload to remove per-violation priority metadata.
if ($Format -eq "json") {
    Remove-ViolationPriorityFromJsonReport -Path $reportPath
    Remove-UnhelpfulPmdJsonFields -Path $reportPath
}

# Load captured stdout and stderr for post-analysis.
# PMD produces both a structured JSON report and a log output to stderr.
# Some errors (like parser stack traces) appear only in stderr, not in the JSON report.
# We parse both to detect configuration errors (invalid XPath) and processing errors (parse failures).
$stdout = Read-FileOrEmpty $stdoutPath
$stderr = Read-FileOrEmpty $stderrPath

# Set safe defaults for error counts and flags in case the JSON report is missing or malformed.
$violationCount = $null
$hadConfigErrors = $false
$hadProcErrors = $false
$configErrorCount = 0
$processingErrorCountReport = 0
$processingErrorCountStderr = 0
$syntacticValid = $false

if ($Format -eq "json" -and (Test-Path $reportPath)) {
    try {
        # Reads the entire PMD JSON file and converts it into a PowerShell object.
        $j = Get-Content $reportPath -Raw | ConvertFrom-Json

        # Count the total number of violations across all files.
        $count = 0
        foreach ($f in @($j.files)) {
            if ($null -ne $f.violations) { $count += @($f.violations).Count }
        }
        $violationCount = $count

        # Count configuration errors and processing errors from the JSON report.
        $configErrorCount = (@($j.configurationErrors)).Count
        $processingErrorCountReport = (@($j.processingErrors)).Count
        # Flags indicating whether configuration errors or processing errors were present according to the JSON report.
        $hadConfigErrors = $configErrorCount -gt 0
        $hadProcErrors = $processingErrorCountReport -gt 0
    }
    catch {
        # If the JSON report is unreadable or malformed, use safe default values.
        # If PMD crashes before writing the report, we have no JSON data.
        # Rather than stopping, we fall back to examining stderr for error patterns.
        # By keeping defaults, we allow error detection to continue via preferred signals (exit code, stderr patterns).
        $violationCount = $null
        $hadConfigErrors = $false
        $hadProcErrors = $false
        $configErrorCount = 0
        $processingErrorCountReport = 0
    }
}

# PMD's JSON report is not always complete; it may omit certain error details.

# Signal 1: PMD exit code 5 indicates processing errors.
# Exit code 5 means PMD encountered files it couldn't parse (e.g., target Java files with syntax errors).
# Does not necessarily mean the rule is invalid, but it does mean the analysis was incomplete and some violations may have been missed.
$hadProcErrorsExitCode = $false
if ($exitCode -eq 5) {
    $hadProcErrorsExitCode = $true
}

# Signal 2: Count "Parsing failed" occurrences in stderr as an additional signal of processing errors.
$processingErrorCountStderr = 0
if ($stderr) {
    $processingErrorCountStderr = ([regex]::Matches($stderr, "\[ERROR\]\s+Parsing failed")).Count
}

# Derive "hadProcessingErrors" once from all available signals.
$hadProcErrors = ($processingErrorCountReport -gt 0) -or ($processingErrorCountStderr -gt 0) -or $hadProcErrorsExitCode


# Configuration errors (invalid XPath syntax, unknown functions, malformed XML) prevent the rule from being compiled by PMD.
# We search stderr first (where most errors appear) then stdout as a fallback.

# Common error patterns indicating configuration issues with the rule.
$configErrorPattern = @(
    "Configuration error",
    "Error \(XML parsing\)",
    "Cannot compile",
    "Unknown function",
    "Unknown namespace",
    "XPath.*(error|compile|parse)",
    "SAXParseException",
    "Exception while initializing rule"
) -join "|"

# Signal 3: Detect configuration/compilation errors in stderr and stdout.
$hasConfigErrorText = ($stderr -match $configErrorPattern) -or ($stdout -match $configErrorPattern)

# Make hadConfigErrors reflect BOTH JSON report + stderr evidence
$hadConfigErrors = $hadConfigErrors -or $hasConfigErrorText
if ($hasConfigErrorText -and $configErrorCount -eq 0) {
    # optional: expose that the count came from stderr, not the report
    $configErrorCount = 1
}

# Determine syntactic validity of the rule configuration.
# We distinguish between a rule being valid (well-formed XPath, proper XML) and the analysis being complete (target files parsed successfully).
# A rule can be syntactically valid even if processing errors prevent full analysis.
$syntacticValid = -not ($hadConfigErrors -or $hasConfigErrorText)

# Final status: summarizes whether the rule passed validation.
# "valid" means the rule is syntactically correct and can be used.
# "invalid" means the rule itself has configuration or compilation issues.
$status = if ($syntacticValid) { "valid" } else { "invalid" }

if ($Format -eq "json") {
    Add-ScriptDetectedErrorsToJsonReport `
        -Path $reportPath `
        -HadConfigErrors $hadConfigErrors `
        -ConfigErrorCount $configErrorCount `
        -HadProcessingErrors $hadProcErrors `
        -ProcessingErrorCountReport $processingErrorCountReport `
        -ProcessingErrorCountStderr $processingErrorCountStderr `
        -HadProcessingErrorsExitCode $hadProcErrorsExitCode `
        -StdoutSnippet (Snip $stdout 1200) `
        -StderrSnippet (Snip $stderr 1200)
}

[ordered]@{
    status                     = $status
    syntacticValid             = $syntacticValid
    exitCode                   = $exitCode
    violationCount             = $violationCount
    hadConfigErrors            = $hadConfigErrors
    configErrorCount           = $configErrorCount
    hadProcessingErrors        = $hadProcErrors
    processingErrorCountReport = $processingErrorCountReport
    processingErrorCountStderr = $processingErrorCountStderr
    rulesetPath                = $rulesetPath
    reportPath                 = $reportPath
    stdoutPath                 = $stdoutPath
    stderrPath                 = $stderrPath
    stdoutSnippet              = (Snip $stdout 1200)
    stderrSnippet              = (Snip $stderr 1200)
} | ConvertTo-Json -Depth 10

