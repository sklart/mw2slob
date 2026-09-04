import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

from mw2slob import cli
from mw2slob import core
from mw2slob.reliability import (
    ConversionError,
    ErrorReporter,
    SourceError,
    Stats,
    WriterError,
    retry,
)
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
                                     sleep=delays.append, random_value=lambda: 0))
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
            self.assertEqual("conversion", line["stage"])
            self.assertEqual("ValueError", line["error_type"])
            self.assertEqual("Example", line["title"])

    def test_summary_is_compact(self):
        stats = Stats(written=2, conversion_errors=1)
        self.assertEqual(
            "Processed: 0, Converted: 2, Skipped: 1, Errors: 1", stats.summary())

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

    def test_conversion_error_is_reported_and_does_not_abort(self):
        class Pool:
            def imap_unordered(self, *_args, **_kwargs):
                return iter([("Broken", (), None, "bad HTML"), ("Good", (), b"ok", None)])

            def terminate(self):
                pass

            def join(self):
                pass

        class Writer:
            added = []

            def add(self, text, *keys, **_kwargs):
                self.added.append((text, keys))

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            report = Path(directory) / "errors.jsonl"
            with ErrorReporter(str(report)) as reporter, \
                 patch.object(core.multiprocessing, "Pool", return_value=Pool()):
                stats = core.run(Writer(), [object()], [], [], {}, "utf-8", reporter=reporter)
            self.assertEqual(1, stats.conversion_errors)
            self.assertEqual(1, stats.written)
            self.assertEqual("convert", json.loads(report.read_text(encoding="utf-8"))["stage"])

    def test_writer_error_aborts_immediately(self):
        class Pool:
            def imap_unordered(self, *_args, **_kwargs):
                return iter([("First", (), b"one", None), ("Second", (), b"two", None)])

            def terminate(self):
                pass

            def join(self):
                pass

        class Writer:
            def add(self, *_args, **_kwargs):
                raise OSError("disk full")

        with patch.object(core.multiprocessing, "Pool", return_value=Pool()):
            with self.assertRaises(WriterError):
                core.run(Writer(), [object()], [], [], {}, "utf-8")

    def test_keyboard_interrupt_is_propagated(self):
        class Pool:
            terminated = False
            joined = False

            def imap_unordered(self, *_args, **_kwargs):
                raise KeyboardInterrupt()

            def terminate(self):
                self.terminated = True

            def join(self):
                self.joined = True

        pool = Pool()
        with patch.object(core.multiprocessing, "Pool", return_value=pool):
            with self.assertRaises(KeyboardInterrupt):
                core.run(object(), [object()], [], [], {}, "utf-8")
        self.assertTrue(pool.terminated)
        self.assertTrue(pool.joined)

    def test_cli_accepts_parallelism_and_error_report_options(self):
        args = cli.arg_parser().parse_args([
            "dump", "--jobs", "2", "--chunksize", "25", "--error-report", "report.jsonl", "input.json"
        ])
        self.assertEqual(2, args.jobs)
        self.assertEqual(25, args.chunksize)
        self.assertEqual("report.jsonl", args.errors_file)

    def test_cli_returns_nonzero_for_failed_build(self):
        failed = Mock(side_effect=SourceError("offline"))
        parser = Mock()
        parser.parse_args.return_value = SimpleNamespace(func=failed)
        with patch.object(cli, "arg_parser", return_value=parser):
            self.assertEqual(1, cli.main())


if __name__ == "__main__":
    unittest.main()
