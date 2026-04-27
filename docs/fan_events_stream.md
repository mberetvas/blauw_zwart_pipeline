## Executive Summary

This command starts the `fan_events` **stream** subcommand and turns the repo into a live synthetic event producer for Kafka.[^1][^2] In this repository, the same command shape is the `producer` service's normal steady-state mode after any optional bootstrap run, so it is meant to keep publishing events continuously rather than writing a one-off batch file.[^3][^4]

With `--calendar <CALENDAR_PATH>`, the stream includes **v2 match-day events** generated from the calendar JSON; because `--no-retail` is not present, it also includes **v3 retail_purchase events**, merges both sources in timestamp order, and emits them as NDJSON records.[^5][^6][^7] The `-s <SEED>` value makes generation reproducible, and the implementation splits that seed into independent RNG namespaces for calendar events, retail events, and wall-clock pacing so each stays stable.[^5]

`--emit-wall-clock-min 0.1` and `--emit-wall-clock-max 0.5` do **not** change the synthetic event timestamps; they only sleep for a random 0.1-0.5 seconds between emitted lines after the first line, making the producer feel "live" at roughly 100-500 ms per message.[^8][^9] `--kafka-bootstrap-servers broker:29092 --kafka-topic fan_events` switches output from stdout/file mode into Kafka mode, creating a Kafka producer and publishing each NDJSON line to the `fan_events` topic on the broker container.[^10][^11]

## What the command does, in plain English

