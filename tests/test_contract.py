"""The contract surface: what validates, what does not, and how errors read.

Every rejection must name the field and say what to do; every accepted YAML must round
trip into a DatasetConfig. The concept budget at the bottom pins the contract's shape so
that growth fails a test, not a review.
"""

import pytest

from tilewright.contract import (
    SOURCE_TAGS, TOP_LEVEL_KEYS, ContractError, DatasetConfig, Identity, load_dataset,
    slugify_key, source_fingerprint,
)
from tilewright.vocabulary import FACETS, check, load_vocabulary, resolve_aliases

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3"}


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

    def test_batch_params_cannot_be_null(self):
        raw = files_cfg(source={"batch": {"directory": "/d", "params": None}})
        assert any("source.batch.params" in e for e in errors_of(raw))

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


# ---------------------------------------------------------------------------
# concept budget: growing the contract is a deliberate act
# ---------------------------------------------------------------------------

def test_concept_budget():
    assert set(DatasetConfig.model_fields) == TOP_LEVEL_KEYS == {
        "label", "key", "metadata", "source", "artifacts", "shared"}
    assert SOURCE_TAGS == ("files", "batch", "groups", "table")
