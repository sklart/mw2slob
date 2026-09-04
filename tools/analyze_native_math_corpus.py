"""Classify a saved Parsoid formula corpus through the full convert pipeline."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from mw2slob import convert

COMMAND = re.compile(r"\\([A-Za-z]+)")


def convert_element(element):
    params = convert.ConvertParams(
        "Corpus", (), "<html><body>{}</body></html>".format(element), False,
        "https://en.wikipedia.org", "/wiki/", "/wiki/", "utf-8", "", False,
    )
    return convert.convert(params, (), {}, {}, "native-mathml").decode("utf-8")


def analyze(records):
    totals = {"total_formulas": 0, "native_success": 0, "mathjax_fallback": 0, "conversion_errors": 0}
    article_fallback = defaultdict(bool)
    fallback_reasons = defaultdict(int)
    articles = set()
    for record in records:
        totals["total_formulas"] += 1
        articles.add(record["article"])
        try:
            result = convert_element(record["html"])
        except Exception:
            totals["conversion_errors"] += 1
            article_fallback[record["article"]] = True
        else:
            if convert.MATH_JAX_SCRIPTS in result:
                totals["mathjax_fallback"] += 1
                article_fallback[record["article"]] = True
                command = COMMAND.search(record["tex"])
                fallback_reasons[command.group(1) if command else "unclassified"] += 1
            elif "<math" in result:
                totals["native_success"] += 1
            else:
                totals["conversion_errors"] += 1
                article_fallback[record["article"]] = True
    total = totals["total_formulas"]
    totals["native_success_percent"] = round(100 * totals["native_success"] / total, 2)
    totals["mathjax_fallback_percent"] = round(100 * totals["mathjax_fallback"] / total, 2)
    totals["conversion_errors_percent"] = round(100 * totals["conversion_errors"] / total, 2)
    totals["articles_total"] = len(articles)
    totals["articles_requiring_fallback"] = sum(article_fallback.values())
    totals["articles_fully_native"] = len(articles) - totals["articles_requiring_fallback"]
    totals["dictionaries_requiring_mathjax"] = 1 if totals["articles_requiring_fallback"] else 0
    totals["dictionaries_without_mathjax"] = 1 - totals["dictionaries_requiring_mathjax"]
    totals["top_fallback_reasons"] = dict(sorted(
        fallback_reasons.items(), key=lambda item: (-item[1], item[0]))[:10])
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("tests/fixtures/mediawiki-parsoid-math.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/mediawiki-parsoid-math-stats.json"))
    args = parser.parse_args()
    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()]
    args.output.write_text(json.dumps(analyze(records), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
