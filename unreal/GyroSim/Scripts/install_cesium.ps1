# Installs the prebuilt Cesium for Unreal plugin (UE 5.8 build) into this project's Plugins folder.
# The plugin (~1.3 GB zip, ~4 GB unpacked) is not in git (.gitignore); run this once per checkout:
#   powershell -ExecutionPolicy Bypass -File unreal\GyroSim\Scripts\install_cesium.ps1
# Optional: -Version v2.31.0  (default = the version below, the one this project was tested with)
param([string]$Version = "v2.31.0")
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot                       # unreal\GyroSim
$plugins = Join-Path $proj "Plugins"
$dest = Join-Path $plugins "CesiumForUnreal"
if (Test-Path (Join-Path $dest "CesiumForUnreal.uplugin")) {
    Write-Host "Cesium for Unreal already installed: $dest"
    exit 0
}
$name = "CesiumForUnreal-58-$Version.zip"
$url = "https://github.com/CesiumGS/cesium-unreal/releases/download/$Version/$name"
$tmp = Join-Path $env:TEMP "gyrosim_cesium"
New-Item -ItemType Directory -Force $tmp | Out-Null
$zip = Join-Path $tmp $name
if (-not (Test-Path $zip)) {
    Write-Host "Downloading $url (about 1.3 GB) ..."
    & curl.exe -L --fail --retry 3 -o "$zip.part" $url
    if ($LASTEXITCODE -ne 0) { throw "download failed" }
    Move-Item -Force "$zip.part" $zip
}
Write-Host "Extracting ..."
$ex = Join-Path $tmp "extract"
if (Test-Path $ex) { Remove-Item -Recurse -Force $ex }
New-Item -ItemType Directory -Force $ex | Out-Null
& tar.exe -xf $zip -C $ex
if ($LASTEXITCODE -ne 0) { throw "extract failed" }
$up = Get-ChildItem -Path $ex -Recurse -Filter "CesiumForUnreal.uplugin" | Select-Object -First 1
if (-not $up) { throw "CesiumForUnreal.uplugin not found in the zip" }
New-Item -ItemType Directory -Force $plugins | Out-Null
Move-Item -Force $up.Directory.FullName $dest
Remove-Item -Recurse -Force $ex
Write-Host "Installed: $dest"
Write-Host "(zip kept in $tmp - delete it to free 1.3 GB)"
