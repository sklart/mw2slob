# Performance baseline

`benchmarks/benchmark.py` builds an offline JSONL dump containing ordinary,
Unicode, alias, CSS-heavy and MathJax-like articles. It writes a JSON result
alongside the generated SLOB; no network service is used.

Run a baseline:

```text
python -m pip install -e ".[benchmark]"
python benchmarks/benchmark.py --articles 1000 --jobs 2 --chunksize 100 --output-dir benchmark-output
python benchmarks/benchmark.py --articles 10000 --heavy --jobs 2 --chunksize 100 --output-dir benchmark-heavy
python benchmarks/run_matrix.py --articles 1000 --output-dir benchmark-matrix
```

The matrix covers jobs `1`, `2`, `4`, and `auto` with chunksizes `10`, `25`,
`50`, `100`, `250`, and `500`. Commit neither generated fixture nor output.

## Measurements

The harness uses `psutil` to sample the parent process and every live worker
every 10 ms. It reports total CPU time and peak RSS for the complete process
tree, plus parent/worker splits. A worker that has exited remains represented
by its last sampled monotonic CPU value. These measurements are benchmark-only:
normal conversion neither calls timing functions nor sends timing values over
the multiprocessing queue.

Stages are source read, pool startup, aggregate worker HTML conversion, writer
`add`, static assets, finalization, and pool shutdown. `sorting_total` and
`alias_resolve_total` are nested within `finalization_total`; therefore they
must never be added to it. `finalization_other` is the non-overlapping
remainder. `unattributed_overhead` is only an explicitly unassigned wall-clock
residual, not a measurement of IPC overhead.

Full local matrix, Windows / Python 3.11 / MathJax enabled / 1,000 articles.
CPU and RSS cover the process tree; RSS is its peak. Results are rounded.

| jobs | chunksize | total, s | articles/s | CPU, s | peak RSS, MiB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 3.47 | 288 | 3.48 | 111 |
| 1 | 25 | 3.48 | 287 | 3.89 | 111 |
| 1 | 50 | 3.50 | 286 | 4.92 | 112 |
| 1 | 100 | 3.46 | 289 | 3.92 | 93 |
| 1 | 250 | 3.42 | 292 | 5.34 | 93 |
| 1 | 500 | 3.53 | 283 | 5.39 | 113 |
| 2 | 10 | 3.24 | 309 | 4.42 | 158 |
| 2 | 25 | 3.28 | 305 | 4.38 | 156 |
| 2 | 50 | 3.42 | 292 | 4.70 | 158 |
| 2 | 100 | 3.30 | 303 | 3.69 | 159 |
| 2 | 250 | 3.49 | 286 | 4.20 | 140 |
| 2 | 500 | 3.34 | 299 | 5.30 | 159 |
| 4 | 10 | 3.83 | 262 | 5.33 | 245 |
| 4 | 25 | 4.01 | 249 | 6.19 | 247 |
| 4 | 50 | 4.04 | 248 | 7.05 | 247 |
| 4 | 100 | 4.05 | 247 | 6.72 | 249 |
| 4 | 250 | 3.88 | 258 | 6.91 | 248 |
| 4 | 500 | 4.13 | 242 | 6.23 | 248 |
| auto | 10 | 3.78 | 265 | 12.16 | 757 |
| auto | 25 | 3.87 | 258 | 12.09 | 761 |
| auto | 50 | 4.01 | 249 | 12.44 | 741 |
| auto | 100 | 3.55 | 282 | 11.94 | 781 |
| auto | 250 | 3.95 | 253 | 12.45 | 785 |
| auto | 500 | 4.25 | 236 | 12.12 | 781 |

For this machine, `--jobs 2 --chunksize 25` is the recommended conservative
setting: it is within 1% of the fastest row (`2/10`), while avoiding a very
small task batch. Do not make it a project-wide default until this matrix has
been reproduced on a representative build host.

The confirmed bottlenecks are (1) HTML conversion, whose aggregate worker CPU
was 0.40–0.81 s per 1,000 articles; (2) process creation/memory pressure,
shown by `auto` reaching 741–785 MiB without throughput benefit; and (3)
finalization, where the measured total is about 0.17–0.26 s and includes
sorting, alias resolution, static assets and output assembly. These figures do
not prove an IPC bottleneck. No parser, compression, mmap, or codec change is
proposed without a before/after row containing baseline, speedup, RAM delta,
and output-size delta.

## Profiling

Install one profiler locally; neither belongs in CI:

```text
py-spy record -o profile.svg -- python benchmarks/benchmark.py --articles 10000 --heavy --jobs 2
scalene --cpu --memory benchmarks/benchmark.py --articles 1000 --heavy --jobs 1
```

Inspect `mw2slob/convert.py` (CSS/lxml), worker IPC, and `slob.Writer`
sorting/alias/finalization separately. CI runs only the five-article smoke
benchmark to ensure the harness remains executable.
