"""The annotated example YAMLs are part of the contract surface: each must validate with
no vocabulary warning, since they are what producers copy, and each must use the source
tag its filename promises."""

import re
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


def test_commented_params_in_the_files_example_validate():
    """Each '# params: ...' line in files.yml is an alternative an author uncomments."""
    path = next(p for p in EXAMPLES if p.stem == "files")
    lines = re.findall(r"^\s*# (params: .*?)(?:\s+#.*)?$", path.read_text(), flags=re.M)
    assert any("location:" in line for line in lines)
    for line in lines:
        raw = YAML(typ="safe").load(path.read_text())
        raw["source"]["files"].update(YAML(typ="safe").load(line))
        cfg, warnings = load_dataset(raw)
        assert warnings == [], line
        if cfg.source.body.params is not None and cfg.source.body.params.location:
            match = re.search(cfg.source.body.params.location, "run_0001.h5")
            assert match and match.groupdict() == {"run": "0001"}
