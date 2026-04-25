#!/bin/sh
set -u

# Force unbuffered Python/dbt output so logs reach Docker stdout immediately.
export PYTHONUNBUFFERED=1

interval_minutes="${DBT_RUN_INTERVAL_MINUTES:-}"
if [ -z "$interval_minutes" ]; then
  interval_minutes=5
  echo "[dbt-scheduler] WARNING: DBT_RUN_INTERVAL_MINUTES not set; using default: ${interval_minutes}m" >&2
fi
selector="${DBT_RUN_SELECTOR:-+tag:mart}"
# Optional second-pass selector. The default repo config uses this for the
# observability mart so the first build can create dbt_run_results via the
# on-run-end hook before the mart itself is rebuilt on top of that table.
post_build_selector="${DBT_RUN_POST_BUILD_SELECTOR:-}"
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

run_build() {
  phase="$1"
  select_expr="$2"
  exclude_expr="$3"

  echo "[dbt-scheduler] $(date -Iseconds) running dbt build (${phase})"

  if [ -n "$exclude_expr" ]; then
    # Intentionally unquoted to allow multi-selector values, e.g.
    # "+tag:mart" and "tag:observability".
    # shellcheck disable=SC2086
    dbt build --project-dir /app --profiles-dir /app/dbt --fail-fast --select $select_expr --exclude $exclude_expr
  else
    # Intentionally unquoted to allow multi-selector values, e.g.
    # "+tag:mart" or "+mart_fan_loyalty +mart_player_season_summary".
    # shellcheck disable=SC2086
    dbt build --project-dir /app --profiles-dir /app/dbt --fail-fast --select $select_expr
  fi
}

post_build_selector_log_value="${post_build_selector:-<none>}"
echo "[dbt-scheduler] starting: selector=$selector post_build_selector=${post_build_selector_log_value} interval=${interval_minutes}m fail_fast=${fail_fast}"

while true
do
  # `dbt build` runs models, snapshots, seeds and tests in DAG order, so a failing
  # test on a parent model stops downstream models from running with bad data.
  # --fail-fast makes dbt stop at the first failure within this invocation.
  if run_build "primary" "$selector" "$post_build_selector"; then
    if [ -n "$post_build_selector" ]; then
      if run_build "post-build" "$post_build_selector" ""; then
        echo "[dbt-scheduler] $(date -Iseconds) dbt build succeeded"
      else
        status=$?
        echo "[dbt-scheduler] $(date -Iseconds) post-build dbt build failed with exit code $status" >&2
        if [ "$fail_fast" = "1" ]; then
          echo "[dbt-scheduler] DBT_FAIL_FAST=1 -> exiting so the container restart policy can react" >&2
          exit "$status"
        fi
      fi
    else
      echo "[dbt-scheduler] $(date -Iseconds) dbt build succeeded"
    fi
  else
    status=$?
    echo "[dbt-scheduler] $(date -Iseconds) primary dbt build failed with exit code $status" >&2
    if [ "$fail_fast" = "1" ]; then
      echo "[dbt-scheduler] DBT_FAIL_FAST=1 -> exiting so the container restart policy can react" >&2
      exit "$status"
    fi
  fi
  echo "[dbt-scheduler] sleeping ${interval_minutes} minute(s)"
  sleep "$interval_seconds"
done
