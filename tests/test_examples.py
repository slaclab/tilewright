"""The annotated example YAMLs are part of the contract surface: each must validate with
no vocabulary warning, since they are what producers copy, and each must use the source
tag its filename promises."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from tilewright.contract import load_dataset

EXAMPLES = sorted((Path(__file__).parent.parent / "examples" / "datasets").glob("*.yml"))


def test_one_example_per_source_tag():
    assert {"files", "batch", "groups", "table"} <= {p.stem.split("_")[0] for p in EXAMPLES}


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_validates_with_no_warnings(path):
    with open(path) as f:
        raw = YAML().load(f)
    cfg, warnings = load_dataset(raw)
    assert warnings == [], f"{path.name}: {warnings}"
    assert path.stem.startswith(cfg.source.tag)
    assert raw.get("key") == cfg.catalog_key, "examples carry the key manifest would write"
