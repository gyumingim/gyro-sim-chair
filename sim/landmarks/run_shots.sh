#!/usr/bin/env bash
# Offscreen landmark shots (Scripts/landmarks_shots.py) with the shared lock C:/GyroSimTiles/ue_offscreen.lock:
# only ONE offscreen UnrealEditor at a time. Waits (1 min steps) while another task holds a fresh lock (< 30 min) and an
# UnrealEditor process is alive; takes a stale lock over. Deletes the temporary map copy and the lock when UE exits.
#   bash sim/landmarks/run_shots.sh            (env GYROSIM_LSHOT_* passes through to the editor)
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK=/c/GyroSimTiles/ue_offscreen.lock
UE="/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe"
LOG=/c/GyroSimTiles/shots/landmarks/ue_landmarks.log
mkdir -p /c/GyroSimTiles/shots/landmarks
while true; do
  if ( set -o noclobber; echo "landmarks_shots $(date +%Y-%m-%dT%H:%M:%S)" > "$LOCK" ) 2>/dev/null; then break; fi
  age=$(( $(date +%s) - $(stat -c %Y "$LOCK") ))
  alive=$(tasklist 2>/dev/null | grep -c -i "^UnrealEditor")      # UnrealEditor.exe and UnrealEditor-Cmd.exe (commandlets hold the lock too)
  if [ "$age" -gt 1800 ] || [ "$alive" -eq 0 ]; then
    echo "stale lock ($(cat "$LOCK"), ${age}s, UE alive $alive) - taking over"; rm -f "$LOCK"; continue
  fi
  echo "$(date +%T) lock held: $(cat "$LOCK") (${age}s) - waiting"; sleep 60
done
trap 'rm -f "$LOCK"' EXIT
export GYROSIM_LSHOT_LOG="$(cygpath -w "$LOG")"
mkdir -p "$REPO/unreal/GyroSim/Content/Maps/_tmp"
cp "$REPO/unreal/GyroSim/Content/Maps/FlightMap.umap" "$REPO/unreal/GyroSim/Content/Maps/_tmp/FlightMap_lmtest.umap"
MSYS2_ARG_CONV_EXCL="*" MSYS_NO_PATHCONV=1 "$UE" "$(cygpath -w "$REPO/unreal/GyroSim/GyroSim.uproject")" /Game/Maps/_tmp/FlightMap_lmtest -GyroSimLandmarkShots -RenderOffscreen -nosplash -unattended \
      -ABSLOG="$GYROSIM_LSHOT_LOG"
echo "UE exit $?"
rm -rf "$REPO/unreal/GyroSim/Content/Maps/_tmp"          # the temporary map copy (never in git)
grep -E "\[lshots\]|\[landmarks\]" "$LOG" | tail -60
