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

## Real MediaWiki compatibility corpus

The production-readiness source of truth is a local Enterprise/Parsoid dump:
`tools/extract_local_parsoid_math_corpus.py DUMP.jsonl --per-article-limit 60`.
It accepts Enterprise `name` + `article_body.html` JSONL or standalone HTML,
stores original math HTML/TeX/inline-block metadata, deduplicates formulae,
and resumes by skipping articles already written. REST collection remains only
an optional seed (`tools/collect_wikimedia_math_corpus.py`) because Wikimedia
rate limits make it unsuitable for the 3,000–5,000 formula production sample.
Run `tools/analyze_native_math_corpus.py` after extraction to produce full
pipeline totals and top fallback commands.

Android/WebView visual validation is **blocked by environment**: this host has
no `adb` or Android emulator. It remains a separate acceptance block; the
production MathJax default is unchanged.

`tests/fixtures/mediawiki-parsoid-math.jsonl` currently contains 1,506 original
`span.mwe-math-element` fragments collected from public Wikimedia Parsoid HTML
endpoints. Each record retains its source URL, article title, original HTML and
`data-mw.body.extsrc`; `tools/collect_wikimedia_math_corpus.py` reproduces the
collection without running in CI. The corpus includes actual
`mwe-math-element-inline` and `mwe-math-element-block` fixtures.

`tools/analyze_native_math_corpus.py` runs every stored fragment through
`convert()` with `native-mathml` — it does not call `native_mathml()` directly.
The current committed result is:

| result | formulas | share |
| --- | ---: | ---: |
| native success | 1,445 | 95.95% |
| MathJax fallback | 61 | 4.05% |
| conversion error | 0 | 0.00% |

This REST seed spans 35 source articles: 14 require a fallback and 21 are
fully native. It remains below the production-readiness target of 3,000–5,000
formulae and 50+ articles; the local-dump extractor above is the required path
to finish that sample. The complete seed as one dictionary therefore requires
MathJax assets (1/1 dictionaries), while its all-native source-article subsets
can be built without them. The most frequent fallback commands are `begin`
(33) and `ce` (18). Real inline/block fixtures are checked through the
full `convert()` path, and a `jobs=1` end-to-end SLOB test builds an actual
`\ce{H2O}` fallback article and verifies its MathJax assets.

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
