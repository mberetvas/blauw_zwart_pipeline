"""CLI package for ``fan_events``.

The console script entrypoint ``fan_events.cli:main`` resolves here.
"""

from fan_events.cli.main import (  # noqa: F401 – public re-exports
    DEFAULT_CALENDAR_LOOP_SHIFT_DAYS,
    SUBCOMMAND_EVENTS,
    SUBCOMMAND_RETAIL,
    SUBCOMMAND_STREAM,
    _run_stream_kafka,
    main,
    parse_args,
    run_stream,
    run_v1,
    run_v2,
    run_v3,
)
