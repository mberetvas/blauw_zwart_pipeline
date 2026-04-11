"""Consumer thread + per-partition asyncio workers (ordered commits, overlapping inserts)."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import TYPE_CHECKING, Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Message

from fan_ingest import db as db_mod
from fan_ingest.records import ParseError, kafka_message_to_row

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("fan_ingest.runner")


class IngestRuntime:
    """Polls Kafka in a dedicated thread; one asyncio worker per partition inserts in order.

    Commits always run on the poll thread (confluent_kafka requirement). Workers signal
    completion via a thread-safe queue; the consumer thread drains it between polls.
    Overlap comes from **multiple partitions** consuming concurrently (SC-004).
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        pool: asyncpg.Pool,
        consumer: Consumer,
        topic: str,
    ) -> None:
        self._loop = loop
        self._pool = pool
        self._consumer = consumer
        self._topic = topic

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._commit_q: queue.Queue[Message] = queue.Queue()

        self._partition_queues: dict[int, asyncio.Queue[tuple[Message, dict[str, Any]] | None]] = {}
        self._partition_tasks: dict[int, asyncio.Task[None]] = {}
        self._queues_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._consumer_thread_main,
            name="kafka-consumer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def _drain_commits(self) -> None:
        while True:
            try:
                msg = self._commit_q.get_nowait()
            except queue.Empty:
                break
            try:
                self._consumer.commit(msg, asynchronous=False)
            except KafkaException as exc:
                logger.error(
                    "ingest_commit_error topic=%s partition=%s offset=%s: %s",
                    msg.topic(),
                    msg.partition(),
                    msg.offset(),
                    exc,
                    exc_info=exc,
                )

    def _ensure_partition_worker(self, partition: int) -> None:
        with self._queues_lock:
            if partition in self._partition_queues:
                return
            # Create the asyncio.Queue and schedule the Task on the event-loop thread.
            # Creating asyncio primitives from a non-event-loop thread is not thread-safe,
            # so we bootstrap via run_coroutine_threadsafe and block until done.
            fut = asyncio.run_coroutine_threadsafe(
                self._start_partition_worker(partition), self._loop
            )
            fut.result(timeout=30.0)

    async def _start_partition_worker(self, partition: int) -> None:
        """Create Queue + Task for *partition* on the event-loop thread (thread-safe)."""
        q: asyncio.Queue[tuple[Message, dict[str, Any]] | None] = asyncio.Queue()
        self._partition_queues[partition] = q
        task = asyncio.create_task(self._partition_worker(partition, q))
        task.add_done_callback(self._on_partition_worker_done)
        self._partition_tasks[partition] = task

    async def _shutdown_partition_workers(self) -> None:
        for q in list(self._partition_queues.values()):
            await q.put(None)
        await asyncio.gather(*list(self._partition_tasks.values()), return_exceptions=True)

    def _on_partition_worker_done(self, task: asyncio.Task[None]) -> None:
        """Done-callback: if a worker task fails, log and trigger a controlled shutdown."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.critical(
                "partition_worker_failed – triggering shutdown: %s",
                exc,
                exc_info=exc,
            )
            self._stop.set()

    async def _partition_worker(
        self,
        partition: int,
        q: asyncio.Queue[tuple[Message, dict[str, Any]] | None],
    ) -> None:
        while True:
            item = await q.get()
            try:
                if item is None:
                    return
                msg, row = item
                await db_mod.insert_fan_event_row(self._pool, row)
                self._commit_q.put(msg)
            except Exception:
                if item is not None:
                    msg = item[0]
                    db_mod.log_write_error(
                        kafka_topic=msg.topic(),
                        kafka_partition=msg.partition(),
                        kafka_offset=msg.offset(),
                    )
                raise
            finally:
                q.task_done()

    def _enqueue_row(self, msg: Message, row: dict[str, Any], partition: int) -> None:
        q = self._partition_queues[partition]

        async def _put() -> None:
            await q.put((msg, row))

        fut = asyncio.run_coroutine_threadsafe(_put(), self._loop)
        fut.result(timeout=30.0)

    def _consumer_thread_main(self) -> None:
        while not self._stop.is_set():
            self._drain_commits()
            msg = self._consumer.poll(0.3)
            self._drain_commits()

            if msg is None:
                continue
            if msg.error():
                err = msg.error()
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("consumer_error: %s", err)
                continue

            if msg.topic() != self._topic:
                logger.warning("unexpected_topic got=%s want=%s", msg.topic(), self._topic)
                continue

            partition = msg.partition()
            self._ensure_partition_worker(partition)

            try:
                row = kafka_message_to_row(
                    kafka_topic=msg.topic(),
                    kafka_partition=partition,
                    kafka_offset=msg.offset(),
                    value=msg.value(),
                )
            except ParseError as exc:
                logger.warning(
                    "ingest_parse_skip topic=%s partition=%s offset=%s error=%s",
                    msg.topic(),
                    partition,
                    msg.offset(),
                    exc,
                    extra={
                        "kafka_topic": msg.topic(),
                        "kafka_partition": partition,
                        "kafka_offset": msg.offset(),
                    },
                )
                try:
                    self._consumer.commit(msg, asynchronous=False)
                except KafkaException as exc:
                    logger.error(
                        "ingest_commit_error topic=%s partition=%s offset=%s: %s",
                        msg.topic(),
                        partition,
                        msg.offset(),
                        exc,
                        exc_info=exc,
                    )
                continue

            try:
                self._enqueue_row(msg, row, partition)
            except Exception:
                logger.exception(
                    "enqueue_failed topic=%s partition=%s offset=%s",
                    msg.topic(),
                    partition,
                    msg.offset(),
                )
                raise

        fut = asyncio.run_coroutine_threadsafe(self._shutdown_partition_workers(), self._loop)
        try:
            fut.result(timeout=120.0)
        except Exception:
            logger.exception("partition_worker_shutdown_failed")

        self._drain_commits()
        try:
            self._consumer.close()
        except KafkaException:
            logger.exception("consumer_close_error")
