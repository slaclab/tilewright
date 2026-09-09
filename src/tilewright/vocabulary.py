"""The soft vocabulary: canonical ids and aliases for the dataset-level facets.

``vocabulary.yml`` lists, per facet, the ids we key discovery on and the aliases people
actually type. ``resolve_aliases`` rewrites an alias to its id (``EDRIXS`` -> ``RIXS``,
``nips3`` -> ``NiPS3``); ``check`` warns about a value on no list. A warning never blocks onboarding (ADR-0003): the dataset registers with
the value as written, and ``scripts/vocab_report.py`` shows what is off-list on a server so
a person can promote it by pull request.

Works on plain dicts so it can run before the contract models see the metadata.
"""

from pathlib import Path

from ruamel.yaml import YAML

# metadata key -> facet list in vocabulary.yml
FACETS = {
    "method": "methods",
    "data_type": "data_types",
    "material": "materials",
    "producer": "producers",
    "facility": "facilities",
    "project": "projects",
    "proposal": "proposals",
}


def load_vocabulary():
    """The bundled vocabulary as a dict of facet -> list of entries."""
    with open(Path(__file__).parent / "vocabulary.yml") as f:
        return YAML(typ="safe").load(f) or {}


def alias_map(vocab, facet):
    """``{alias: canonical id}`` for one facet list."""
    return {alias: entry["id"]
            for entry in vocab.get(facet) or []
            for alias in entry.get("aliases") or []}


def resolve_aliases(metadata, vocab):
    """Rewrite aliases in ``metadata`` (a dict, mutated in place) to canonical ids.

    Returns informational messages, one per rewrite. A facet that holds a list
    (``method``) is rewritten element-wise. Nothing else in the metadata is touched.
    """
    messages = []
    if not isinstance(metadata, dict):
        return messages
    for field, facet in FACETS.items():
        aliases = alias_map(vocab, facet)
        value = metadata.get(field)
        if value is None or not aliases:
            continue
        values = value if isinstance(value, list) else [value]
        resolved = []
        for v in values:
            canonical = aliases.get(v)
            if canonical is None:
                resolved.append(v)
                continue
            resolved.append(canonical)
            messages.append(f"metadata.{field}: alias '{v}' -> '{canonical}'")
        metadata[field] = resolved if isinstance(value, list) else resolved[0]
    return messages


def check(metadata, vocab):
    """Warnings for facet values on no list. Never raises."""
    warnings = []
    for field, facet in FACETS.items():
        entries = vocab.get(facet) or []
        if not entries:
            continue
        accepted = {e["id"] for e in entries} | set(alias_map(vocab, facet))
        value = metadata.get(field)
        if value is None:
            continue
        for v in (value if isinstance(value, list) else [value]):
            if v not in accepted:
                warnings.append(f"metadata.{field} '{v}' is not in the vocabulary; it is "
                                f"registered as written (known: "
                                f"{', '.join(sorted(e['id'] for e in entries))})")
    return warnings
