# Persistent offscreen render server for the slider page (docs/grounded-day-busan.md 'sliders'): one hidden offscreen editor
# (art_shots.py GYROSIM_ART_SERVE=1) that idles at t.MaxFPS 1 and renders a view of tune_views.json with the live values of
# C:\GyroSimTiles\tune\params.json when sim/tune_server.py asks (~4 s per shot once the view is loaded). Quits after
# -idle minutes without a request. Power rule: holds C:\GyroSimTiles\ue_offscreen.lock for its whole life (token
# 'tune_serve ...'; created atomically, never taken from someone else, removed only if still ours) - no other offscreen
# editor or heavy CPU job may run meanwhile.
#   powershell -NoProfile -WindowStyle Hidden -File unreal\GyroSim\Scripts\tune_serve.ps1 [-idle 15]
param([int]$idle = 15)
$lock = "C:\GyroSimTiles\ue_offscreen.lock"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = Join-Path (Split-Path -Parent $here) "GyroSim.uproject"
$logf = "C:\GyroSimTiles\tune\ue_serve.log"
$token = "tune_serve pid" + $PID + " " + (Get-Date -Format s) + " " + [guid]::NewGuid().ToString()
$held = $false
function OtherUE { Get-CimInstance Win32_Process | ? { ($_.Name -eq 'UnrealEditor.exe' -and $_.CommandLine -match 'RenderOffscreen|nullrhi') -or $_.Name -eq 'UnrealEditor-Cmd.exe' } }
try {
  New-Item -ItemType Directory -Force "C:\GyroSimTiles\tune" | Out-Null
  if (OtherUE) { "another offscreen editor is running - not starting"; exit 2 }
  try { $fs = [System.IO.File]::Open($lock, 'CreateNew', 'Write'); $w = New-Object System.IO.StreamWriter($fs); $w.WriteLine($token); $w.Close(); $held = $true } catch { "lock busy: " + (Get-Content $lock -ErrorAction SilentlyContinue); exit 3 }
  Remove-Item "C:\GyroSimTiles\tune\render_req.json" -ErrorAction SilentlyContinue
  $env:GYROSIM_ART_VIEWS = Join-Path $here "tune_views.json"
  $env:GYROSIM_ART_SERVE = "1"; $env:GYROSIM_TUNE = "1"; $env:GYROSIM_ART_IDLE_MIN = "$idle"
  $env:GYROSIM_ART_TAG = "serve"; $env:GYROSIM_SHOTS_DIR = "C:\GyroSimTiles\tune\shots"; $env:GYROSIM_ART_LOG = $logf
  $env:GYROSIM_GROUND = "vworld"
  $p = Start-Process -FilePath "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" -ArgumentList @(('"' + $proj + '"'), '/Game/Maps/FlightMap', '-GyroSimArtShots', '-RenderOffscreen', '-nosplash', '-unattended', '-nosound', ('-ABSLOG="' + $logf + '"')) -WindowStyle Hidden -PassThru
  $p.WaitForExit((($idle + 60) * 60) * 1000) | Out-Null
  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
} finally {
  if ($held -and ((Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1) -eq $token)) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
}
