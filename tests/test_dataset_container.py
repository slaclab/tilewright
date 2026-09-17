"""The four fingerprint cases of ``register.dataset_container`` and ``--update``, against a
mock Tiled client. No server needed."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ruamel.yaml import YAML

from tilewright.contract import load_dataset, source_fingerprint
from tilewright.register import dataset_container
from tilewright.utils import FINGERPRINT_KEY, STORAGE_EXTERNAL, STORAGE_KEY, STORAGE_UPLOADED

EXAMPLES = Path(__file__).parent.parent / "examples" / "datasets"

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3", "label": "X",
        "description": "the original"}


def client_with(existing=None):
    client = MagicMock()
    client.__contains__.side_effect = lambda k: existing is not None
    node = MagicMock()
    node.metadata = existing or {}
    client.__getitem__.return_value = node
    return client, node


def test_absent_key_is_created_with_stamps():
    client, _ = client_with(None)
    dataset_container(client, "X", META, STORAGE_EXTERNAL, "abc123")
    md = client.create_container.call_args.kwargs["metadata"]
    assert md[STORAGE_KEY] == STORAGE_EXTERNAL and md[FINGERPRINT_KEY] == "abc123"
    assert md["registered_at"].endswith("+00:00") and md["description"] == "the original"


def test_same_fingerprint_proceeds_without_touching_metadata():
    client, node = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL, FINGERPRINT_KEY: "abc123"})
    assert dataset_container(client, "X", META, STORAGE_EXTERNAL, "abc123") is node
    node.update_metadata.assert_not_called()
    client.create_container.assert_not_called()


def test_same_fingerprint_with_update_patches_metadata():
    client, node = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL, FINGERPRINT_KEY: "abc123"})
    new = {**META, "description": "corrected", "contact": "A <a@b>"}
    dataset_container(client, "X", new, STORAGE_EXTERNAL, "abc123", update=True)
    patch = node.update_metadata.call_args.args[0]
    assert patch["description"] == "corrected" and patch["contact"] == "A <a@b>"
    assert "updated_at" in patch and STORAGE_KEY not in patch and FINGERPRINT_KEY not in patch


def test_different_fingerprint_is_refused_with_both_shown():
    client, _ = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL, FINGERPRINT_KEY: "abc123"})
    with pytest.raises(ValueError) as exc:
        dataset_container(client, "X", META, STORAGE_EXTERNAL, "fff999")
    msg = str(exc.value)
    assert "already holds different data" in msg and "abc123" in msg and "fff999" in msg
    assert "different label" in msg


def test_different_fingerprint_is_refused_even_with_update():
    client, node = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL, FINGERPRINT_KEY: "abc123"})
    with pytest.raises(ValueError):
        dataset_container(client, "X", META, STORAGE_EXTERNAL, "fff999", update=True)
    node.update_metadata.assert_not_called()


def test_table_switched_to_a_list_id_is_refused():
    """ADR-0008: a list id re-keys every entity, so it is not the data already registered."""
    raw = YAML(typ="safe").load((EXAMPLES / "table.yml").read_text())
    registered = source_fingerprint(load_dataset(raw)[0])
    raw["source"]["table"]["id"] = ["run_number", "Ei"]
    now = source_fingerprint(load_dataset(raw)[0])
    client, node = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL,
                                FINGERPRINT_KEY: registered})
    with pytest.raises(ValueError, match="already holds different data"):
        dataset_container(client, "X", META, STORAGE_EXTERNAL, now)
    node.update_metadata.assert_not_called()


def test_unfingerprinted_container_needs_adopt():
    client, node = client_with({**META, STORAGE_KEY: STORAGE_EXTERNAL})
    with pytest.raises(ValueError, match="--adopt"):
        dataset_container(client, "X", META, STORAGE_EXTERNAL, "abc123")
    dataset_container(client, "X", META, STORAGE_EXTERNAL, "abc123", adopt=True)
    assert node.update_metadata.call_args.args[0] == {FINGERPRINT_KEY: "abc123"}


def test_transport_mismatch_is_refused_first():
    client, _ = client_with({**META, STORAGE_KEY: STORAGE_UPLOADED, FINGERPRINT_KEY: "abc123"})
    with pytest.raises(ValueError, match="storage='uploaded'"):
        dataset_container(client, "X", META, STORAGE_EXTERNAL, "abc123")
