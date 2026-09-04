"""Run the documented multiprocessing matrix without using network input."""

import argparse
import json
from pathlib import Path

from benchmark import run_benchmark


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=int, default=1000, choices=(1000, 10000))
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-matrix"))
    parser.add_argument("--jobs", action="append", choices=("1", "2", "4", "auto"),
                        help="Run only these job-count rows (repeatable)")
    args = parser.parse_args()
    results = []
    job_values = {"1": 1, "2": 2, "4": 4, "auto": None}
    selected = args.jobs or ("1", "2", "4", "auto")
    for jobs in (job_values[value] for value in selected):
        for chunksize in (10, 25, 50, 100, 250, 500):
            name = "jobs-{}-chunk-{}".format(jobs or "auto", chunksize)
            result = run_benchmark(args.output_dir / name, args.articles, jobs, chunksize)
            results.append(result)
            print("{}: {:.1f} articles/s".format(name, result["articles_per_second"]))
    (args.output_dir / "matrix.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
