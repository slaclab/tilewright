"""The contract surface: what validates, what does not, and how errors read.

Every rejection must name the field and say what to do; every accepted YAML must round
trip into a DatasetConfig. The concept budget at the bottom pins the contract's shape so
that growth fails a test, not a review.
"""

from pathlib import Path
from typing import get_args

import pytest
from ruamel.yaml import YAML

from tilewright.contract import (
    SOURCE_TAGS, TOP_LEVEL_KEYS, ArtifactSpec, ContractError, DatasetConfig, Identity,
    ParamsSpec, Source, load_dataset, slugify_key, source_fingerprint,
)
from tilewright.vocabulary import FACETS, check, load_vocabulary, resolve_aliases

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3"}
EXAMPLES = Path(__file__).parent.parent / "examples" / "datasets"


def files_cfg(**over):
    cfg = {"label": "Test Files", "metadata": dict(META),
           "source": {"files": {"directory": "/data/runs", "pattern": "*.h5"}},
           "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
    cfg.update(over)
    return cfg


def errors_of(raw):
    with pytest.raises(ContractError) as exc:
        load_dataset(raw)
    return exc.value.errors


# ---------------------------------------------------------------------------
# accepted shapes
# ---------------------------------------------------------------------------

class TestAccepted:

    def test_files_defaults(self):
        cfg, warnings = load_dataset(files_cfg())
        assert warnings == []
        assert cfg.source.tag == "files"
        assert cfg.source.body.params.group is None and cfg.source.body.params.from_ == "datasets"
        assert cfg.source.identity == Identity.params
        assert cfg.catalog_key == "TEST_FILES"

    def test_key_present_and_matching(self):
        cfg, _ = load_dataset(files_cfg(key="TEST_FILES"))
        assert cfg.key == "TEST_FILES"

    def test_params_null_forces_provenance(self):
        raw = files_cfg()
        raw["source"]["files"]["params"] = None
        cfg, _ = load_dataset(raw)
        assert cfg.source.body.params is None
        assert cfg.source.identity == Identity.provenance

    def test_identity_override(self):
        raw = files_cfg()
        raw["source"]["files"]["identity"] = "provenance"
        cfg, _ = load_dataset(raw)
        assert cfg.source.identity == Identity.provenance

    def test_params_from_attrs_and_groups(self):
        raw = files_cfg()
        raw["source"]["files"]["params"] = {"groups": {"inst": "/entry/instrument"},
                                            "from": "attrs", "recursive": True,
                                            "exclude": ["/entry/instrument/blob"]}
        cfg, _ = load_dataset(raw)
        p = cfg.source.body.params
        assert p.groups == {"inst": "/entry/instrument"} and p.from_ == "attrs" and p.recursive

    def test_batch_groups_table(self):
        batch = files_cfg(source={"batch": {"directory": "/d", "pattern": "*.h5",
                                            "params": {"group": "/params"}}})
        groups = files_cfg(source={"groups": {"directory": "/d", "entity_group": "/samples",
                                              "params": {"group": "params"}}})
        table = files_cfg(source={"table": {"directory": "/d", "path": "runs.parquet",
                                            "id": "run"}}, artifacts=[])
        assert load_dataset(batch)[0].source.tag == "batch"
        assert load_dataset(groups)[0].source.tag == "groups"
        t = load_dataset(table)[0]
        assert t.source.tag == "table" and t.source.identity == Identity.provenance

    def test_batch_params_null_forces_provenance(self):
        raw = files_cfg(source={"batch": {"directory": "/d", "params": None}})
        cfg, warnings = load_dataset(raw)
        assert warnings == [] and cfg.source.body.params is None
        assert cfg.source.identity == Identity.provenance

    def test_table_id_is_one_column_or_several(self):
        for id_ in ("system_id", ["system_id", "tilt"]):
            raw = files_cfg(source={"table": {"directory": "/d", "path": "t.csv", "id": id_}},
                            artifacts=[])
            cfg, warnings = load_dataset(raw)
            assert warnings == [] and cfg.source.body.id == id_

    def test_metadata_extras_kept(self):
        raw = files_cfg()
        raw["metadata"]["prior_distribution"] = "uniform"
        raw["metadata"]["trusted_q_max"] = 2.85
        cfg, _ = load_dataset(raw)
        md = cfg.metadata.model_dump()
        assert md["prior_distribution"] == "uniform" and md["trusted_q_max"] == 2.85

    def test_optional_artifact_and_shared(self):
        raw = files_cfg(artifacts=[{"type": "a", "dataset": "/a"},
                                   {"type": "b", "dataset": "/b", "optional": True}],
                        shared=[{"type": "energy", "dataset": "/energy"}])
        cfg, _ = load_dataset(raw)
        assert [a.optional for a in cfg.artifacts] == [False, True]
        assert cfg.shared[0].type == "energy"


# ---------------------------------------------------------------------------
# rejected shapes: one sentence per problem, all problems at once
# ---------------------------------------------------------------------------

class TestRejected:

    def test_all_errors_reported_together(self):
        raw = files_cfg()
        del raw["source"]["files"]["directory"]
        raw["source"]["files"]["directoy"] = "/d"
        raw["metadata"].pop("material")
        errs = errors_of(raw)
        assert "source.files.directory is required" in errs
        assert "source.files.directoy is not a contract key" in errs
        assert "metadata.material is required" in errs

    def test_two_tags(self):
        raw = files_cfg()
        raw["source"]["batch"] = {"directory": "/d"}
        assert any("exactly one of files | batch | groups | table" in e for e in errors_of(raw))

    def test_no_tag(self):
        assert any("exactly one of" in e for e in errors_of(files_cfg(source={})))

    def test_relative_directory(self):
        raw = files_cfg()
        raw["source"]["files"]["directory"] = "data/runs"
        assert any("directory must be an absolute path" in e for e in errors_of(raw))

    def test_group_and_groups_exclusive(self):
        raw = files_cfg()
        raw["source"]["files"]["params"] = {"group": "/p", "groups": {"a": "/a"}}
        assert any("mutually exclusive" in e for e in errors_of(raw))

    def test_table_has_no_identity_or_pattern(self):
        raw = files_cfg(source={"table": {"directory": "/d", "path": "t.csv", "id": "run",
                                          "identity": "provenance", "pattern": "*.csv"}},
                        artifacts=[])
        assert errors_of(raw) == ["source.table.identity is not a contract key",
                                  "source.table.pattern is not a contract key"]

    @pytest.mark.parametrize("id_", ["", [], ["run", ""], ["run", 3], 3, None])
    def test_table_id_must_name_columns(self, id_):
        raw = files_cfg(source={"table": {"directory": "/d", "path": "t.csv", "id": id_}},
                        artifacts=[])
        assert errors_of(raw) == ["source.table.id: must be a column name or a list of "
                                  "column names, none of them empty"]

    def test_table_id_names_a_column_once(self):
        raw = files_cfg(source={"table": {"directory": "/d", "path": "t.csv",
                                          "id": ["run", "run"]}}, artifacts=[])
        assert errors_of(raw) == ["source.table.id: names a column more than once"]

    def test_drifted_key(self):
        errs = errors_of(files_cfg(key="OLD_NAME"))
        assert any("does not match slug(label) 'TEST_FILES'" in e for e in errs)

    def test_table_forbids_artifacts(self):
        raw = files_cfg(source={"table": {"directory": "/d", "path": "t.csv", "id": "run"}})
        assert any("'table' source has no readable arrays" in e for e in errors_of(raw))

    def test_duplicate_types_across_artifacts_and_shared(self):
        raw = files_cfg(shared=[{"type": "spectrum", "dataset": "/s"}])
        assert any("artifact types must be unique" in e for e in errors_of(raw))

    def test_required_metadata(self):
        raw = files_cfg(metadata={"method": []})
        errs = errors_of(raw)
        assert "metadata.method needs at least one entry" in errs
        assert "metadata.data_type is required" in errs
        assert "metadata.material is required" in errs

    def test_unknown_identity(self):
        raw = files_cfg()
        raw["source"]["files"]["identity"] = "content"
        assert any(e.startswith("source.files.identity must be one of") for e in errors_of(raw))

    @pytest.mark.parametrize("old", ["data", "parameters", "provenance", "extra_metadata"])
    def test_old_shape_gets_a_migration_hint(self, old):
        raw = files_cfg()
        raw[old] = {}
        errs = errors_of(raw)
        assert len(errs) == 1 and old in errs[0] or "contract changed" in errs[0]

    def test_not_a_mapping(self):
        assert errors_of(["x"]) == ["the YAML must be a mapping at the top level"]


# ---------------------------------------------------------------------------
# key and fingerprint
# ---------------------------------------------------------------------------

class TestKeyAndFingerprint:

    def test_slug(self):
        assert slugify_key("Broad Sigma") == "BROAD_SIGMA"
        assert slugify_key("SUNNY NiPS3 10K") == "SUNNY_NIPS3_10K"
        assert slugify_key("  Okafor: NiPS3 powder! ") == "OKAFOR_NIPS3_POWDER"
        with pytest.raises(ValueError):
            slugify_key("---")

    def test_fingerprint_ignores_label_and_metadata(self):
        a, _ = load_dataset(files_cfg())
        b, _ = load_dataset(files_cfg(label="Another Name", metadata={**META, "description": "x"}))
        assert source_fingerprint(a) == source_fingerprint(b)

    def test_fingerprint_follows_the_data(self):
        a, _ = load_dataset(files_cfg())
        raw = files_cfg()
        raw["source"]["files"]["directory"] = "/data/other"
        b, _ = load_dataset(raw)
        assert source_fingerprint(a) != source_fingerprint(b)

    # Computed on origin/main b268731. A contract change must not re-fingerprint an
    # existing YAML: a changed value here means registered datasets would be refused.
    GOLDEN = {"batch": "2577590f34841be2", "files": "5dd61ef0e916076d",
              "files_nexus": "05ba87a48b5c5ce7", "groups": "983ce13fccafbc8e",
              "table": "fb36ed8c86a417f5"}
    GOLDEN_VARIANTS = [
        ("files", {"identity": "provenance"}, "612f65facb4ab85c"),
        ("files", {"params": None}, "3fdd1ec6ea7990f5"),
        ("batch", {"identity": "provenance"}, "e53377692c4c971d"),
        ("groups", {"identity": "provenance"}, "26489812688e5df3"),
        ("groups", {"params": None}, "6e9343c078db0fbd"),
        ("files", {"server_base_dir": "/srv/data"}, "65515a648b79b940"),
    ]

    def test_fingerprint_of_every_example_is_pinned(self):
        found = {}
        for path in sorted(EXAMPLES.glob("*.yml")):
            cfg, _ = load_dataset(YAML().load(path.read_text()))
            found[path.stem] = source_fingerprint(cfg)
        assert found == self.GOLDEN

    @pytest.mark.parametrize("stem, override, expected", GOLDEN_VARIANTS)
    def test_fingerprint_of_identity_and_params_variants_is_pinned(self, stem, override,
                                                                   expected):
        raw = YAML(typ="safe").load((EXAMPLES / f"{stem}.yml").read_text())
        raw["source"][stem].update(override)
        assert source_fingerprint(load_dataset(raw)[0]) == expected

    # A table's id is a fact only as a list (ADR-0008): a single column leaves the
    # b268731 value alone, and a list re-keys every entity, so it is different data.
    GOLDEN_TABLE_IDS = [
        (["run_number", "Ei"], "1f158c1accc9890f"),
        (["Ei", "run_number"], "f4a58535f478d8bb"),
        (["run_number"], "b0caa823904594f8"),
    ]

    @staticmethod
    def table_fingerprint(table_id):
        raw = YAML(typ="safe").load((EXAMPLES / "table.yml").read_text())
        raw["source"]["table"]["id"] = table_id
        return source_fingerprint(load_dataset(raw)[0])

    def test_single_column_id_keeps_the_b268731_fingerprint(self):
        assert self.table_fingerprint("run_number") == "fb36ed8c86a417f5"

    @pytest.mark.parametrize("table_id, expected", GOLDEN_TABLE_IDS,
                             ids=["run_number,Ei", "Ei,run_number", "one-element"])
    def test_fingerprint_of_a_list_id_is_pinned(self, table_id, expected):
        assert self.table_fingerprint(table_id) == expected

    def test_fingerprint_uses_the_server_view(self):
        raw = files_cfg()
        raw["source"]["files"]["server_base_dir"] = "/mnt/runs"
        a, _ = load_dataset(raw)
        raw["source"]["files"]["directory"] = "/elsewhere/runs"
        b, _ = load_dataset(raw)
        assert source_fingerprint(a) == source_fingerprint(b)


# ---------------------------------------------------------------------------
# vocabulary: aliases rewrite, unknown values warn
# ---------------------------------------------------------------------------

class TestVocabulary:

    def test_every_facet_list_exists(self):
        vocab = load_vocabulary()
        for facet in FACETS.values():
            assert facet in vocab, facet

    def test_alias_rewrites_spelling_only(self):
        raw = files_cfg(metadata={"method": ["EDRIXS"], "material": "NIPS", "data_type": "simulation"})
        cfg, notes = load_dataset(raw)
        assert cfg.metadata.method == ["RIXS"]
        assert cfg.metadata.material == "NiPS3"
        assert [n for n in notes if "alias" in n] == [
            "metadata.method: alias 'EDRIXS' -> 'RIXS'", "metadata.material: alias 'NIPS' -> 'NiPS3'"]
        raw["metadata"].pop("data_type")
        assert "metadata.data_type is required" in errors_of(raw)

    def test_unknown_value_warns_not_errors(self):
        raw = files_cfg(metadata={**META, "material": "Unobtainium", "method": ["HRSTEM"]})
        cfg, warnings = load_dataset(raw)
        assert cfg.metadata.material == "Unobtainium"
        assert cfg.metadata.method == ["STEM"]  # alias resolved
        offlist = [w for w in warnings if "not in the vocabulary" in w]
        assert len(offlist) == 1 and "Unobtainium" in offlist[0]

    def test_check_on_plain_dict(self):
        vocab = load_vocabulary()
        assert check({"proposal": "IPTS-99999"}, vocab)
        assert check({"proposal": "IPTS-37598"}, vocab) == []
        md = {"producer": "Mantid"}
        resolve_aliases(md, vocab)
        assert md["producer"] == "mantid"

    def test_aliases_are_resolved_in_place_so_a_flow_list_keeps_its_style(self):
        """A list facet is the same list afterwards, changed only where an alias was
        (#14): a YAML flow list written back stays a flow list."""
        import io

        from ruamel.yaml import YAML

        yaml = YAML()
        raw = yaml.load("metadata:\n  method: [RIXS, EDRIXS]\n  material: NiPS3\n"
                        "  producer: [Mantid]\n")
        md = raw["metadata"]
        method, producer = md["method"], md["producer"]
        notes = resolve_aliases(md, load_vocabulary())
        assert notes == ["metadata.method: alias 'EDRIXS' -> 'RIXS'",
                         "metadata.producer: alias 'Mantid' -> 'mantid'"]
        assert md["method"] is method and md["producer"] is producer
        out = io.StringIO()
        yaml.dump(raw, out)
        assert out.getvalue() == ("metadata:\n  method: [RIXS, RIXS]\n  material: NiPS3\n"
                                  "  producer: [mantid]\n")

    def test_a_list_without_aliases_is_left_alone(self):
        from ruamel.yaml import YAML

        raw = YAML().load("metadata:\n  method: [RIXS]\n  data_type: simulation\n"
                          "  material: NiPS3\n")
        method = raw["metadata"]["method"]
        load_dataset({**files_cfg(), "metadata": raw["metadata"]})
        assert raw["metadata"]["method"] is method and method.fa.flow_style()


# ---------------------------------------------------------------------------
# concept budget: growing the contract is a deliberate act
# ---------------------------------------------------------------------------

def _keys(model):
    return {field.alias or name for name, field in model.model_fields.items()}


def test_concept_budget():
    assert set(DatasetConfig.model_fields) == TOP_LEVEL_KEYS == {
        "label", "key", "metadata", "source", "artifacts", "shared"}
    assert SOURCE_TAGS == ("files", "batch", "groups", "table")
    tags = {tag: next(a for a in get_args(Source.model_fields[tag].annotation)
                      if a is not type(None)) for tag in SOURCE_TAGS}
    common, hdf5 = {"directory", "server_base_dir"}, {"identity", "pattern"}
    assert {tag: _keys(model) for tag, model in tags.items()} == {
        "files": common | hdf5 | {"params"},
        "batch": common | hdf5 | {"params"},
        "groups": common | hdf5 | {"entity_group", "params"},
        "table": common | {"path", "id", "locator"},
    }
    assert _keys(ParamsSpec) == {"group", "groups", "from", "recursive", "exclude"}
    assert _keys(ArtifactSpec) == {"type", "dataset", "optional"}
