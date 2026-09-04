"""Extract a resumable native-MathML corpus from a local Parsoid/Enterprise dump.

Input may be JSONL records containing ``name`` + ``article_body.html`` (the
Wikimedia Enterprise shape), ``title`` + ``html``, or standalone HTML files.
No network is used. Existing output is read first so completed articles and
duplicate formulae are skipped deterministically.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from lxml import html


def formula_id(article, tex, element_html):
    value = "\0".join((article, tex, element_html)).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def existing_state(output):
    articles, formulae = set(), set()
    if not output.exists():
        return articles, formulae
    for line in output.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        articles.add(record["article"])
        formulae.add(record.get("id") or formula_id(record["article"], record["tex"], record["html"]))
    return articles, formulae


def records(path):
    if path.suffix.lower() in (".html", ".htm"):
        yield path.stem, path.read_text(encoding="utf-8"), str(path)
        return
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            data = json.loads(line)
            article = data.get("name") or data.get("title") or "{}:{}".format(path.name, number)
            content = data.get("article_body", {}).get("html") or data.get("html")
            if content:
                yield article, content, str(path)


def extract(inputs, output, per_article_limit):
    done_articles, seen_formulae = existing_state(output)
    stats = Counter(skipped_articles=len(done_articles), duplicates=0, formulas=0, articles=0)
    with output.open("a", encoding="utf-8", newline="\n") as target:
        for input_path in inputs:
            for article, source_html, source_id in records(input_path):
                if article in done_articles:
                    continue
                document = html.fromstring(source_html)
                emitted = 0
                for element in document.cssselect("span.mwe-math-element"):
                    try:
                        tex = json.loads(element.attrib.get("data-mw", ""))["body"]["extsrc"]
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
                    original = html.tostring(element, encoding="unicode")
                    identifier = formula_id(article, tex, original)
                    if identifier in seen_formulae:
                        stats["duplicates"] += 1
                        continue
                    classes = element.attrib.get("class", "").split()
                    record = {
                        "id": identifier, "article": article, "source": source_id,
                        "html": original, "tex": tex,
                        "display": "block" if "mwe-math-element-block" in classes else "inline",
                    }
                    target.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    seen_formulae.add(identifier)
                    emitted += 1
                    stats["formulas"] += 1
                    if emitted >= per_article_limit:
                        break
                done_articles.add(article)
                stats["articles"] += 1
                target.flush()
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/local-parsoid-math.jsonl"))
    parser.add_argument("--per-article-limit", type=int, default=60)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(extract(args.inputs, args.output, args.per_article_limit), sort_keys=True))


if __name__ == "__main__":
    main()
