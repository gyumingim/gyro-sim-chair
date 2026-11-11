#!/usr/bin/env bash
# Offscreen UE shots + GPU ms + triangles for the impostor trees (Scripts/trees_near_shots.py states), holding the lock.
#   bash sim/impostor/ue_shots.sh [states] [out dir]      e.g.  none,blob,imp  C:/GyroSimTiles/shots/trees_imp
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd -W)"
OUTD="${2:-C:/GyroSimTiles/shots/trees_imp}"
mkdir -p "$OUTD"
LOG="$OUTD/ue.log"
export GYROSIM_TREES_NEAR_SHOTS=1 GYROSIM_TSHOT_LOG="$LOG" GYROSIM_SHOTS_DIR="$OUTD"
export GYROSIM_TNS_STATES="${1:-none,blob,imp}" GYROSIM_TNS_VIEWS="${GYROSIM_TNS_VIEWS:-hwang_low,park_low,jang_mid}"
export GYROSIM_TNS_GPU="${GYROSIM_TNS_GPU:-hwang_low,park_low,jang_mid}" GYROSIM_TNS_SHOT_ALL="${GYROSIM_TNS_SHOT_ALL:-blob,imp}"
if powershell -NoProfile -c "if (Get-Process UnrealEditor -ErrorAction SilentlyContinue) { exit 1 }"; then :; else
  echo "an UnrealEditor is running - not starting (user's editor or another offscreen run)"; exit 2; fi
powershell -NoProfile -File "$REPO/sim/impostor/run_locked.ps1" -exe "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" \
  -argstr "$REPO/unreal/GyroSim/GyroSim.uproject /Game/Maps/FlightMap -GyroSimTreeShots -RenderOffscreen -nosplash -nosound -unattended -ABSLOG=$LOG" \
  -log "$OUTD/ue_stdout.log"
echo "exit $?"
