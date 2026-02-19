$catalog = Get-Content ".\config\pmd-catalog.json" -Raw | ConvertFrom-Json
$testFile = "C:\Users\vidar\repo\java-classes\TestExample.java"
$pmdBin = "C:\Users\vidar\tools\pmd-bin-7.20.0\bin\pmd.bat"

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