$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'Create .venv with Python 3.10+ and install the build extra first. See README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    $buildManifest = Join-Path $projectRoot 'packaging\pokato.manifest'
    & $buildPython -m PyInstaller --noconfirm --onefile --windowed --noupx --name Pokato --icon NONE --paths src --manifest $buildManifest --specpath build scripts/launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    $builtExecutable = Join-Path $projectRoot 'dist\Pokato.exe'
    if (-not (Test-Path -LiteralPath $builtExecutable)) { throw 'Build did not produce Pokato.exe.' }
    Get-Item -LiteralPath $builtExecutable | Select-Object FullName, Length
    Get-FileHash -LiteralPath $builtExecutable -Algorithm SHA256 | Format-List Algorithm, Hash, Path
}
finally {
    Pop-Location
}
