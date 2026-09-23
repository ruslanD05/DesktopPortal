$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Output = Join-Path $Root 'dist\DesktopPortal'

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'DesktopPortal.spec')

Copy-Item (Join-Path $Root 'packs') (Join-Path $Output 'packs') -Recurse -Force
New-Item (Join-Path $Output 'data') -ItemType Directory -Force | Out-Null
foreach ($Name in @('settings.json', 'collections.json', 'tags.json')) {
    $Source = Join-Path $Root "data\$Name"
    if (Test-Path $Source) {
        Copy-Item $Source (Join-Path $Output "data\$Name") -Force
    }
}
Copy-Item (Join-Path $Root 'README.md') (Join-Path $Output 'README.md') -Force

$Archive = Join-Path $Root 'dist\DesktopPortal-Windows.zip'
if (Test-Path $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
Compress-Archive -Path "$Output\*" -DestinationPath $Archive -CompressionLevel Optimal

Write-Host "Built: $Output\DesktopPortal.exe"
Write-Host "Archive: $Archive"
