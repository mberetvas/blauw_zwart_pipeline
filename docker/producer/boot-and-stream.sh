#!/bin/sh
set -eu

STATE_DIR="${FAN_EVENTS_BOOTSTRAP_STATE_DIR:-/var/lib/fan-events-producer}"
SENTINEL_PATH="${FAN_EVENTS_BOOTSTRAP_SENTINEL:-$STATE_DIR/bootstrap.done}"

BOOTSTRAP_ENABLED="${FAN_EVENTS_BOOTSTRAP_ENABLED:-1}"
BOOTSTRAP_INCLUDE_RETAIL="${FAN_EVENTS_BOOTSTRAP_INCLUDE_RETAIL:-0}"

SEED="${FAN_EVENTS_STREAM_SEED:-42}"
CALENDAR_PATH="${FAN_EVENTS_CALENDAR_PATH:-/app/match_day.example.json}"
KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-broker:29092}"
KAFKA_TOPIC_NAME="${KAFKA_TOPIC:-fan_events}"

NORMAL_EMIT_MIN="${FAN_EVENTS_STREAM_EMIT_WALL_CLOCK_MIN:-0.1}"
NORMAL_EMIT_MAX="${FAN_EVENTS_STREAM_EMIT_WALL_CLOCK_MAX:-0.5}"

BOOTSTRAP_EMIT_MIN="${FAN_EVENTS_BOOTSTRAP_EMIT_WALL_CLOCK_MIN:-0}"
BOOTSTRAP_EMIT_MAX="${FAN_EVENTS_BOOTSTRAP_EMIT_WALL_CLOCK_MAX:-0}"
BOOTSTRAP_MAX_EVENTS="${FAN_EVENTS_BOOTSTRAP_MAX_EVENTS:-}"
BOOTSTRAP_MAX_DURATION="${FAN_EVENTS_BOOTSTRAP_MAX_DURATION_SECONDS:-}"

mkdir -p "$STATE_DIR"

run_normal_stream() {
  echo "[producer] starting normal continuous stream"
  exec fan_events stream \
    --calendar "$CALENDAR_PATH" \
    -s "$SEED" \
    --emit-wall-clock-min "$NORMAL_EMIT_MIN" \
    --emit-wall-clock-max "$NORMAL_EMIT_MAX" \
    --kafka-bootstrap-servers "$KAFKA_BOOTSTRAP" \
    --kafka-topic "$KAFKA_TOPIC_NAME"
}

if [ "$BOOTSTRAP_ENABLED" != "1" ]; then
  echo "[producer] bootstrap disabled (FAN_EVENTS_BOOTSTRAP_ENABLED=$BOOTSTRAP_ENABLED)"
  run_normal_stream
fi

if [ -f "$SENTINEL_PATH" ]; then
  echo "[producer] bootstrap already completed ($SENTINEL_PATH present)"
  run_normal_stream
fi

echo "[producer] bootstrap missing sentinel; running one-time fast season bootstrap"

set -- fan_events stream \
  --calendar "$CALENDAR_PATH" \
  -s "$SEED" \
  --no-calendar-loop \
  --emit-wall-clock-min "$BOOTSTRAP_EMIT_MIN" \
  --emit-wall-clock-max "$BOOTSTRAP_EMIT_MAX" \
  --kafka-bootstrap-servers "$KAFKA_BOOTSTRAP" \
  --kafka-topic "$KAFKA_TOPIC_NAME"

if [ "$BOOTSTRAP_INCLUDE_RETAIL" = "1" ]; then
  if [ -n "$BOOTSTRAP_MAX_EVENTS" ]; then
    set -- "$@" --max-events "$BOOTSTRAP_MAX_EVENTS"
  fi
  if [ -n "$BOOTSTRAP_MAX_DURATION" ]; then
    set -- "$@" --max-duration "$BOOTSTRAP_MAX_DURATION"
  fi
  if [ -z "$BOOTSTRAP_MAX_EVENTS" ] && [ -z "$BOOTSTRAP_MAX_DURATION" ]; then
    echo "[producer] retail bootstrap requested but unbounded; falling back to --no-retail for safe completion"
    set -- "$@" --no-retail
  fi
else
  set -- "$@" --no-retail
fi

"$@"

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$SENTINEL_PATH"
echo "[producer] bootstrap completed; sentinel written to $SENTINEL_PATH"

run_normal_stream
