"""Error classification, retrying, and machine-readable conversion reports."""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


class SourceError(RuntimeError):
    """The input source could not be read reliably; conversion must stop."""


class ConversionError(RuntimeError):
    """One article could not be converted; other articles may continue."""


class WriterError(RuntimeError):
    """A SLOB writer operation failed; finalization must not run."""


def retry(operation, attempts=3, initial_delay=1.0, sleep=time.sleep):
    """Run an idempotent source operation with bounded exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt == attempts:
                raise SourceError("source failed after {} attempts: {}".format(attempt, error)) from error
            sleep(initial_delay * (2 ** (attempt - 1)))


@dataclass
class Stats:
    source_errors: int = 0
    conversion_errors: int = 0
    writer_errors: int = 0
    written: int = 0
    empty: int = 0

    def summary(self):
        return (
            "Conversion summary: written={written}, empty={empty}, "
            "source_errors={source_errors}, conversion_errors={conversion_errors}, "
            "writer_errors={writer_errors}"
        ).format(**self.__dict__)


@dataclass
class ErrorReporter:
    path: str
    _file: object = field(init=False, default=None)

    def __enter__(self):
        self._file = open(self.path, "w", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *_):
        self._file.close()

    def record(self, category, error, title=None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "error_type": type(error).__name__,
            "message": str(error),
        }
        if title is not None:
            entry["title"] = title
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
