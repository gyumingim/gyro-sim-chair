# Run one heavy job (headless Blender bake etc.) while holding C:\GyroSimTiles\ue_offscreen.lock (power rule).
# Lock created atomically with our own token, removed only if still ours. Exits 3 if the lock is busy.
#   powershell -NoProfile -File sim\impostor\run_locked.ps1 -exe <blender.exe> -argstr "-b --factory-startup -P x.py -- a b" -log <file>
param([string]$exe, [string]$argstr, [string]$log)
$lock = "C:\GyroSimTiles\ue_offscreen.lock"
$token = "impostor_bake pid" + $PID + " " + (Get-Date -Format s) + " " + [guid]::NewGuid().ToString()
try { $fs = [System.IO.File]::Open($lock, 'CreateNew', 'Write'); $w = New-Object System.IO.StreamWriter($fs); $w.WriteLine($token); $w.Close() }
catch { "lock busy: " + (Get-Content $lock -ErrorAction SilentlyContinue); exit 3 }
$code = 1
try {
  $p = Start-Process -FilePath $exe -ArgumentList $argstr -NoNewWindow -Wait -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log + ".err")
  $code = $p.ExitCode
} finally {
  $c = Get-Content $lock -ErrorAction SilentlyContinue
  if ($c -and ($c -join "") -eq $token) { Remove-Item $lock -Force }
}
exit $code
