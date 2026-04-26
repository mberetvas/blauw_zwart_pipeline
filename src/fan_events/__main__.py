"""Support ``python -m fan_events`` by delegating to the CLI entrypoint."""

from fan_events.cli import main

if __name__ == "__main__":
    main()
