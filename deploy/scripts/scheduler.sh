#!/bin/sh
# Periodic jobs (ADR 0003): sweep & email outbox every minute, DSR every 10 minutes, image/export retention every hour.
# Writes /tmp/scheduler.beat ONLY when all jobs in the tick succeed within timeout.
set -u
trap "exit 0" TERM INT
i=0
while :; do
  ok=1
  if ! timeout 50 tastoria jobs sweep; then
    echo "scheduler: sweep failed (exit $?)" >&2
    ok=0
  fi
  if ! timeout 50 tastoria jobs drain-outbox; then
    echo "scheduler: drain-outbox failed (exit $?)" >&2
    ok=0
  fi
  if [ $((i % 10)) -eq 0 ]; then
    if ! timeout 240 tastoria jobs process-dsr; then
      echo "scheduler: process-dsr failed (exit $?)" >&2
      ok=0
    fi
  fi
  if [ $((i % 60)) -eq 0 ]; then
    if ! timeout 240 tastoria jobs purge-images; then
      echo "scheduler: purge-images failed (exit $?)" >&2
      ok=0
    fi
    if ! timeout 120 tastoria jobs purge-exports; then
      echo "scheduler: purge-exports failed (exit $?)" >&2
      ok=0
    fi
  fi
  [ "$ok" = 1 ] && date +%s > /tmp/scheduler.beat
  i=$((i + 1))
  sleep 60 &
  wait $!
done
