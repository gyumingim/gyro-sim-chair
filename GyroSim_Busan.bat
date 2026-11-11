@echo off
rem GyroSim - one step: Busan (Gimhae RKPK 36L) over the V-World photo, with the Busan minimap (top right).
rem Free flight (server --free-flight): no start menu / lessons / instructor. Every Play first shows the Busan start picker
rem (sim/start_spots.py: 13 spots, a point clicked on the map, altitude / heading, random, last choice remembered); the plane
rem waits until you press Enter / click 출발. F1 menu -> '출발 위치 고르기' picks a new spot mid-flight.
rem 1) starts the sim server (JSBSim + V-World tile proxy) in a minimized window, unless one is already running
rem 2) opens the Unreal project; Play starts by itself (-GyroSimPlay) in full screen (Content/Python/pie_fullscreen.py).
rem    F11 (or Alt+Enter) = full screen on / off, Esc = stop.
rem Needs unreal\GyroSim\Config\cesium_token.txt with a 'vworld' line (this PC has it) and the tiles in C:\GyroSimTiles.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "UE=C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"

netstat -ano | findstr /R /C:"127.0.0.1:8781 .*LISTENING" >nul
if %errorlevel%==0 (
    echo [GyroSim] 시뮬 서버가 이미 켜져 있습니다. 청주에서 시작하거나 메뉴가 먼저 나오면 그 서버 창을 닫고 이 파일을 다시 실행하세요.
) else (
    echo [GyroSim] 시뮬 서버 시작 - 부산, 출발 위치를 고른 뒤 자유 비행
    start "GyroSim server (Busan)" /min /D "%ROOT%" cmd /k python sim\server.py --start rkpk --free-flight
    timeout /t 3 /nobreak >nul
)

rem 3) live look sliders (sim/tune_server.py, 127.0.0.1:8768, page http://127.0.0.1:8767/today/busan_tune/): hidden, once
netstat -ano | findstr /R /C:"127.0.0.1:8768 .*LISTENING" >nul
if not %errorlevel%==0 (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath python -ArgumentList '-I','%ROOT%\sim\tune_server.py' -WindowStyle Hidden"
)

if not exist "%UE%" (
    echo [GyroSim] 언리얼 5.8 이 없습니다: %UE%
    pause
    exit /b 1
)
echo [GyroSim] 언리얼 여는 중 - 조금 기다리면 Play 가 저절로 시작됩니다.
start "" "%UE%" "%ROOT%\unreal\GyroSim\GyroSim.uproject" /Game/Maps/FlightMap -GyroSimPlay -nosplash
endlocal
