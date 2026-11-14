@echo off
rem GyroSim - look at the cockpit v2 in Unreal (no flight, no city): /Game/Maps/CockpitView, editor camera at the pilot eye.
rem Built by unreal\GyroSim\Scripts\cockpit_view_build.py; opened with Scripts\cockpit_view_open.py (Game View, sim look settings,
rem t.MaxFPS 30, r.ScreenPercentage 75). Move: hold the right mouse button + W A S D / Q E, mouse wheel while holding = speed.
rem The canopy look is applied in memory: when closing, do NOT save the level.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "UE=C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
set "PYF=%ROOT:\=/%/unreal/GyroSim/Scripts/cockpit_view_open.py"
start "" "%UE%" "%ROOT%\unreal\GyroSim\GyroSim.uproject" /Game/Maps/CockpitView -nosplash -ExecCmds="py %PYF%"
endlocal
