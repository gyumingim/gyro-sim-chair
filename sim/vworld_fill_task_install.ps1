# OPTIONAL - registers a hidden Windows scheduled task that runs the Busan V-World fill (sim/vworld_fill.py) every day.
# Written for the user to run by hand; nothing runs it automatically. Remove again: sim/vworld_fill_task_remove.ps1
#
#   powershell -ExecutionPolicy Bypass -File sim\vworld_fill_task_install.ps1
#
# What it makes (current user, only while logged on, no password stored, no admin needed):
#   task  "GyroSim VWorld Busan fill"
#   runs  pythonw.exe sim\vworld_fill.py --run-until-budget   (pythonw = no console window; output only in
#         C:\GyroSimTiles\vworld\fill_busan.log)
#   when  every day 03:00, then again every hour until 02:00 next day (each start exits at once when today's plan is
#         used, the server stopped the key for the day, another fill is running, or the flight proxy is up);
#         a missed start runs when the PC is next on. One instance at a time; one run at most 23 h.
$ErrorActionPreference = "Stop"
$TaskName = "GyroSim VWorld Busan fill"
$Script = Join-Path $PSScriptRoot "vworld_fill.py"
$Pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $Pyw) { throw "pythonw.exe not found on PATH" }
if (-not (Test-Path $Script)) { throw "missing $Script" }

$action = New-ScheduledTaskAction -Execute $Pyw -Argument "`"$Script`" --run-until-budget" -WorkingDirectory $env:TEMP
$trigger = New-ScheduledTaskTrigger -Daily -At 03:00
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 03:00 -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 23)).Repetition
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 23) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "V-World Busan z19 cache fill (sim/vworld_fill.py). Remove: sim/vworld_fill_task_remove.ps1" | Out-Null
Write-Output "registered: $TaskName  ($Pyw `"$Script`" --run-until-budget)"
Write-Output "check: python sim\vworld_fill.py --status   stop now: python sim\vworld_fill.py --stop"
