param(
    [string]$BuildDirectory = ".\build\cpp-ninja",
    [string]$BaselineReport,
    [string]$NormalizedDirectory,
    [string]$StepFile,
    [string]$Output = ".\cpp_acceptance_output"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $fastBuildDirectory = Join-Path (Split-Path -Parent $BuildDirectory) "fast-standalone"
    cmake -S .\cpp\fast -B $fastBuildDirectory -G Ninja -DCMAKE_BUILD_TYPE=Release
    if ($LASTEXITCODE -ne 0) { throw "Standalone fast library configure failed." }
    cmake --build $fastBuildDirectory --config Release
    if ($LASTEXITCODE -ne 0) { throw "Standalone fast library build failed." }
    ctest --test-dir $fastBuildDirectory --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "Standalone fast library tests failed." }

    $memoryBuildDirectory = Join-Path (Split-Path -Parent $BuildDirectory) "occt-fast-standalone"
    cmake -S .\cpp\occt_fast -B $memoryBuildDirectory -G Ninja -DCMAKE_BUILD_TYPE=Release
    if ($LASTEXITCODE -ne 0) { throw "Standalone memory adapter configure failed." }
    cmake --build $memoryBuildDirectory --config Release
    if ($LASTEXITCODE -ne 0) { throw "Standalone memory adapter build failed." }
    ctest --test-dir $memoryBuildDirectory --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "Standalone memory adapter tests failed." }

    cmake -S . -B $BuildDirectory -G Ninja -DCMAKE_BUILD_TYPE=Release
    if ($LASTEXITCODE -ne 0) { throw "C++ configure failed." }
    cmake --build $BuildDirectory --config Release
    if ($LASTEXITCODE -ne 0) { throw "C++ build failed." }
    ctest --test-dir $BuildDirectory --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "C++ and cross-language parity tests failed." }

    $executable = Join-Path $BuildDirectory "mbd_geometry_cli.exe"
    if ([bool]$BaselineReport -ne [bool]$NormalizedDirectory) {
        throw "BaselineReport and NormalizedDirectory must be supplied together."
    }
    if ($BaselineReport) {
        & $executable parity-report $BaselineReport $NormalizedDirectory
        if ($LASTEXITCODE -ne 0) { throw "Saved Python/C++ partition parity failed." }
    }
    if ($StepFile) {
        & $executable run $StepFile $Output rigid
        if ($LASTEXITCODE -ne 0) { throw "Native C++ STEP workflow failed." }
        if ($BaselineReport) {
            $memoryParity = Join-Path $BuildDirectory "mbd_memory_parity.exe"
            python .\scripts\check_memory_report.py $memoryParity $StepFile $BaselineReport
            if ($LASTEXITCODE -ne 0) { throw "Pure-memory/Python acceptance failed." }
        }
    }
}
finally {
    Pop-Location
}
