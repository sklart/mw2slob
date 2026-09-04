"""Reproducible, offline performance benchmark for mw2slob.

The generated JSONL fixture intentionally mixes ordinary, Unicode, aliased,
CSS-heavy, and MathJax-like articles. Results are written as JSON so runs from
different machines can be compared without scraping console output.
"""

import argparse
import json
import os
import threading
import time
from pathlib import Path

import psutil
from mw2slob import core, dump
from mw2slob.siteinfo import Info


class ProcessTreeSampler:
    """Sample CPU and RSS for the parent plus all multiprocessing workers."""

    def __init__(self, interval=0.01):
        self.parent_pid = os.getpid()
        self.parent_start_cpu = self._cpu(psutil.Process(self.parent_pid))
        self.interval = interval
        self.parent_peak_rss = self.workers_peak_rss = self.tree_peak_rss = 0
        self.cpu_by_pid = {}
        self._stop = threading.Event()

    @staticmethod
    def _cpu(process):
        cpu = process.cpu_times()
        return cpu.user + cpu.system

    def capture(self):
        try:
            parent = psutil.Process(self.parent_pid)
            processes = [parent] + parent.children(recursive=True)
        except (psutil.Error, OSError):
            return
        parent_rss = workers_rss = 0
        for process in processes:
            try:
                rss, cpu = process.memory_info().rss, self._cpu(process)
            except (psutil.Error, OSError):
                continue
            self.cpu_by_pid[process.pid] = max(self.cpu_by_pid.get(process.pid, 0.0), cpu)
            if process.pid == self.parent_pid:
                parent_rss = rss
            else:
                workers_rss += rss
        self.parent_peak_rss = max(self.parent_peak_rss, parent_rss)
        self.workers_peak_rss = max(self.workers_peak_rss, workers_rss)
        self.tree_peak_rss = max(self.tree_peak_rss, parent_rss + workers_rss)

    def start(self):
        self.capture()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            self.capture()

    def stop(self):
        self.capture()
        self._stop.set()
        self.thread.join()
        self.capture()
        parent_cpu = max(self.cpu_by_pid.get(self.parent_pid, self.parent_start_cpu) - self.parent_start_cpu, 0.0)
        workers_cpu = sum(cpu for pid, cpu in self.cpu_by_pid.items() if pid != self.parent_pid)
        return {
            "total_cpu_seconds": parent_cpu + workers_cpu,
            "parent_cpu_seconds": parent_cpu,
            "workers_cpu_seconds": workers_cpu,
            "peak_rss_process_tree_bytes": self.tree_peak_rss,
            "peak_rss_parent_bytes": self.parent_peak_rss,
            "peak_rss_workers_bytes": self.workers_peak_rss,
        }


class StageObserver:
    def __init__(self):
        self.timings = {}
        self._active = {}
        self._alias_depth = 0

    def __call__(self, event):
        now = time.perf_counter()
        if event.name == "begin_finalize":
            self._begin("finalization_total", now)
        elif event.name == "end_finalize":
            self._end("finalization_total", now)
        elif event.name == "begin_resolve_aliases":
            self._alias_depth += 1
            self._begin("alias_resolve_total", now)
        elif event.name == "end_resolve_aliases":
            self._end("alias_resolve_total", now)
            self._alias_depth -= 1
        elif event.name == "begin_sort":
            self._begin("sorting_inside_alias" if self._alias_depth else "sorting_outside_alias", now)
        elif event.name == "end_sort":
            self._end("sorting_inside_alias" if self._alias_depth else "sorting_outside_alias", now)

    def _begin(self, stage, now):
        self._active.setdefault(stage, []).append(now)

    def _end(self, stage, now):
        if self._active.get(stage):
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


def run_benchmark(output_dir, articles, jobs, chunksize, heavy=False, no_math=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = output_dir / "fixture-{}.jsonl".format(articles)
    output = output_dir / "output.slob"
    write_fixture(fixture, articles, heavy=heavy)
    info = Info("Benchmark", "en", False, "", "", "/wiki/", "https://benchmark.invalid")
    observer = StageObserver()
    timings = {}
    timed_articles = TimedArticles(fixture, info)
    sampler = ProcessTreeSampler()
    started = time.perf_counter()
    sampler.start()
    try:
        core.create_slob(
            str(output), info, timed_articles, workdir=str(output_dir), no_math=no_math,
            jobs=jobs, chunksize=chunksize, observer=observer, timings=timings,
            benchmark_timing=True, process_sampler=sampler,
        )
    finally:
        process_metrics = sampler.stop()
    total = time.perf_counter() - started
    result = {
        "articles": articles,
        "jobs": jobs if jobs is not None else "auto",
        "chunksize": chunksize,
        "heavy": heavy,
        "mathjax": not no_math,
        "total": total,
        "articles_per_second": articles / total if total else 0.0,
        "output_bytes": output.stat().st_size,
        "source_read": timed_articles.elapsed,
        "pool_startup": timings.get("pool_startup", 0.0),
        "html_conversion_aggregate_worker_seconds": timings.get("html_conversion_worker", 0.0),
        "writer_add": timings.get("writer_add", 0.0),
        "static_assets": timings.get("static_assets", 0.0),
        "sorting_outside_alias": observer.timings.get("sorting_outside_alias", 0.0),
        "sorting_inside_alias": observer.timings.get("sorting_inside_alias", 0.0),
        "alias_resolve_total": observer.timings.get("alias_resolve_total", 0.0),
        "finalization_total": observer.timings.get("finalization_total", 0.0),
        "pool_shutdown": timings.get("pool_shutdown", 0.0),
    }
    result["finalization_other"] = max(
        0.0, result["finalization_total"] - result["alias_resolve_total"]
        - result["sorting_outside_alias"],
    )
    result.update(process_metrics)
    # Aggregate worker CPU and wall-clock stages overlap, so the residual is
    # deliberately not claimed to be IPC overhead.
    result["unattributed_overhead"] = max(
        0.0, total - result["source_read"] - result["pool_startup"]
        - result["writer_add"] - result["static_assets"]
        - result["finalization_total"] - result["pool_shutdown"],
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
