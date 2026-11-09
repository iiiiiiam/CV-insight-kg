"""Small, literal naming rules for abstracts; no model or per-paper answers."""

import re

VERSION = "explicit-names/0.1"
TOKEN = r"[A-Z0-9][A-Za-z0-9]*(?:[-./][A-Za-z0-9]+)*"
NAME = TOKEN + r"(?:\s+" + TOKEN + r"){0,2}"
INTRO = re.compile(r"\b(?:we|this paper)\s+(?:here\s+)?(?:introduce|propose|present|develop)\s+", re.I)
NAMING = re.compile(r"\b(?:named|called|termed|dubbed|namely)\s+", re.I)
GENERIC = {"a", "an", "the", "new", "novel", "first", "our", "model", "models", "method", "methods",
           "dataset", "datasets", "data", "public", "standard", "benchmark", "benchmarks", "existing",
           "three", "two", "four", "five", "several", "multiple", "challenging", "large", "large-scale"}
GENERIC |= {"this", "these", "those", "it", "its", "each", "some", "both"}


def _name(value):
    value = re.sub(r"\[[\d,\s]+\]", "", value).strip(" \t,:()\"'")
    value = re.sub(r"^(?:(?:the|a|an|both)\s+)+", "", value, flags=re.I)
    if (not re.fullmatch(NAME, value) or len(value) < 3 or not re.search(r"[A-Za-z]", value)
        or all(t.casefold() in GENERIC for t in value.split())
        or (value.isupper() and len(value) <= 3)):
        return None
    return value


def explicit_signals(paper):
    """Return names and matched naming sentences, not invented source annotations."""
    signals, seen = [], set()

    def add(kind, name, field, context, rule):
        if not name or (kind, name.casefold()) in seen:
            return
        if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", getattr(paper, field) or "") is None:
            return
        seen.add((kind, name.casefold()))
        signals.append(dict(kind=kind, name=name, alias=name, field=field, context=context, rule=rule))

    for field in ("title", "abstract"):
        text = getattr(paper, field) or ""
        # A title alone does not establish that a capitalized word is a method.
        if field == "abstract":
            for intro in INTRO.finditer(text):
                clause = re.split(r"[.;\n]", text[intro.end():intro.end() + 220], maxsplit=1)[0]
                direct = re.match(TOKEN + r"(?=\s*[,:(]|\s+(?:is|as|to|for|which)\b)", clause)
                if direct:
                    add("method", _name(direct.group()), field, intro.group() + clause, "introduced_name")
                naming = NAMING.search(clause)
                if naming:
                    tail = re.split(r",|\b(?:to|for|which|that)\b", clause[naming.end():], maxsplit=1)[0].strip()
                    kind = "task" if re.search(r"\b(?:task|problem)\s*$", clause[:naming.start()].strip(), re.I) else "method"
                    acronym = re.search(r"\((" + TOKEN + r")\)", tail)
                    value = acronym[1] if acronym and kind == "method" else tail.split("(", 1)[0].strip()
                    add(kind, _name(value), field, intro.group() + clause, "introduced_named_" + kind)

        patterns = (
            r"\b(?:on|using|including|like|such as|namely)\s+(?P<names>[^.;:\n]{1,160}?)\s+(?:benchmark\s+)?data\s*sets?\b",
            r"\bdata\s*sets?\s*(?:such as|like|including|named|called|:|\()\s*(?P<names>[^.;\n)]{1,160})",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                for part in re.split(r",|\band\b|&", match["names"]):
                    add("dataset", _name(part), field, match.group(), "explicit_dataset_list")
        # An individually named dataset; initial uppercase is deliberately literal.
        for match in re.finditer(r"(?<![\w-])(" + NAME + r")\s+(?:dataset|data set|corpus)\b", text):
            add("dataset", _name(match[1]), field, match.group(), "explicit_dataset_name")
    return signals
