$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Output = Join-Path $Root 'dist\DesktopPortal.exe'

# A running copy locks the file, so the build would fail after a long wait.
$Running = Get-Process DesktopPortal -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $Output }
if ($Running) {
    throw "Quit the running $Output first (More > Quit DesktopPortal)."
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'DesktopPortal.spec')
if ($LASTEXITCODE) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

# The release is this one file. It ships without packs or data, so users start
# from defaults and personal assets are never redistributed.
Write-Host "Built: $Output"
