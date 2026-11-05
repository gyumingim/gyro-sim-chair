# Removes the optional scheduled task made by sim/vworld_fill_task_install.ps1 and asks a running fill to stop.
#
#   powershell -ExecutionPolicy Bypass -File sim\vworld_fill_task_remove.ps1
#
# The cache (C:\GyroSimTiles\vworld) and the fill state/log are kept.
$TaskName = "GyroSim VWorld Busan fill"
$t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($t) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "removed: $TaskName"
} else {
    Write-Output "no task named $TaskName"
}
$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if ($py) { & $py (Join-Path $PSScriptRoot "vworld_fill.py") --stop }
