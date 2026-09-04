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
from urllib.error import HTTPError

from lxml import html


PAGES = (
    "Mathematics", "Calculus", "Integral", "Derivative", "Linear algebra",
    "Matrix (mathematics)", "Mathematical notation", "Fourier transform",
    "Partial differential equation", "Schrödinger equation", "Maxwell's equations",
    "General relativity", "Quantum mechanics", "Probability theory", "Set theory",
    "Number theory", "Complex analysis", "Tensor calculus", "Trigonometric functions",
    "Statistical mechanics", "Differential geometry", "Group theory",
)


def page_html(title):
    url = "https://en.wikipedia.org/api/rest_v1/page/html/" + quote(title, safe="")
    request = Request(url, headers={"User-Agent": "mw2slob-native-mathml-corpus/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def collect(output, limit):
    count = 0
    with output.open("w", encoding="utf-8", newline="\n") as target:
        for title in PAGES:
            try:
                document = html.fromstring(page_html(title))
            except HTTPError as error:
                print("skipping", title, "HTTP", error.code)
                if error.code == 429:
                    time.sleep(5)
                continue
            for element in document.cssselect("span.mwe-math-element"):
                data_mw = element.attrib.get("data-mw", "")
                try:
                    tex = json.loads(data_mw)["body"]["extsrc"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                target.write(json.dumps({
                    "source": "https://en.wikipedia.org/api/rest_v1/page/html/" + quote(title, safe=""),
                    "article": title,
                    "html": html.tostring(element, encoding="unicode"),
                    "tex": tex,
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
                if count >= limit:
                    return count
            time.sleep(1)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/mediawiki-parsoid-math.jsonl"))
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print("collected", collect(args.output, args.limit), "formulae")


if __name__ == "__main__":
    main()
