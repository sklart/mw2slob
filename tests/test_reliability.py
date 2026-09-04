import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mw2slob import core
from mw2slob.reliability import ErrorReporter, SourceError, Stats, retry
from mw2slob.siteinfo import Info


class ReliabilityTest(unittest.TestCase):
    def test_retry_uses_exponential_backoff(self):
        calls = []
        delays = []

        def operation():
            calls.append(None)
            if len(calls) < 3:
                raise OSError("temporary")
            return "ok"

        self.assertEqual("ok", retry(operation, attempts=3, initial_delay=0.25,
                                     sleep=delays.append))
        self.assertEqual([0.25, 0.5], delays)

    def test_retry_classifies_exhaustion_as_source_error(self):
        with self.assertRaises(SourceError):
            retry(lambda: (_ for _ in ()).throw(OSError("offline")), attempts=1)

    def test_error_reporter_writes_json_lines(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "errors.jsonl"
            with ErrorReporter(str(path)) as reporter:
                reporter.record("conversion", ValueError("broken html"), "Example")
            line = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("conversion", line["category"])
            self.assertEqual("ValueError", line["error_type"])
            self.assertEqual("Example", line["title"])

    def test_summary_is_compact(self):
        stats = Stats(written=2, conversion_errors=1)
        self.assertEqual(
            "Conversion summary: written=2, empty=0, source_errors=0, "
            "conversion_errors=1, writer_errors=0", stats.summary())

    def test_fatal_source_error_does_not_finalize_writer(self):
        class TempDir:
            def cleanup(self):
                pass

        class Writer:
            tmpdir = TempDir()
            finalized = False

            def tag(self, *_):
                pass

            def finalize(self):
                self.finalized = True

        writer = Writer()
        info = Info("test", "en", False, "", "", "/wiki/", "https://example.test")
        with patch.object(core.slob, "create", return_value=writer), \
             patch.object(core, "run", side_effect=SourceError("input unavailable")), \
             patch.object(core, "p"):
            with self.assertRaises(SourceError):
                core.create_slob("output.slob", info, [])
        self.assertFalse(writer.finalized)


if __name__ == "__main__":
    unittest.main()
