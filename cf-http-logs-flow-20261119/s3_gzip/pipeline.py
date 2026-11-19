"""The NDJSON entry: one table unit of lines in, the request_log rows and the failed lines out."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from typing import Any

import pyarrow as pa

import aidc_runtime

from . import logs

LOG = logging.getLogger("s3_gzip")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Entry:
    """The entry class the runtime constructs with no arguments (``[tool.aidc] entry``)."""

    table = "cf_request_log_20261119"
    clock: Callable[[], dt.datetime] = staticmethod(utc_now)

    def open(self, lake: Any = None, *, obs: Any = None, **_: Any) -> None:
        log = obs.log if obs is not None else LOG
        log.info("s3_gzip open", extra={"aidc": {"table": self.table, "columns": logs.REQUEST_LOG_SCHEMA.names}})

    def __call__(self, batch: Any, **_: Any) -> tuple[pa.Table, pa.Table | None]:
        split = logs.split(batch.table(), self.clock())
        failed = (aidc_runtime.failed_table(split.failed_rows, split.failed_reasons)
                  if split.failed_rows else None)
        LOG.info("s3_gzip unit", extra={"aidc": {
            "accepted": split.accepted.num_rows, "failed": len(split.failed_rows)}})
        return split.accepted, failed
