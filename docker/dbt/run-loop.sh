#!/bin/sh
set -u

interval_minutes="${DBT_RUN_INTERVAL_MINUTES:-}"
if [ -z "$interval_minutes" ]; then
  interval_minutes=5
  echo "[dbt-scheduler] WARNING: DBT_RUN_INTERVAL_MINUTES not set; using default: ${interval_minutes}m" >&2
fi
selector="${DBT_RUN_SELECTOR:-+mart_fan_loyalty +mart_player_season_summary}"

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

echo "[dbt-scheduler] starting: selector=$selector interval=${interval_minutes}m"

while true
do
  echo "[dbt-scheduler] $(date -Iseconds) running dbt"
  # Intentionally unquoted to allow multi-selector values, e.g.
  # "+mart_fan_loyalty +mart_player_season_summary".
  # shellcheck disable=SC2086
  if dbt run --project-dir /app --profiles-dir /app/dbt --select $selector; then
    echo "[dbt-scheduler] $(date -Iseconds) dbt run succeeded"
  else
    status=$?
    echo "[dbt-scheduler] $(date -Iseconds) dbt run failed with exit code $status" >&2
  fi
  echo "[dbt-scheduler] sleeping ${interval_minutes} minute(s)"
  sleep "$interval_seconds"
done
