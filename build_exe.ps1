$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $buildPython)) { $buildPython = 'python' }
    & $buildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies.' }
    & $buildPython -m PyInstaller --noconfirm PlanePlane.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Output (Join-Path $PSScriptRoot 'dist\PlanePlane.exe')
} finally {
    Pop-Location
}
