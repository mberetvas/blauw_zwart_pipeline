#!/bin/sh
set -u

# Force unbuffered Python/dbt output so logs reach Docker stdout immediately.
export PYTHONUNBUFFERED=1

interval_minutes="${DBT_RUN_INTERVAL_MINUTES:-}"
if [ -z "$interval_minutes" ]; then
  interval_minutes=5
  echo "[dbt-scheduler] WARNING: DBT_RUN_INTERVAL_MINUTES not set; using default: ${interval_minutes}m" >&2
fi
selector="${DBT_RUN_SELECTOR:-+mart_fan_loyalty +mart_player_season_summary}"
# When 1 (default), the container exits non-zero on dbt build failure so Docker's
# restart policy surfaces the issue. Set to 0 to keep the legacy log-and-continue behavior.
fail_fast="${DBT_FAIL_FAST:-1}"

case "$interval_minutes" in
  *[!0-9]*)
    echo "[dbt-scheduler] DBT_RUN_INTERVAL_MINUTES must be a positive integer, got: '$interval_minutes'" >&2
    exit 2
    ;;
esac

if [ "$interval_minutes" -le 0 ]; then
  echo "[dbt-scheduler] DBT_RUN_INTERVAL_MINUTES must be greater than zero, got: $interval_minutes" >&2
  exit 2
fi

interval_seconds=$((interval_minutes * 60))

echo "[dbt-scheduler] starting: selector=$selector interval=${interval_minutes}m fail_fast=${fail_fast}"

while true
do
  echo "[dbt-scheduler] $(date -Iseconds) running dbt build"
  # `dbt build` runs models, snapshots, seeds and tests in DAG order, so a failing
  # test on a parent model stops downstream models from running with bad data.
  # --fail-fast makes dbt stop at the first failure within this invocation.
  # Intentionally unquoted to allow multi-selector values, e.g.
  # "+mart_fan_loyalty +mart_player_season_summary".
  # shellcheck disable=SC2086
  if dbt build --project-dir /app --profiles-dir /app/dbt --fail-fast --select $selector; then
    echo "[dbt-scheduler] $(date -Iseconds) dbt build succeeded"
  else
    status=$?
    echo "[dbt-scheduler] $(date -Iseconds) dbt build failed with exit code $status" >&2
    if [ "$fail_fast" = "1" ]; then
      echo "[dbt-scheduler] DBT_FAIL_FAST=1 -> exiting so the container restart policy can react" >&2
      exit "$status"
    fi
  fi
  echo "[dbt-scheduler] sleeping ${interval_minutes} minute(s)"
  sleep "$interval_seconds"
done
