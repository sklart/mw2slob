"""Run the documented multiprocessing matrix without using network input."""

import argparse
from pathlib import Path

from benchmark import run_benchmark


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=int, default=1000, choices=(1000, 10000))
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-matrix"))
    args = parser.parse_args()
    for jobs in (1, 2, 4, None):
        for chunksize in (10, 25, 50, 100, 250, 500):
            name = "jobs-{}-chunk-{}".format(jobs or "auto", chunksize)
            result = run_benchmark(args.output_dir / name, args.articles, jobs, chunksize)
            print("{}: {:.1f} articles/s".format(name, result["articles_per_second"]))


if __name__ == "__main__":
    main()
