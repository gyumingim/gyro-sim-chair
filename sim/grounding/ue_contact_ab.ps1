# Building contact (GYROSIM_BLDG_CONTACT, docs/research/building-grounding-study.md): rebuild the data + materials and shoot the
# in-game A/B with GPU times, as ONE heavy job holding C:\GyroSimTiles\ue_offscreen.lock (power rule: created atomically with
# our token, never taken from someone else, removed only if still ours; refuses to start while any offscreen editor runs).
#   powershell -NoProfile -WindowStyle Hidden -File sim\grounding\ue_contact_ab.ps1 [-steps data,mat,shots]
# data  = python -I sim/bldg_ao_build.py (A channel = signed distance to the footprint)
# mat   = ground_material.py + buildings_material.py commandlets (re-import T_GyroBldgAO, BcOn / BcDark .. parameters)
# shots = art_shots.py, hidden offscreen editor: C:\GyroSimTiles\shots\contact\{views,variants}_<tag>.json -> contact\<tag>\,
#         GPU (startfpschart) on the -gpu views
param([string]$steps = "data,mat,shots", [string]$tag = "contact", [string]$contact = "0", [string]$gpu = "n5_gwangan_500,a04_seomyeon_200,s_seomyeon_ob,g_gwangan_ob")
$lock = "C:\GyroSimTiles\ue_offscreen.lock"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$proj = Join-Path $repo "unreal\GyroSim\GyroSim.uproject"
$scr = Join-Path $repo "unreal\GyroSim\Scripts"
$out = "C:\GyroSimTiles\shots\contact"
$ue = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
$uec = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$token = "bldg_contact_ab pid" + $PID + " " + (Get-Date -Format s) + " " + [guid]::NewGuid().ToString()
$held = $false
function OtherUE { Get-CimInstance Win32_Process | ? { ($_.Name -eq 'UnrealEditor.exe' -and $_.CommandLine -match 'RenderOffscreen|nullrhi') -or $_.Name -eq 'UnrealEditor-Cmd.exe' } }
function Say($m) { $l = (Get-Date -Format "HH:mm:ss ") + $m; $l; Add-Content -Path "$out\run.log" -Value $l }
New-Item -ItemType Directory -Force $out | Out-Null
try {
  if (OtherUE) { Say "another offscreen editor is running - not starting"; exit 2 }
  try { $fs = [System.IO.File]::Open($lock, 'CreateNew', 'Write'); $w = New-Object System.IO.StreamWriter($fs); $w.WriteLine($token); $w.Close(); $held = $true } catch { Say ("lock busy: " + (Get-Content $lock -ErrorAction SilentlyContinue)); exit 3 }
  if ($steps -match "data") {
    Say "bldg_ao_build start"
    $p = Start-Process -FilePath "python" -ArgumentList @("-I", (Join-Path $repo "sim\bldg_ao_build.py")) -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$out\bldg_ao_build.log" -RedirectStandardError "$out\bldg_ao_build.err"
    Say ("bldg_ao_build exit " + $p.ExitCode); if ($p.ExitCode -ne 0) { exit 4 }
  }
  if ($steps -match "mat") {
    foreach ($s in @("ground_material.py", "buildings_material.py")) {
      Say "$s start"
      $p = Start-Process -FilePath $uec -ArgumentList @(('"' + $proj + '"'), '-run=pythonscript', ('-script="' + (Join-Path $scr $s) + '"'), '-unattended', '-nosplash', '-nullrhi', ('-ABSLOG="' + "$out\$s.log" + '"')) -WindowStyle Hidden -Wait -PassThru
      Say ("$s exit " + $p.ExitCode)
    }
  }
  if ($steps -match "shots") {
    Say "art_shots start"
    $env:GYROSIM_ART_VIEWS = "$out\views_$tag.json"; $env:GYROSIM_ART_VARIANTS = "$out\variants_$tag.json"
    $env:GYROSIM_ART_GPU = $gpu
    $env:GYROSIM_ART_LOG = "$out\ue_shots_$tag.log"; $env:GYROSIM_SHOTS_DIR = "$out\$tag"; $env:GYROSIM_ART_TAG = $tag
    $env:GYROSIM_GROUND = "vworld"; $env:GYROSIM_BLDG_CONTACT = $contact
    $p = Start-Process -FilePath $ue -ArgumentList @(('"' + $proj + '"'), '/Game/Maps/FlightMap', '-GyroSimArtShots', '-RenderOffscreen', '-nosplash', '-unattended', '-nosound', ('-ABSLOG="' + "$out\ue_shots_$tag.log" + '"')) -WindowStyle Hidden -PassThru
    $p.WaitForExit(90 * 60 * 1000) | Out-Null
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; Say "art_shots timeout - stopped" }
    Say "art_shots end"
  }
} finally {
  if ($held -and ((Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1) -eq $token)) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
}
