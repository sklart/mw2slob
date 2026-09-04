"""Collect a reproducible sample of real Parsoid math elements from Wikimedia.

The generated JSONL deliberately stores the original ``mwe-math-element``
HTML, including ``data-mw.body.extsrc`` and MediaWiki's real inline/block
classes. It is committed as a test fixture; this script is not used in CI.
"""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from lxml import html


PAGES = (
    ("mathematics", "Mathematics"), ("mathematics", "Calculus"), ("mathematics", "Integral"),
    ("mathematics", "Derivative"), ("mathematics", "Linear algebra"), ("mathematics", "Matrix (mathematics)"),
    ("mathematics", "Mathematical notation"), ("mathematics", "Fourier transform"),
    ("mathematics", "Partial differential equation"), ("mathematics", "Number theory"),
    ("mathematics", "Complex analysis"), ("mathematics", "Tensor calculus"),
    ("mathematics", "Trigonometric functions"), ("mathematics", "Differential geometry"),
    ("mathematics", "Group theory"), ("mathematics", "Topology"), ("mathematics", "Combinatorics"),
    ("physics", "Schrödinger equation"), ("physics", "Maxwell's equations"),
    ("physics", "General relativity"), ("physics", "Quantum mechanics"), ("physics", "Statistical mechanics"),
    ("physics", "Electromagnetism"), ("physics", "Classical mechanics"), ("physics", "Thermodynamics"),
    ("physics", "Quantum field theory"), ("physics", "Special relativity"),
    ("chemistry", "Chemical equation"), ("chemistry", "Chemical reaction"),
    ("chemistry", "Stoichiometry"), ("chemistry", "Chemical kinetics"), ("chemistry", "Acid-base reaction"),
    ("astronomy", "Celestial mechanics"), ("astronomy", "Orbital mechanics"),
    ("astronomy", "Cosmology"), ("astronomy", "Stellar evolution"), ("astronomy", "Black hole"),
    ("engineering", "Control theory"), ("engineering", "Signal processing"),
    ("engineering", "Electrical engineering"), ("engineering", "Fluid mechanics"),
    ("engineering", "Structural engineering"), ("statistics", "Probability theory"),
    ("statistics", "Mathematical statistics"), ("statistics", "Regression analysis"),
    ("statistics", "Bayesian inference"), ("statistics", "Stochastic process"),
    ("linguistics", "Formal language"), ("linguistics", "Generative grammar"),
    ("linguistics", "Phonology"), ("linguistics", "International Phonetic Alphabet"),
    ("legacy-texvc", "Help:Displaying a formula"), ("legacy-texvc", "TeX"),
    ("legacy-texvc", "Mathematical markup"),
)


def page_html(title):
    url = "https://en.wikipedia.org/w/rest.php/v1/page/" + quote(title, safe="") + "/html"
    request = Request(url, headers={"User-Agent": "mw2slob-native-mathml-corpus/1.0"})
    with urlopen(request, timeout=5) as response:
        return response.read()


def collect(output, limit, min_articles, per_article_limit, max_pages):
    seen_articles = set()
    count = 0
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            seen_articles.add(record["article"])
            count += 1
    with output.open("a", encoding="utf-8", newline="\n") as target:
        processed_pages = 0
        for category, title in PAGES:
            if title in seen_articles:
                continue
            if max_pages and processed_pages >= max_pages:
                return count
            try:
                document = html.fromstring(page_html(title))
            except (HTTPError, URLError, TimeoutError) as error:
                code = getattr(error, "code", None)
                print("skipping", ascii(title), "HTTP" if code else type(error).__name__, code or "")
                if code == 429:
                    time.sleep(5)
                continue
            article_count = 0
            for element in document.cssselect("span.mwe-math-element"):
                data_mw = element.attrib.get("data-mw", "")
                try:
                    tex = json.loads(data_mw)["body"]["extsrc"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                target.write(json.dumps({
                    "category": category,
                    "source": "https://en.wikipedia.org/w/rest.php/v1/page/" + quote(title, safe="") + "/html",
                    "article": title,
                    "html": html.tostring(element, encoding="unicode"),
                    "tex": tex,
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
                article_count += 1
                target.flush()
                if article_count >= per_article_limit:
                    break
            seen_articles.add(title)
            processed_pages += 1
            if count >= limit and len(seen_articles) >= min_articles:
                return count
            time.sleep(1)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/mediawiki-parsoid-math.jsonl"))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--min-articles", type=int, default=1)
    parser.add_argument("--per-article-limit", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=0,
                        help="Stop after this many new pages so rate-limited runs can resume")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print("collected", collect(args.output, args.limit, args.min_articles,
                               args.per_article_limit, args.max_pages), "formulae")


if __name__ == "__main__":
    main()
