#!/bin/sh
# Avoid xvfb-run's signal handshake under Docker Desktop x86 emulation.
set -eu
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null || true' EXIT
export DISPLAY=:99
attempt=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
  kill -0 "$xvfb_pid"
  attempt=$((attempt + 1))
  [ "$attempt" -lt 100 ] || exit 1
  sleep 0.1
done
"$@"
