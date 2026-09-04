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

`tests/fixtures/mediawiki-math-corpus.json` is a real MediaWiki/texvc-shaped
compatibility corpus. Its supported set contains powers, fractions, roots,
matrices, sums, integrals, Greek/Unicode, and `\operatorname`, each in real
`data-mw.body.extsrc` form. Inline and MediaWiki display/block forms are
checked separately for `display="inline"` and `display="block"` in MathML.

The unsupported/fallback set deliberately includes mhchem `\ce{H2O}`, texvc
`\unicode`, `\bbox`, `\chem`, and nested `\cfrac`. These macros are excluded
before calling `latex2mathml`; the original math element, `data-tex`, MathJax
script and SLOB MathJax assets are retained. A mock-driven regression test
verifies this path independently of the converter's current behavior.

| result | formulas | share |
| --- | ---: | ---: |
| native success | 9 | 64.3% |
| MathJax fallback | 5 | 35.7% |
| conversion error | 0 | 0.0% |

Five of fourteen corpus formulae require the MathJax fallback. A dictionary
containing the complete corpus therefore requires MathJax assets (one of one
such SLOBs); a dictionary containing only the nine supported formulae does
not. This is structural coverage, not a pixel-level browser rendering
assessment.

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
