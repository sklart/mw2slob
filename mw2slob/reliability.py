"""Error classification, retrying, and machine-readable conversion reports."""

import json
import random
import socket
import time
from http.client import IncompleteRead
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.error import HTTPError


class SourceError(RuntimeError):
    """The input source could not be read reliably; conversion must stop."""


class ConversionError(RuntimeError):
    """One article could not be converted; other articles may continue."""


class WriterError(RuntimeError):
    """A SLOB writer operation failed; finalization must not run."""


@dataclass(frozen=True)
class ConversionFailure:
    """Pickle-safe description of an exception raised by a worker process."""

    exception_type: str
    message: str


def is_retryable_source_error(error):
    """Return whether a source exception can be retried safely."""
    if isinstance(error, (IncompleteRead, socket.timeout, ConnectionResetError, TimeoutError)):
        return True
    if isinstance(error, HTTPError):
        return error.code in (429, 502, 503, 504)
    if isinstance(error, OSError):
        return True
    return False


def retry(operation, attempts=3, initial_delay=1.0, sleep=time.sleep,
          random_value=random.random):
    """Run an idempotent source operation with bounded exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except KeyboardInterrupt:
            raise
        except Exception as error:
            if not is_retryable_source_error(error) or attempt == attempts:
                raise SourceError("source failed after {} attempts: {}".format(attempt, error)) from error
            delay = initial_delay * (2 ** (attempt - 1))
            sleep(delay + (delay * 0.25 * random_value()))


@dataclass
class Stats:
    processed: int = 0
    source_errors: int = 0
    conversion_errors: int = 0
    writer_errors: int = 0
    written: int = 0
    empty: int = 0

    def summary(self, elapsed=None):
        skipped = self.empty + self.conversion_errors
        rate = ""
        if elapsed and elapsed > 0:
            rate = ", rate={:.0f}/s".format(self.processed / elapsed)
        return (
            "Processed: {processed}, Converted: {written}, Skipped: {skipped}, "
            "Errors: {errors}" + rate
        ).format(processed=self.processed, written=self.written, skipped=skipped,
                 errors=self.source_errors + self.conversion_errors + self.writer_errors)


@dataclass
class ErrorReporter:
    path: str
    _file: object = field(init=False, default=None)

    def __enter__(self):
        self._file = open(self.path, "w", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *_):
        self._file.close()

    def record(self, stage, error, title=None, source=None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "category": stage,
            "error_type": getattr(error, "original_type", type(error).__name__),
            "message": getattr(error, "original_message", str(error)),
            "source": source,
        }
        if title is not None:
            entry["title"] = title
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
