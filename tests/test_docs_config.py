"""The config on the hosting page stays in step with the one the repository ships.

`docs/host-a-server.md` embeds `includes/config-pointer.yml` as a complete pointer-serving
config. It is written out rather than copied from `config.yml` (which carries a
deployment's own storage roots), so these tests pin the parts that must agree: the shape
Tiled expects, and the adapter line a reader will paste.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SNIPPET = ROOT / "includes" / "config-pointer.yml"
SHIPPED = ROOT / "config.yml"
PAGE = ROOT / "docs" / "host-a-server.md"


def _load(path):
    return yaml.safe_load(path.read_text())


def test_the_page_embeds_the_snippet():
    assert '--8<-- "config-pointer.yml"' in PAGE.read_text()


def test_the_snippet_is_a_complete_tiled_config():
    cfg = _load(SNIPPET)
    assert set(cfg) == {"uvicorn", "trees"}
    assert set(cfg["uvicorn"]) == {"host", "port"}
    (tree,) = cfg["trees"]
    assert tree["path"] == "/" and tree["tree"] == "catalog"
    assert set(tree["args"]) == {"uri", "init_if_not_exists", "adapters_by_mimetype",
                                 "readable_storage"}
    assert tree["args"]["uri"].startswith("sqlite:///")
    assert tree["args"]["init_if_not_exists"] is True
    assert tree["args"]["readable_storage"]


def test_the_snippet_agrees_with_the_shipped_config():
    snippet, shipped = _load(SNIPPET), _load(SHIPPED)
    assert set(snippet) <= set(shipped)
    assert set(snippet["uvicorn"]) <= set(shipped["uvicorn"])
    (snippet_tree,), (shipped_tree,) = snippet["trees"], shipped["trees"]
    assert snippet_tree["path"] == shipped_tree["path"]
    assert snippet_tree["tree"] == shipped_tree["tree"]
    assert set(snippet_tree["args"]) <= set(shipped_tree["args"])
    assert (snippet_tree["args"]["adapters_by_mimetype"]
            == shipped_tree["args"]["adapters_by_mimetype"])


def test_the_adapter_target_is_importable():
    module, _, name = (_load(SNIPPET)["trees"][0]["args"]["adapters_by_mimetype"]
                       ["application/x-hdf5-broker"]).partition(":")
    assert getattr(__import__(module, fromlist=[name]), name)
