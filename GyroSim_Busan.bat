@echo off
rem GyroSim - one step: Busan (Gimhae RKPK 36L) free flight over the V-World photo, with the Busan minimap (top right).
rem 1) starts the sim server (JSBSim + V-World tile proxy) in a minimized window, unless one is already running
rem 2) opens the Unreal project; Play starts by itself (-GyroSimPlay, window maximized). F11 = full screen, Esc = stop.
rem Needs unreal\GyroSim\Config\cesium_token.txt with a 'vworld' line (this PC has it) and the tiles in C:\GyroSimTiles.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "UE=C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"

netstat -ano | findstr /R /C:"127.0.0.1:8781 .*LISTENING" >nul
if %errorlevel%==0 (
    echo [GyroSim] 시뮬 서버가 이미 켜져 있습니다. 부산이 아니라 청주에서 시작되면 그 서버 창을 닫고 이 파일을 다시 실행하세요.
) else (
    echo [GyroSim] 시뮬 서버 시작 - 부산 김해 36L
    start "GyroSim server (Busan)" /min /D "%ROOT%" cmd /k python sim\server.py --start rkpk
    timeout /t 3 /nobreak >nul
)

if not exist "%UE%" (
    echo [GyroSim] 언리얼 5.8 이 없습니다: %UE%
    pause
    exit /b 1
)
echo [GyroSim] 언리얼 여는 중 - 조금 기다리면 Play 가 저절로 시작됩니다.
start "" "%UE%" "%ROOT%\unreal\GyroSim\GyroSim.uproject" /Game/Maps/FlightMap -GyroSimPlay -nosplash
endlocal
