#!/usr/bin/env bash
# Offscreen landmark shots (Scripts/landmarks_shots.py) with the shared lock C:/GyroSimTiles/ue_offscreen.lock:
# only ONE offscreen UnrealEditor at a time. Lock convention for all holders: sim/power_rule.py docstring. Waits (1 min
# steps) while the holder named in the token (pid<N>, started before the token was written) is alive, or the lock is fresh
# (< 2 min with no UnrealEditor alive, < 30 min otherwise); takes a stale lock over. Deletes the temporary map copy and
# the lock (only if it still holds our token) when UE exits.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK=/c/GyroSimTiles/ue_offscreen.lock
UE="/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe"
LOG=/c/GyroSimTiles/shots/landmarks/ue_landmarks.log
mkdir -p /c/GyroSimTiles/shots/landmarks
TOKEN="landmarks_shots pid$(cat /proc/$$/winpid 2>/dev/null || echo $$) $(date +%Y-%m-%dT%H:%M:%S) $(date +%s%N)-$RANDOM$RANDOM"
holder_live() {          # the token's pid exists AND started no later than the token was written (not a reused pid)
  local hpid htime pstart
  hpid=$(head -1 "$LOCK" 2>/dev/null | grep -o -m1 'pid[0-9][0-9]*' | head -1 | cut -c4-)
  htime=$(head -1 "$LOCK" 2>/dev/null | awk '{print $3}')
  [ -n "$hpid" ] && [ -n "$htime" ] || return 1
  pstart=$(powershell -NoProfile -Command "\$p = Get-CimInstance Win32_Process -Filter 'ProcessId=$hpid'; if (\$p) { \$p.CreationDate.ToString('s') }" 2>/dev/null | tr -d '\r')
  [ -n "$pstart" ] && [[ ! "$pstart" > "$htime" ]]
}
waited=0
while true; do
  if ( set -o noclobber; echo "$TOKEN" > "$LOCK" ) 2>/dev/null; then break; fi
  age=$(( $(date +%s) - $(stat -c %Y "$LOCK") ))
  alive=$(tasklist 2>/dev/null | grep -c -i "^UnrealEditor")      # UnrealEditor.exe and UnrealEditor-Cmd.exe (commandlets hold the lock too)
  if holder_live; then
    echo "$(date +%T) lock held by a live holder: $(head -1 "$LOCK") (${age}s) - waiting"
  elif [ "$age" -gt 1800 ] || { [ "$alive" -eq 0 ] && [ "$age" -gt 120 ]; }; then     # 2 min grace: holders run several UE in a row
    echo "stale lock ($(cat "$LOCK"), ${age}s, UE alive $alive) - taking over"; rm -f "$LOCK"; continue
  else
    echo "$(date +%T) lock held: $(cat "$LOCK") (${age}s) - waiting"
  fi
  if [ "$waited" -ge 5 ]; then
    echo "  hint: waiting ${waited} min - the lock may be a leftover (power cut / killed job). If no heavy job runs, delete $LOCK by hand."
  fi
  waited=$((waited + 1)); sleep 60
done
trap '[ "$(head -1 "$LOCK" 2>/dev/null | tr -d "\r")" = "$TOKEN" ] && rm -f "$LOCK"' EXIT     # only our own lock
export GYROSIM_LSHOT_LOG="$(cygpath -w "$LOG")"
mkdir -p "$REPO/unreal/GyroSim/Content/Maps/_tmp"
cp "$REPO/unreal/GyroSim/Content/Maps/FlightMap.umap" "$REPO/unreal/GyroSim/Content/Maps/_tmp/FlightMap_lmtest.umap"
MSYS2_ARG_CONV_EXCL="*" MSYS_NO_PATHCONV=1 "$UE" "$(cygpath -w "$REPO/unreal/GyroSim/GyroSim.uproject")" /Game/Maps/_tmp/FlightMap_lmtest -GyroSimLandmarkShots -RenderOffscreen -nosplash -unattended \
      -ABSLOG="$GYROSIM_LSHOT_LOG"
echo "UE exit $?"
rm -rf "$REPO/unreal/GyroSim/Content/Maps/_tmp"          # the temporary map copy (never in git)
grep -E "\[lshots\]|\[landmarks\]" "$LOG" | tail -60
