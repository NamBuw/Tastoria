#!/bin/sh
# Periodic jobs (ADR 0003): sweep every minute (UC34), finish open data-subject requests every 10 minutes
# (crash recovery for UC06/UC07). Each run is a fresh process; a failing run is logged and retried next tick.
# Backups run on the host (deploy/scripts/backup.sh), not here: they need docker and rclone.
set -u
trap "exit 0" TERM INT
i=0
while :; do
  date +%s > /tmp/scheduler.beat
  tastoria jobs sweep || echo "scheduler: sweep failed (exit $?)" >&2
  if [ $((i % 10)) -eq 0 ]; then
    tastoria jobs process-dsr || echo "scheduler: process-dsr failed (exit $?)" >&2
  fi
  i=$((i + 1))
  sleep 60 &
  wait $!
done
