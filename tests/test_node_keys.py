"""Which artifact types a Tiled server serves back (#23, ADR-0012).

An artifact's ``type`` is its node key, and the Tiled client puts that key into a URL. The
offline tests pin the contract's rule on the samples below. The integration test
(``pytest -m integration tests/test_node_keys.py``; it starts its own ``tiled serve`` of
the pinned version, so no server is needed beforehand) registers every sample through
both transports and checks that the server serves back exactly the ones the rule accepts.

Run with: uv run --extra test pytest tests/test_node_keys.py -m ''
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from ruamel.yaml import YAML

from tilewright.contract import (
    TYPE_RULE, ArtifactSpec, ContractError, key_problem, load_dataset,
)
from tilewright.manifest import generate_manifests

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3"}

# Served back by a local server, through both transports and both read paths.
SERVED = [
    "spectrum", "a.b", "stage.x.y", "a-b", "-lead", "a|b", "_lead", "__lead", ".lead", "a.",
    "...", "a..b", "a b", " lead", "trail ", "  ", "a[0]", "len [mm]", "énergie", "µ", "温度",
    "e\u0301", "a\u00a0b", "a\u200bb", "a\x9fb", "a%", "%zz", "a%2", "a%2g", "a&b", "a=b",
    "a+b", "a:b", "a;b", "a,b", "a\\b", "a'b", 'a"b', "a*b", "a~b", "a!b", "a@b", "a$b",
    "a^b", "a`b", "a{b}", "a<b>", "a(b)", "123", "x" * 200,
]
# Registered (pointer) or refused (upload), and never served back.
NOT_SERVED = {
    "a/b": "contains '/', which separates the keys of a path",
    "/lead": "contains '/', which separates the keys of a path",
    "trail/": "contains '/', which separates the keys of a path",
    "a?b": "contains '?', which starts the query of a URL",
    "a#b": "contains '#', which starts the fragment of a URL",
    "a\tb": "contains the control character '\\t', which a URL cannot hold",
    "a\nb": "contains the control character '\\n', which a URL cannot hold",
    "a\x01b": "contains the control character '\\x01', which a URL cannot hold",
    "a\x7fb": "contains the control character '\\x7f', which a URL cannot hold",
    "a%20b": "contains '%20', which a URL reads as an escaped character",
    "a%2Fb": "contains '%2F', which a URL reads as an escaped character",
    "a%2fb": "contains '%2f', which a URL reads as an escaped character",
    "%41": "contains '%41', which a URL reads as an escaped character",
    ".": "is a dot segment, which a URL reads as a node or its parent",
    "..": "is a dot segment, which a URL reads as a node or its parent",
}


def refusal(key):
    return (f"type {key!r} {NOT_SERVED[key]}; {TYPE_RULE}. Change the type (a '_' instead, "
            f"say)")


def dataset_cfg(artifacts, shared=()):
    return {"label": "Keys", "metadata": dict(META),
            "source": {"files": {"directory": "/d"}},
            "artifacts": artifacts, "shared": list(shared)}


def errors_of(raw):
    with pytest.raises(ContractError) as exc:
        load_dataset(raw)
    return exc.value.errors


# ---------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", SERVED)
def test_the_contract_accepts_a_type_the_server_serves(key):
    assert key_problem(key) is None
    cfg, _ = load_dataset(dataset_cfg([{"type": key, "dataset": "/x"}],
                                      [{"type": f"axis {key}", "dataset": "/e"}]))
    assert cfg.artifacts[0].type == key


@pytest.mark.parametrize("key", NOT_SERVED)
def test_the_contract_refuses_a_type_the_server_does_not_serve(key):
    assert errors_of(dataset_cfg([{"type": key, "dataset": "/x"}],
                                 [{"type": key, "dataset": "/e"}])) == [
        f"artifacts[0]: {refusal(key)}", f"shared[0]: {refusal(key)}"]


def test_a_group_template_is_checked_on_its_own_text():
    assert errors_of(dataset_cfg([{"type": "a#{name}", "group": "/g"}])) == [
        "artifacts[0]: type 'a#{name}' contains '#', which starts the fragment of a URL; "
        f"{TYPE_RULE}. Change the type (a '_' instead, say)"]
    # '%4' and '{name}' can make '%41' only with a member's name: the manifest decides
    for template in ("%4{name}", "{name}", ".{name}", "{name}%"):
        load_dataset(dataset_cfg([{"type": template, "group": "/g"}]))


def test_the_type_description_states_the_rule():
    doc = ArtifactSpec.model_fields["type"].description
    for text in ("'/', '?', '#', an ASCII control character (tab, newline) and a '%' "
                 "followed by two hex digits ('%20')", "may not be '.' or '..'",
                 "so the server would not serve such an array back",
                 "a leading '_' or '.'", "a dot does not nest the locators", "255 bytes"):
        assert text in doc
    assert "never serve it back" not in doc  # with --upload, registration fails instead


# ---------------------------------------------------------------------------
# the manifest: a group entry's types exist only once it is expanded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template, member, key", [
    ("{name}", "..", ".."), ("{name}", "a?b", "a?b"), ("%4{name}", "1", "%41"),
    ("t_{name}", "a\tb", "t_a\tb"),
])
def test_a_member_whose_type_would_not_be_served_is_named(tmp_path, template, member, key):
    d = tmp_path / "data"
    d.mkdir()
    with h5py.File(d / "e.h5", "w") as f:
        f["run"] = 1
        f["traces/ok"] = np.zeros(3)
        f[f"traces/{member}"] = np.zeros(3)
    raw = dataset_cfg([{"type": template, "group": "/traces"}])
    raw["source"]["files"]["directory"] = str(d)
    yaml_path = tmp_path / "ds.yml"
    with open(yaml_path, "w") as fh:
        YAML().dump(raw, fh)
    with pytest.raises(ValueError) as exc:
        generate_manifests(str(yaml_path), tmp_path / "m")
    problem = key_problem(key)
    assert problem is not None
    assert str(exc.value) == (
        f"{d / 'e.h5'}: artifact type={template!r} group '/traces': the member {member!r} "
        f"gives the type {key!r}, and that type {problem}; {TYPE_RULE}. Leave the member "
        f"out with 'members', or rename it in the file")
    raw["artifacts"][0]["members"] = "ok"
    with open(yaml_path, "w") as fh:
        YAML().dump(raw, fh)
    _, art_path = generate_manifests(str(yaml_path), tmp_path / "m")
    assert list(pd.read_parquet(art_path)["type"]) == [template.format(name="ok")]


# ---------------------------------------------------------------------------
# the server (integration): exactly the types the contract accepts come back
# ---------------------------------------------------------------------------

WANT = np.arange(3.0)


@pytest.fixture(scope="module")
def local_server(tmp_path_factory):
    """A `tiled serve` of the installed Tiled on a free local port, with the TileWright
    adapter, reading from ``data`` and storing uploads in ``storage``."""
    root = tmp_path_factory.mktemp("tiled")
    data, storage = root / "data", root / "storage"
    data.mkdir()
    storage.mkdir()
    with h5py.File(data / "e.h5", "w") as f:
        f["x"] = WANT
        f["run"] = 1
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (root / "config.yml").write_text(
        f"uvicorn: {{host: 127.0.0.1, port: {port}}}\n"
        "trees:\n  - path: /\n    tree: catalog\n    args:\n"
        f"      uri: 'sqlite:///{root}/catalog.db'\n      init_if_not_exists: true\n"
        f"      writable_storage: '{storage}'\n      readable_storage: ['{data}']\n"
        "      adapters_by_mimetype:\n"
        "        application/x-hdf5-broker: 'tilewright.adapter:LazyHDF5ArrayAdapter'\n")
    tiled = shutil.which("tiled", path=str(Path(sys.executable).parent)) or "tiled"
    log = open(root / "server.log", "w")
    proc = subprocess.Popen([tiled, "serve", "config", str(root / "config.yml"),
                             "--api-key", "secret"], cwd=root, stdout=log,
                            stderr=subprocess.STDOUT, env={**os.environ})
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if proc.poll() is not None:
                pytest.fail(f"tiled serve exited: {(root / 'server.log').read_text()}")
            try:
                urllib.request.urlopen(f"{url}/api/v1/", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("tiled serve did not start in 60 s")
        from tiled.client import from_uri

        yield from_uri(url, api_key="secret"), data
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        log.close()


def _manifests(tmp_path, data):
    """The two manifests of one entity with one artifact, typed 'probe', over ``data``."""
    raw = dataset_cfg([{"type": "probe", "dataset": "/x"}])
    raw["source"]["files"]["directory"] = str(data)
    yaml_path = tmp_path / "probe.yml"
    with open(yaml_path, "w") as fh:
        YAML().dump(raw, fh)
    ent_path, art_path = generate_manifests(str(yaml_path), tmp_path / "m")
    return pd.read_parquet(ent_path), pd.read_parquet(art_path)


def _served(client, data, ent_df, art_df, key, dataset, upload):
    """Whether an artifact typed ``key`` registers without an error and reads back, by
    listing, by key, by path, and from its locators."""
    from tilewright.client import load, locate
    from tilewright.register import register_dataset_http

    rows = art_df.assign(type=key)  # the manifest the contract would refuse to write
    summary = register_dataset_http(client, ent_df, rows, str(data), dataset, dataset, {},
                                    upload=upload, max_workers=1)
    if summary.failed or summary.artifacts != 1:
        return False
    try:
        (ent_key,) = list(client[dataset])
        entity = client[dataset][ent_key]
        return (list(entity) == [key] and np.array_equal(entity[key][:], WANT)
                and np.array_equal(client[dataset, ent_key, key][:], WANT)
                and list(locate(entity)) == [key]
                and np.array_equal(load(entity, key, str(data)), WANT))
    except Exception:  # noqa: BLE001  a KeyError, a TypeError, an httpx.InvalidURL ...
        return False


@pytest.mark.integration
@pytest.mark.parametrize("upload", [False, True], ids=["pointer", "upload"])
def test_the_server_serves_exactly_the_types_the_contract_accepts(local_server, tmp_path,
                                                                  upload):
    client, data = local_server
    ent_df, art_df = _manifests(tmp_path, data)
    keys = SERVED + list(NOT_SERVED)
    found = {key: _served(client, data, ent_df, art_df, key,
                          f"KEYS_{'UP' if upload else 'PTR'}_{i}", upload)
             for i, key in enumerate(keys)}
    assert found == {key: key_problem(key) is None for key in keys}
    assert found == {key: key in SERVED for key in keys}


@pytest.mark.integration
def test_an_uploaded_type_must_fit_a_file_name_once_escaped(local_server, tmp_path):
    """The limit the type description states for --upload: the server names a directory
    after the type, escaped by urllib.parse.quote_plus; a pointer has no such limit."""
    client, data = local_server
    ent_df, art_df = _manifests(tmp_path, data)
    cases = {"x" * 255: True, "x" * 256: False, "é" * 42: True, "é" * 43: False,
             "a+" * 63: True, "a+" * 64: False}
    for i, (key, fits) in enumerate(cases.items()):
        assert key_problem(key) is None
        assert _served(client, data, ent_df, art_df, key, f"LONG_PTR_{i}", False)
        assert _served(client, data, ent_df, art_df, key, f"LONG_UP_{i}", True) is fits, key
