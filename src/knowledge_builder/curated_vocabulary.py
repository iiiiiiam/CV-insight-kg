"""Small reusable CV fallback; the frozen first-week vocabulary stays unchanged."""

import json
import re
from copy import deepcopy
from pathlib import Path

from .extraction import validate_vocabulary

PATH = Path(__file__).with_name("vocabulary_cv.json")


def load_curated_vocabulary():
    vocabulary = json.loads(PATH.read_text(encoding="utf-8"))
    validate_vocabulary(vocabulary)
    for term in vocabulary["terms"]:
        if not term.get("source_url", "").startswith("https://"):
            raise ValueError("Curated CV terms require a public reference")
    return vocabulary


def merge_curated_vocabulary(vocabulary, paper=None):
    """Existing/feedback identities win; conflicting aliases are not overwritten."""
    merged = deepcopy(vocabulary)
    curated = load_curated_vocabulary()
    aliases = {a.casefold(): t for t in merged["terms"] for a in t["aliases"]}
    traces = []
    for term in curated["terms"]:
        target = next((t for t in merged["terms"] if t["kind"] == term["kind"]
                       and (t["key"] == term["key"] or t["name"].casefold() == term["name"].casefold())), None)
        for alias in term["aliases"]:
            if paper is not None and alias in term.get("case_sensitive_aliases", []):
                if not any(re.search(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", text or "")
                           for text in (paper.title, paper.abstract)):
                    continue
            existing = aliases.get(alias.casefold())
            if existing is not None:
                if existing["kind"] != term["kind"] or (target is not None and target is not existing):
                    continue
                target = existing
            elif target is None:
                target = dict(key=term["key"], kind=term["kind"], name=term["name"], aliases=[alias])
                merged["terms"].append(target)
            else:
                target["aliases"].append(alias)
            aliases[alias.casefold()] = target
            traces.append(dict(key=target["key"], kind=target["kind"], name=target["name"], alias=alias,
                               source_url=term["source_url"]))
    validate_vocabulary(merged)
    return merged, traces
