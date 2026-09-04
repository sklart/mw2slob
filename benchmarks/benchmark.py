"""Reproducible, offline performance benchmark for mw2slob.

The generated JSONL fixture intentionally mixes ordinary, Unicode, aliased,
CSS-heavy, and MathJax-like articles. Results are written as JSON so runs from
different machines can be compared without scraping console output.
"""

import argparse
import json
import os
import platform
import time
import tracemalloc
from pathlib import Path

from mw2slob import core, dump
from mw2slob.siteinfo import Info


class StageObserver:
    EVENTS = {
        "sort": ("begin_sort", "end_sort"),
        "alias_resolve": ("begin_resolve_aliases", "end_resolve_aliases"),
        "finalization": ("begin_finalize", "end_finalize"),
    }

    def __init__(self):
        self.timings = {}
        self._active = {}

    def __call__(self, event):
        now = time.perf_counter()
        for stage, (begin, end) in self.EVENTS.items():
            if event.name == begin:
                self._active.setdefault(stage, []).append(now)
            elif event.name == end and self._active.get(stage):
                self.timings[stage] = self.timings.get(stage, 0.0) + now - self._active[stage].pop()


class TimedArticles:
    def __init__(self, source, info):
        self.source = source
        self.info = info
        self.elapsed = 0.0

    def __iter__(self):
        articles = dump.articles([str(self.source)], self.info)
        while True:
            started = time.perf_counter()
            try:
                article = next(articles)
            except StopIteration:
                self.elapsed += time.perf_counter() - started
                return
            self.elapsed += time.perf_counter() - started
            yield article


def fixture_record(index, heavy=False):
    title = "Статья {} — ёж".format(index) if index % 17 == 0 else "Article {}".format(index)
    css = "<style>.note{color:red;padding:4px}.x{font-weight:bold}</style>" if index % 5 == 0 else ""
    math = "<span class=\"mwe-math-element\" data-mw=\"{}\">x² + y²</span>" if index % 11 == 0 else ""
    repeated = ("<p class=\"note\">Heavy HTML <b>content</b> <a href=\"/wiki/Target\">Target</a>.</p>" * 20
                if heavy else "<p class=\"note\">HTML <b>content</b> <a href=\"/wiki/Target\">Target</a>.</p>")
    return {
        "name": title,
        "article_body": {"html": css + repeated + math},
        "redirects": [{"name": "Alias {}".format(index)}] if index % 7 == 0 else [],
    }


def write_fixture(path, count, heavy=False):
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for index in range(count):
            output.write(json.dumps(fixture_record(index, heavy), ensure_ascii=False) + "\n")


def peak_rss_bytes():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if platform.system() == "Darwin" else value * 1024
    except ImportError:
        return None


def run_benchmark(output_dir, articles, jobs, chunksize, heavy=False, no_math=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = output_dir / "fixture-{}.jsonl".format(articles)
    output = output_dir / "output.slob"
    write_fixture(fixture, articles, heavy=heavy)
    info = Info("Benchmark", "en", False, "", "", "/wiki/", "https://benchmark.invalid")
    observer = StageObserver()
    timings = {}
    timed_articles = TimedArticles(fixture, info)
    started = time.perf_counter()
    cpu_started = time.process_time()
    tracemalloc.start()
    core.create_slob(
        str(output), info, timed_articles, workdir=str(output_dir), no_math=no_math,
        jobs=jobs, chunksize=chunksize, observer=observer, timings=timings,
    )
    current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total = time.perf_counter() - started
    result = {
        "articles": articles,
        "jobs": jobs if jobs is not None else "auto",
        "chunksize": chunksize,
        "heavy": heavy,
        "mathjax": not no_math,
        "total": total,
        "articles_per_second": articles / total if total else 0.0,
        "cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_bytes": peak_rss_bytes(),
        "peak_python_tracemalloc_bytes": traced_peak,
        "output_bytes": output.stat().st_size,
        "source_read": timed_articles.elapsed,
        "html_conversion_worker": timings.get("html_conversion_worker", 0.0),
        "writer_add": timings.get("writer_add", 0.0),
        "sorting": observer.timings.get("sort", 0.0),
        "alias_resolve": observer.timings.get("alias_resolve", 0.0),
        "finalization": observer.timings.get("finalization", 0.0),
    }
    effective_jobs = jobs or (os.cpu_count() or 1)
    result["multiprocessing_overhead_estimate"] = max(
        0.0, total - result["source_read"] - result["writer_add"]
        - (result["html_conversion_worker"] / effective_jobs)
        - result["finalization"],
    )
    (output_dir / "benchmark.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=int, default=1000, choices=(5, 1000, 10000))
    parser.add_argument("--jobs", default="auto", choices=("1", "2", "4", "auto"))
    parser.add_argument("--chunksize", type=int, default=100, choices=(1, 10, 25, 50, 100, 250, 500))
    parser.add_argument("--heavy", action="store_true")
    parser.add_argument("--no-math", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-output"))
    parser.add_argument("--smoke", action="store_true", help="Run the short offline CI benchmark")
    args = parser.parse_args()
    if args.smoke:
        args.articles = 5
        args.jobs = "1"
        args.chunksize = 1
        args.no_math = True
    jobs = None if args.jobs == "auto" else int(args.jobs)
    result = run_benchmark(args.output_dir, args.articles, jobs, args.chunksize,
                           heavy=args.heavy, no_math=args.no_math)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
