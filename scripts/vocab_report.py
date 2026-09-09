"""Which metadata values on a live server are not in the vocabulary.

Maintainer tool for the vocab-review skill (.claude/skills/vocab-review). Reads only; the
decisions (alias or new id, label, implies) are a person's, made in a pull request.

    uv run scripts/vocab_report.py --url <URL> --api-key <KEY>

Asks the server for the distinct values of each facet across the dataset containers with
Tiled's ``distinct`` query (one request per facet, answered from the catalog database),
diffs them against src/tilewright/vocabulary.yml, and prints the off-list values with how
many datasets carry each and one example key.
"""

import argparse
import os
import sys

from tiled.client import from_uri
from tiled.queries import Contains, Key

from tilewright.vocabulary import FACETS, alias_map, load_vocabulary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default=os.environ.get("TILED_URL", "http://localhost:8005"))
    parser.add_argument("--api-key", default=os.environ.get("TILED_API_KEY", ""))
    args = parser.parse_args(argv)

    client = from_uri(args.url, api_key=args.api_key)
    vocab = load_vocabulary()
    rows = []
    for field, facet in FACETS.items():
        known = {e["id"] for e in vocab.get(facet) or []} | set(alias_map(vocab, facet))
        try:
            counts = client.distinct(field, counts=True)["metadata"].get(field, [])
        except Exception as e:  # a facet nobody has used yet, or an old server
            print(f"  ({field}: distinct query failed: {e})", file=sys.stderr)
            continue
        for item in counts:
            values = item["value"] if isinstance(item["value"], list) else [item["value"]]
            for value in values:
                if value is None or value in known:
                    continue
                rows.append((field, str(value), item["count"]))
    if not rows:
        print("Every facet value on the server is in the vocabulary.")
        return 0

    # One example dataset per off-list value, found by query, not by walking.
    print(f"{'facet':10} {'value':40} {'datasets':>8}  example")
    for field, value, count in sorted(rows):
        example = "?"
        for query in (Key(field) == value, Contains(field, value)):
            try:
                example = next(iter(client.search(query).keys()))
                break
            except (StopIteration, Exception):
                continue
        print(f"{field:10} {value[:40]:40} {count:>8}  {example}")
    print(f"\n{len(rows)} off-list values across {len({r[0] for r in rows})} facets. "
          f"Decide alias / new id / leave for each; see .claude/skills/vocab-review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