It runs the synthetic fan-event generator as a **continuous Kafka publisher** for the [mberetvas/blauw_zwart_pipeline](https://github.com/mberetvas/blauw_zwart_pipeline) stack.[^1][^3] Concretely, it:

1. Loads and validates the match calendar JSON.[^12][^13]
2. Builds calendar-based supporter events such as `ticket_scan` and `merch_purchase` records around each match window.[^6][^14]
3. Simultaneously generates retail `retail_purchase` events from a separate retail simulator.[^7][^15]
4. Applies extra retail intensity on match days when both calendar and retail streams are active.[^5][^16]
5. Merges both event streams into one globally time-sorted NDJSON stream.[^5][^17]
6. Sleeps 0.1-0.5 seconds between emitted lines to simulate live arrival cadence.[^8][^9]
7. Publishes each line to Kafka topic `fan_events` on broker `broker:29092`.[^10][^11]

## Flag-by-flag breakdown

| Part | Effect |
|---|---|
| `fan_events` | Invokes the console script registered in `pyproject.toml`, which points to `fan_events.cli:main`.[^1] |
| `stream` | Selects the merged streaming subcommand that combines calendar events and/or retail events into one ordered stream.[^2][^5] |
| `--calendar <CALENDAR_PATH>` | Enables calendar-driven v2 events by loading that JSON file and deriving match contexts from it.[^2][^5][^12] |
| `-s <SEED>` | Makes the run reproducible; the code derives separate RNGs from the seed for v2, retail, and pacing behavior.[^5] |
| `--emit-wall-clock-min 0.1 --emit-wall-clock-max 0.5` | Adds a random wall-clock delay between lines, uniformly sampled from 0.1 to 0.5 seconds.[^8][^9] |
| `--kafka-bootstrap-servers broker:29092` | Points Kafka mode at the Compose broker listener used by containers on the Docker network.[^3][^10] |
| `--kafka-topic fan_events` | Enables Kafka output and sends messages to topic `fan_events`; Kafka mode is mutually exclusive with `-o/--output` file output.[^2][^10][^18] |

## Data flow and runtime behavior

### 1. Entrypoint and dispatch

The package registers `fan_events = "fan_events.cli:main"` as a console script, and `fan_events.cli` re-exports the parser and `main` implementation from `fan_events.cli.main`.[^1][^19] When the parsed command is `stream`, `main()` dispatches to `run_stream()`.[^11]

### 2. Calendar side of the stream

When `--calendar` is supplied, `run_stream()` loads the JSON document from disk, validates the `matches` array, parses match metadata such as kickoff time, timezone, attendance, and venue fields, and converts each match into a `MatchContext` that includes kickoff, event window, and effective capacity.[^5][^12][^13] The calendar side can then emit `ticket_scan`, `merch_purchase`, or both event types; in the default `both` mode it emits both.[^6][^20]

The stream parser documents that calendar mode **loops by default** and replays the season with a `+1` calendar-year shift on each pass unless `--no-calendar-loop` is used.[^2] In the implementation, `run_stream()` selects `iter_looped_v2_records()` when calendar looping is enabled, and that iterator keeps replaying the base contexts forever with suffixed `match_id` values such as `:c1`, `:c2`, and so on.[^5][^20]

### 3. Retail side of the stream

The retail generator emits `retail_purchase` events from an independent simulator with configurable arrival model, epoch, and fan pool.[^7][^15] In stream mode, `_stream_retail_kwargs()` forwards any retail-specific caps, but if neither `--retail-max-events` nor `--retail-max-duration` is set, it explicitly sets `skip_default_event_cap=True`; `iter_retail_records()` therefore does **not** fall back to its standalone default cap of 200 events and can run indefinitely.[^21][^15]

Because your command includes `--calendar` but not `--no-retail`, `run_stream()` enables both the calendar iterator and the retail iterator.[^5] When both are active, it also shares a unified fan pool across both generators so IDs can overlap realistically across match and retail behavior.[^5][^17]

### 4. Match-day retail uplift

When both calendar and retail are present, `run_stream()` installs a `rate_factor_fn` built by `build_retail_rate_factor_fn()`.[^5][^16] That function increases retail intensity on home match days, boosts it further in configurable pre/post-kickoff windows, and can optionally boost away-only match days too.[^16] In Poisson mode, the multiplier scales the effective retail arrival rate `lambda`; in non-Poisson modes it reduces the sampled gap duration by the same factor.[^15][^16]

### 5. Merge order

The stream does not interleave sources arbitrarily. Calendar records and retail records are each produced in sorted order and then merged with `heapq.merge(..., key=merge_key_tuple)` into one globally ordered stream.[^17][^20] The orchestrator serializes retail records with the v3 formatter and non-retail records with the v2 formatter, so the output topic receives a mixed but schema-correct NDJSON feed.[^17]

### 6. Pacing

The `--emit-wall-clock-*` options are validated as a required min/max pair, must be non-negative, and must satisfy `min <= max`.[^9] During emission, `write_merged_stream()` sleeps only **between** lines, never before the first line, and only when both bounds plus a pacing RNG are present.[^8] That means your command introduces real-time pacing on the outbound Kafka messages, but the event payload timestamps still come from the synthetic match/retail timelines rather than from wall-clock `now()`.[^8][^15][^20]

### 7. Kafka output mode

If `args.kafka_topic` is set, `run_stream()` routes to `_run_stream_kafka()` instead of stdout or file output.[^5] `_run_stream_kafka()` loads `confluent_kafka.Producer`, merges CLI overrides with `FAN_EVENTS_KAFKA_*` environment defaults, logs the resolved topic/client/bootstrap summary, builds a producer config, and wraps the producer in `KafkaSink`.[^10][^11]

`KafkaSink.write()` sends each NDJSON line as the Kafka message value, with `key=None`, which means no explicit key-based partitioning is applied by this producer.[^10] `KafkaSink.flush()` polls delivery callbacks after every emitted line, and `KafkaSink.close()` performs a blocking producer flush with a 30-second timeout on shutdown.[^10] The tests also verify that Kafka mode is activated by `--kafka-topic` or the equivalent env var, and that Kafka output is intentionally mutually exclusive with file/stdout `-o` selection.[^18]

## What this exact command likely means in this repo

This exact command pattern is the repo's **normal producer loop** in `docker/producer/boot-and-stream.sh`.[^3] After optional one-time bootstrap logic, the script executes:

```sh
fan_events stream \
  --calendar "$CALENDAR_PATH" \
  -s "$SEED" \
  --emit-wall-clock-min "$NORMAL_EMIT_MIN" \
  --emit-wall-clock-max "$NORMAL_EMIT_MAX" \
  --kafka-bootstrap-servers "$KAFKA_BOOTSTRAP" \
  --kafka-topic "$KAFKA_TOPIC_NAME"
```

That script defaults `NORMAL_EMIT_MIN=0.1`, `NORMAL_EMIT_MAX=0.5`, `KAFKA_BOOTSTRAP=broker:29092`, `KAFKA_TOPIC_NAME=fan_events`, and `SEED=42`, which matches the intent of the command you asked about almost exactly.[^3] The Compose `producer` service is documented as "Runs the synthetic `fan_events` stream," and its environment comments note that in Kafka mode the service logs startup/progress to stderr instead of printing every NDJSON record to container stdout.[^4]

So, in practice, this command is the **steady-state live event source** for the rest of the demo stack: Kafka receives `fan_events`, downstream `ingest` persists them into Postgres, dbt builds marts on top, and the frontend consumes those marts later in the pipeline.[^22][^23]

## Operational implications

1. **It is usually long-running.** With `--calendar` the season loops by default, and the retail iterator is also uncapped unless you set retail-specific limits, so the producer is intended to keep running until interrupted.[^2][^5][^15][^21]
2. **It is reproducible.** Given the same seed and inputs, the synthetic timelines and pacing decisions are designed to be stable because the command derives deterministic RNG namespaces from the seed.[^5][^7]
3. **It is paced for realism, not throughput.** A 0.1-0.5 second sleep between lines yields roughly a few messages per second rather than a bulk backfill rate.[^8][^9]
4. **It writes to Kafka, not a file.** Once `--kafka-topic` is supplied, the CLI switches away from stdout/file output and becomes a Kafka producer.[^5][^10][^18]

## Confidence Assessment

**High confidence:** The command's entrypoint, parser behavior, merge logic, pacing semantics, Kafka publishing path, and its role inside Docker Compose are all directly verified from source code, tests, and runtime help output in this repository.[^1][^2][^3][^4][^5][^8][^10][^18]

**Moderate confidence:** The exact business meaning of the calendar contents depends on the JSON file passed as `<CALENDAR_PATH>`, which I did not inspect here because your question was about the command itself rather than a specific calendar document.[^12][^13]

**Important assumption:** I treated the `# ~100–500 ms pacing between emitted lines` fragment in your snippet as an explanatory shell comment, not as part of the `fan_events` CLI surface, because the CLI only defines the documented flags shown in `stream --help` and in the parser source.[^2][^24]

## Footnotes

[^1]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\pyproject.toml:50-52` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^2]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:840-1159` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`); `uv run python -m fan_events stream --help` captured from repo at commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`
[^3]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker\producer\boot-and-stream.sh:10-33,36-77` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^4]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker-compose.yml:181-205` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^5]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:1352-1470` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^6]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v2_calendar.py:398-482,556-597` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^7]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v3_retail.py:1-10,113-230` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^8]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\orchestrator.py:90-155` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^9]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:455-464` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^10]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\sinks\kafka_sink.py:1-30,75-127,148-279` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^11]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:1490-1595` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^12]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v2_calendar.py:55-75,183-250,356-381` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^13]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v2_calendar.py:340-353` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^14]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v2_calendar.py:438-481` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^15]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v3_retail.py:129-230` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^16]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\retail_intensity.py:1-152` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^17]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\orchestrator.py:23-38,59-88` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^18]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:489-509` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`); `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\tests\test_kafka_sink.py:245-366` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^19]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\__init__.py:1-20` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`); `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\__main__.py:1-6` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^20]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v2_calendar.py:522-553,600-715` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^21]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:354-381` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`); `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\generation\v3_retail.py:172-176` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^22]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\README.md:29-42,44-92` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^23]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\README.md:3-32` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`); `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\tests\test_cli_stream.py:97-124,127-141` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
[^24]: `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_events\cli\main.py:1097-1159` (commit `d238b4c0fb2636a9fcd68b13e4ac2c1b01d0d449`)
