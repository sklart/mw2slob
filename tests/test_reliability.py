import json
import tempfile
import unittest
from http.client import IncompleteRead
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

import slob
from mw2slob import cli
from mw2slob import core
from mw2slob import convert
from mw2slob import dump
from mw2slob import scrape
from mw2slob import siteinfo
from mw2slob.reliability import (
    ConversionError,
    ConversionFailure,
    ErrorReporter,
    SourceError,
    Stats,
    WriterError,
    retry,
)
from mw2slob.siteinfo import Info


class ReliabilityTest(unittest.TestCase):
    def convert_html(self, html):
        params = convert.ConvertParams(
            title="Article", aliases=(), text=html, rtl=False, server="https://example.test",
            articlepath="/wiki/", site_articlepath="/wiki/", encoding="utf-8",
            remove_embedded_bg="", ensure_ext_image_urls=False,
        )
        return convert.convert(params, (), {}, {}).decode("utf-8")

    def test_upstream_html_serialization_and_image_priority(self):
        converted = self.convert_html(
            '<html><body class="article"><p>Text</p><img src="/image.png"></body></html>')
        self.assertTrue(converted.startswith("<!DOCTYPE html>"))
        self.assertIn('<body class="article">', converted)
        self.assertNotIn("<div><body", converted)
        self.assertIn('loading="lazy"', converted)
        self.assertIn('fetchpriority="low"', converted)

    def test_upstream_math_fallback_remains_supported(self):
        converted = self.convert_html(
            '<html><body><span class="mwe-math-element" '
            'data-mw=\'{"body":{"extsrc":"x^2"}}\'>'
            '<img class="mwe-math-fallback-image-inline" src="/math.png" alt="x²">'
            '</span></body></html>')
        self.assertIn(convert.MATH_JAX_SCRIPTS, converted)
        self.assertIn('data-tex="x^2"', converted)
        self.assertNotIn('src="/math.png"', converted)

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
                return iter([
                    ("Broken", (), None, ConversionFailure("ValueError", "bad HTML")),
                    ("Good", (), b"ok", None),
                ])

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
            error = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("convert", error["stage"])
            self.assertEqual("ValueError", error["error_type"])
            self.assertEqual("bad HTML", error["message"])

    def test_safe_convert_preserves_original_exception_type(self):
        params = SimpleNamespace(title="Broken", aliases=(), text="<bad>")
        with patch.object(core.convert, "convert", side_effect=ValueError("bad HTML")):
            _title, _aliases, text, failure = core.safe_convert(params)
        self.assertIsNone(text)
        self.assertEqual("ValueError", failure.exception_type)
        self.assertEqual("bad HTML", failure.message)

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

    def test_cli_returns_nonzero_for_failed_finalization(self):
        failed = Mock(side_effect=WriterError("finalization failed"))
        parser = Mock()
        parser.parse_args.return_value = SimpleNamespace(func=failed)
        with patch.object(cli, "arg_parser", return_value=parser):
            self.assertEqual(1, cli.main())

    def test_couch_iteration_recovers_without_duplicates_or_gaps(self):
        class Row:
            def __init__(self, key):
                self.id = key

        class Couch:
            calls = []

            def iterview(self, _name, _batch_size, **args):
                self.calls.append(args)
                if len(self.calls) == 1:
                    def interrupted():
                        yield Row("A")
                        yield Row("B")
                        raise IncompleteRead(b"", 1)
                    return interrupted()
                if len(self.calls) == 2:
                    def interrupted_again():
                        yield Row("B")
                        yield Row("C")
                        raise IncompleteRead(b"", 1)
                    return interrupted_again()

                def resumed():
                    yield Row("C")
                    yield Row("D")
                return resumed()

        couch = Couch()
        rows = list(scrape.iter_view_with_retries(
            couch, "_all_docs", 50, {}, initial_delay=0, sleep=lambda _: None,
            random_value=lambda: 0))
        self.assertEqual(["A", "B", "C", "D"], [row.id for row in rows])
        self.assertEqual("B", couch.calls[1]["startkey"])
        self.assertEqual("C", couch.calls[2]["startkey"])

    def test_couch_iteration_aborts_after_retry_exhaustion(self):
        class Couch:
            def iterview(self, *_args, **_kwargs):
                def interrupted():
                    raise IncompleteRead(b"", 1)
                    yield None
                return interrupted()

        with self.assertRaises(SourceError):
            list(scrape.iter_view_with_retries(
                Couch(), "_all_docs", 50, {}, attempts=2, initial_delay=0,
                sleep=lambda _: None, random_value=lambda: 0))

    def test_failed_finalization_preserves_existing_output_and_removes_temp(self):
        class TempDir:
            def cleanup(self):
                pass

        class Writer:
            tmpdir = TempDir()

            def __init__(self, filename):
                self.filename = filename

            def tag(self, *_args):
                pass

            def finalize(self):
                Path(self.filename).write_bytes(b"partial")
                raise OSError("finalization failed")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            output = Path(directory) / "output.slob"
            output.write_bytes(b"previous")
            info = Info("test", "en", False, "", "", "/wiki/", "https://example.test")
            with patch.object(core.slob, "create", side_effect=lambda path, **_kwargs: Writer(path)), \
                 patch.object(core.slob, "add_dir"), patch.object(core, "run"), \
                 patch.object(core, "p"):
                with self.assertRaises(WriterError):
                    core.create_slob(str(output), info, [], no_math=True)
            self.assertEqual(b"previous", output.read_bytes())
            self.assertFalse(Path(str(output) + ".tmp").exists())

    def test_successful_finalization_atomically_replaces_existing_output(self):
        class TempDir:
            def cleanup(self):
                pass

        class Writer:
            tmpdir = TempDir()

            def __init__(self, filename):
                self.filename = filename

            def tag(self, *_args):
                pass

            def finalize(self):
                Path(self.filename).write_bytes(b"replacement")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            output = Path(directory) / "output.slob"
            output.write_bytes(b"previous")
            info = Info("test", "en", False, "", "", "/wiki/", "https://example.test")
            with patch.object(core.slob, "create", side_effect=lambda path, **_kwargs: Writer(path)), \
                 patch.object(core.slob, "add_dir"), patch.object(core, "run"), \
                 patch.object(core, "p"):
                core.create_slob(str(output), info, [], no_math=True)
            self.assertEqual(b"replacement", output.read_bytes())
            self.assertFalse(Path(str(output) + ".tmp").exists())

    def test_dump_to_slob_end_to_end_smoke(self):
        records = [
            {
                "name": "Article",
                "article_body": {"html": "<p>Normal <strong>article</strong>.</p>"},
                "redirects": [{"name": "Article alias"}],
            },
            {
                "name": "Ёж",
                "article_body": {"html": "<p>Unicode title and content.</p>"},
            },
            {
                "name": "Wiki markup",
                "article_body": {
                    "html": "<style>.note { color: red; }</style><p class=\"note\">"
                            "<a href=\"/wiki/Target\">Target</a></p>"
                },
            },
        ]
        info = Info("test", "en", False, "", "", "/wiki/", "https://example.test")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            source = root / "fixture.jsonl"
            source.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
            output = root / "output.slob"
            core.create_slob(
                str(output), info, dump.articles([str(source)], info), workdir=str(root),
                no_math=True, jobs=1, chunksize=1,
            )
            self.assertTrue(output.exists())
            self.assertFalse(Path(str(output) + ".tmp").exists())
            verification = slob.verify(str(output), full=True)
            self.assertTrue(verification["valid"])
            with slob.open(str(output)) as dictionary:
                entries = list(dictionary)
                keys = {entry.key for entry in entries}
                self.assertTrue({"Article", "Article alias", "Ёж", "Wiki markup"}.issubset(keys))
                article = next(entry for entry in entries if entry.key == "Article")
                self.assertEqual("text/html;charset=utf-8", article.content_type)
                self.assertIn(b"Normal", article.content)
                self.assertGreaterEqual(len(dictionary), 4)


if __name__ == "__main__":
    unittest.main()
