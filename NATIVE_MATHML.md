# Native MathML experiment

This document describes the `native-mathml-experiment` branch only. Production
continues to use MathJax by default. The experiment is opt-in:

```text
python -m pip install -e ".[native-mathml]"
mw2slob dump --math-renderer native-mathml ...
```

`latex2mathml` converts `data-mw.body.extsrc` TeX during conversion and omits
the bundled MathJax directory when every formula in an article was converted.
If a formula cannot be converted, its original element is retained and the
MathJax/fallback path remains available for that article.

## Formula corpus

The regression corpus converts inline/display forms of: simple powers,
fractions, roots, matrices, sums, integrals, Greek/Unicode, and
`\operatorname` notation. It confirms generated MathML and absence of the
MathJax import for this supported corpus. This is structural coverage, not a
pixel-level browser rendering assessment. Texvc extensions beyond this subset
(for example chemistry `\ce{...}` and MediaWiki-specific macros) require a
real dictionary corpus plus visual validation before this mode can replace
MathJax.

## Local comparison

Windows, Python 3.11, 1,000 offline fixture articles, `jobs=2`, `chunksize=25`.
The fixture contains standard `data-mw.body.extsrc` formulae.

| metric | MathJax 4 | native MathML |
| --- | ---: | ---: |
| SLOB size | 2,695,416 B | 143,512 B |
| static assets | 2.422 s | 0.066 s |
| total build | 3.210 s | 0.854 s |
| aggregate HTML conversion CPU | 0.403 s | 0.481 s |
| peak process-tree RSS | 155 MiB | 141 MiB |
| browser/WebView article open | not measured | not measured |
| browser/WebView RAM | not measured | not measured |

The build and size benefits are substantial because MathJax assets dominate
this tiny fixture. Browser/WebView open time, RAM, and visual rendering were
not measured: this repository has no browser or Android WebView test harness.
They are required before a production decision. The experiment therefore does
not recommend removing MathJax.
