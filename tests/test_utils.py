# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "ruamel.yaml",
# ]
# ///
"""
Unit tests for utils module.

Tests verify the generic artifact key generation where the manifest's
``type`` column IS the artifact key (no hardcoded type branches).

Run with:
    uv run --with pytest --with 'ruamel.yaml' pytest tests/test_utils.py -v
"""

from pathlib import Path

import numpy as np
import pytest

from tilewright.utils import make_artifact_key, make_entity_key, to_json_safe


class TestMakeEntityKey:
    """Tests for make_entity_key()."""

    def test_full_uuid(self):
        row = {"uid": "636ce3e4-1ea0-5f0f-a515-a4378fa5c842"}
        assert make_entity_key(row, "VDP_SIM") == "VDP_SIM_636ce3e4-1ea0"

    def test_accepts_any_dataset_key(self):
        row = {"uid": "636ce3e4-1ea0-5f0f-a515-a4378fa5c842"}
        assert make_entity_key(row, "SAM_KLEIN") == "SAM_KLEIN_636ce3e4-1ea0"
        assert make_entity_key(row, "NIPS3_MULTIMODAL") == "NIPS3_MULTIMODAL_636ce3e4-1ea0"


class TestMakeArtifactKey:
    """Tests for make_artifact_key()."""

    def test_returns_type_directly(self):
        """The type column IS the key -- no transformation."""
        row = {"type": "mh_powder_30T"}
        assert make_artifact_key(row) == "mh_powder_30T"

    def test_gs_state(self):
        row = {"type": "gs_state"}
        assert make_artifact_key(row) == "gs_state"

    def test_ins_type(self):
        row = {"type": "ins_12meV"}
        assert make_artifact_key(row) == "ins_12meV"

    def test_nips3_rixs(self):
        """Works with NiPS3-style artifact types."""
        row = {"type": "rixs"}
        assert make_artifact_key(row) == "rixs"

    def test_nips3_mag(self):
        row = {"type": "mag"}
        assert make_artifact_key(row) == "mag"

    def test_accepts_any_type_string(self):
        """Generic: any string is a valid type."""
        row = {"type": "custom_artifact_v2"}
        assert make_artifact_key(row) == "custom_artifact_v2"

    def test_extra_columns_ignored(self):
        """Only the type column matters for key generation."""
        row = {"type": "rixs", "axis": "powder", "Hmax_T": 30}
        assert make_artifact_key(row) == "rixs"


class TestToJsonSafe:
    """Tests for to_json_safe() edge cases."""

    def test_np_bool_true(self):
        """np.bool_ True → Python bool True (not raw np.bool_)."""
        result = to_json_safe(np.bool_(True))
        assert result is True
        assert type(result) is bool

    def test_np_bool_false(self):
        """np.bool_ False → Python bool False."""
        result = to_json_safe(np.bool_(False))
        assert result is False
        assert type(result) is bool

    def test_list_passthrough(self):
        """Plain Python list passes through unchanged."""
        value = [1, 2, 3]
        assert to_json_safe(value) == [1, 2, 3]

    def test_dict_passthrough(self):
        """Plain Python dict passes through unchanged."""
        value = {"a": 1}
        assert to_json_safe(value) == {"a": 1}

    def test_np_int(self):
        assert type(to_json_safe(np.int64(5))) is int

    def test_np_float(self):
        assert type(to_json_safe(np.float32(1.5))) is float

    def test_nan_becomes_none(self):
        import math
        assert to_json_safe(float("nan")) is None

    def test_none_becomes_none(self):
        assert to_json_safe(None) is None

    def test_round_trip_yaml_values_become_plain_types(self):
        """ruamel's round-trip scalars (ScalarFloat, ...) become builtins, recursively."""
        import orjson
        from ruamel.yaml import YAML

        loaded = YAML().load(
            "f: 1.5\nhex: 0x1F\nflag: &a true\nq: 'x'\nwhen: 2024-01-02\n"
            "nested: {g: [2.5, {h: 3.5}], t: null}\n")
        out = to_json_safe(loaded)
        assert out == {"f": 1.5, "hex": 31, "flag": True, "q": "x", "when": "2024-01-02",
                       "nested": {"g": [2.5, {"h": 3.5}], "t": None}}

        def types(v):
            if isinstance(v, dict):
                return [type(v)] + [t for x in v.values() for t in types(x)]
            if isinstance(v, list):
                return [type(v)] + [t for x in v for t in types(x)]
            return [type(v)]

        assert set(types(out)) <= {dict, list, str, int, float, bool, type(None)}
        assert orjson.loads(orjson.dumps(out)) == out

    def test_infinite_floats_become_null_and_are_reported(self):
        """#33: inf and -inf are no more JSON numbers than NaN, and the Tiled client's
        serializer writes any of them as null; the caller is told which key held one, with
        the path inside a nested value. NaN is dropped silently: it is also what a row
        holds where it has no value for a column."""
        seen = []
        assert to_json_safe(float("inf"), lambda k, v: seen.append((k, v))) is None
        assert to_json_safe(np.float64("-inf"), lambda k, v: seen.append((k, v))) is None
        assert to_json_safe(float("nan"), lambda k, v: seen.append((k, v))) is None
        assert seen == [("", float("inf")), ("", float("-inf"))]

        seen.clear()
        out = to_json_safe({"limits": {"upper": float("inf")}, "bounds": [1.0, float("inf")]},
                           lambda k, v: seen.append((k, v)))
        assert out == {"limits": {"upper": None}, "bounds": [1.0, None]}
        assert seen == [("limits.upper", float("inf")), ("bounds", float("inf"))]

    def test_tuples_and_arrays_recurse(self):
        out = to_json_safe((np.float32(1.5), np.array([np.int64(2)]), {"k": np.bool_(True)}))
        assert out == [1.5, [2], {"k": True}]
        assert type(out[0]) is float and type(out[1][0]) is int and out[2]["k"] is True


