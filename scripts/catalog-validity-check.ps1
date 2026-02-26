# This script validates the syntactical validity of XPath expressions from the official PMD catalog by running them against a single test file, returning a csv summary of the results.
# It does not attempt to run the rules on a full codebase or interpret the results beyond basic error detection.
# For a more comprehensive validation that runs the rules on a full codebase and collects detailed results, use run-catalog-on-target.ps1 instead.

$catalog = Get-Content ".\config\pmd-catalog.json" -Raw | ConvertFrom-Json
$testFile = "path\to\test\file\Example.java"  # Change to an actual Java file for testing
$pmdBin = "path\to\pmd.bat"  # Change to the actual path of your PMD binary

$results = @()

foreach ($prop in $catalog.rules.PSObject.Properties) {

    $r = $prop.Value  # rule object

    if (-not $r.xpath -or $r.xpath.Trim() -eq "") {
        Write-Host "Skipping empty XPath: $($r.id)"
        continue
    }

    Write-Host "Testing rule:" $r.id

    $resJson = & .\scripts\pmd-xpath-check.ps1 `
        -PmdBin $pmdBin `
        -Target $testFile `
        -XPath $r.xpath

    if (-not $resJson) {
        Write-Host "No output for $($r.id)"
        continue
    }

    $res = $resJson | ConvertFrom-Json

    $results += [pscustomobject]@{
        rule_id  = $r.id
        status   = $res.status
        exitCode = $res.exitCode
        stderr   = $res.stderrSnippet
    }
}

Write-Host "Total results:" $results.Count

$results | Export-Csv -NoTypeInformation ".\executed-pmd-rules.csv"