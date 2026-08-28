param(
    [Parameter(Mandatory = $false)]
    [string]$StepFile,
    [string]$Output = ".\acceptance_output",
    [switch]$ReuseCache
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python -m unittest -v
    if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }

    if ($StepFile) {
        $arguments = @(".\step_geometry_encoder.py", $StepFile, "--output", $Output)
        if ($ReuseCache) { $arguments += "--reuse-cache" }
        python @arguments
        if ($LASTEXITCODE -ne 0) { throw "STEP acceptance workflow failed." }

        $manifestPath = Join-Path $Output "workflow_manifest.json"
        $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.status -ne "completed") { throw "Workflow manifest is not completed." }
        $failedGates = @($manifest.quality_gates | Where-Object { -not $_.passed })
        if ($failedGates.Count -gt 0) { throw "One or more quality gates failed." }
    }
}
finally {
    Pop-Location
}
