$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Output = Join-Path $Root 'dist\DesktopPortal'

# A running copy locks its files, and PyInstaller would delete the rest of the
# folder (including that copy's packs and settings) before failing.
$Running = Get-Process DesktopPortal -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$Output\*" }
if ($Running) {
    throw "Quit the running $Output\DesktopPortal.exe first (More > Quit DesktopPortal)."
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'DesktopPortal.spec')
if ($LASTEXITCODE) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

# Releases ship without local packs or data so users start from defaults and
# personal assets are never redistributed.
New-Item (Join-Path $Output 'packs') -ItemType Directory -Force | Out-Null
New-Item (Join-Path $Output 'data') -ItemType Directory -Force | Out-Null
foreach ($Name in @('README.md', 'LICENSE')) {
    Copy-Item (Join-Path $Root $Name) (Join-Path $Output $Name) -Force
}

$Archive = Join-Path $Root 'dist\DesktopPortal-Windows.zip'
if (Test-Path $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
Compress-Archive -Path "$Output\*" -DestinationPath $Archive -CompressionLevel Optimal

Write-Host "Built: $Output\DesktopPortal.exe"
Write-Host "Archive: $Archive"
