# Performance baseline

`benchmarks/benchmark.py` builds an offline JSONL dump containing ordinary,
Unicode, alias, CSS-heavy and MathJax-like articles. It writes a JSON result
alongside the generated SLOB; no network service is used.

Run a baseline:

```text
python benchmarks/benchmark.py --articles 1000 --jobs 2 --chunksize 100 --output-dir benchmark-output
python benchmarks/benchmark.py --articles 10000 --heavy --jobs 2 --chunksize 100 --output-dir benchmark-heavy
python benchmarks/run_matrix.py --articles 1000 --output-dir benchmark-matrix
```

The matrix covers jobs `1`, `2`, `4`, and `auto` with chunksizes `10`, `25`,
`50`, `100`, `250`, and `500`. Commit neither generated fixture nor output.

## Measurements

The harness reports wall-clock total, articles/sec, process CPU seconds, peak
RSS when supported (Linux/macOS), Python traced peak memory, output size, and
these stages: source read, aggregate worker HTML conversion, writer `add`,
sorting, alias resolution, finalization, and a derived multiprocessing/IPC
overhead estimate. Worker conversion time is aggregate work across processes;
it must not be compared directly to wall-clock time for multi-worker runs.

Local baseline, Windows / Python 3.11 / MathJax enabled / 1,000 articles:

| jobs | chunksize | total | articles/s | output |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 100 | 5.35 s | 187 | 2.70 MB |
| 2 | 100 | 3.29 s | 304 | 2.70 MB |
| 4 | 100 | 3.23 s | 309 | 2.70 MB |
| auto | 100 | 3.86 s | 259 | 2.70 MB |
| 2, heavy | 100 | 19.21 s / 10,000 | 521 | 3.14 MB |

For this machine, `--jobs 2 --chunksize 100` is the conservative default:
it is close to the best observed throughput without the extra worker pressure
of four processes. Re-run the full matrix on the target machine before making
defaults platform-wide.

The initial measurements show finalization (including bundled MathJax assets),
multiprocessing/IPC, and HTML conversion as the three largest areas to inspect.
No parser, compression, mmap, or codec change is proposed without a before/
after row containing baseline, speedup, RAM delta, and output-size delta.

## Profiling

Install one profiler locally; neither belongs in CI:

```text
py-spy record -o profile.svg -- python benchmarks/benchmark.py --articles 10000 --heavy --jobs 2
scalene --cpu --memory benchmarks/benchmark.py --articles 1000 --heavy --jobs 1
```

Inspect `mw2slob/convert.py` (CSS/lxml), worker IPC, and `slob.Writer`
sorting/alias/finalization separately. CI runs only the five-article smoke
benchmark to ensure the harness remains executable.
