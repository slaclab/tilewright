"""The contract surface: what validates, what does not, and how errors read.

Every rejection must name the field and say what to do; every accepted YAML must round
trip into a DatasetConfig. The concept budget at the bottom pins the contract's shape so
that growth fails a test, not a review.
"""

import re
from pathlib import Path
from typing import get_args

import pytest
from ruamel.yaml import YAML

from tilewright.contract import (
    SOURCE_TAGS, TOP_LEVEL_KEYS, ArtifactSpec, ContractError, DatasetConfig, Identity,
    ParamsSpec, SharedAxisSpec, Source, load_dataset, slugify_key, source_fingerprint,
)
from tilewright.manifest import _from_text
from tilewright.vocabulary import FACETS, check, load_vocabulary, resolve_aliases

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3"}
EXAMPLES = Path(__file__).parent.parent / "examples" / "datasets"
REFERENCE_PAGE = Path(__file__).parent.parent / "docs" / "reference" / "dataset-yaml.md"


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

    @pytest.mark.parametrize("location", [
        r"BCI_(?P<year>\d{4})(?P<month>[A-Z]{3})\.h5$",
        r":(?P<row>\d+)$",
        r"(\d+)_(?P<member>[^_]+)_",
    ])
    def test_params_location_is_a_regex_with_named_groups(self, location):
        for tag in ("files", "batch", "groups"):
            raw = files_cfg(source={tag: {"directory": "/d", "params": {"location": location}}})
            cfg, warnings = load_dataset(raw)
            assert warnings == [] and cfg.source.body.params.location == location
            assert cfg.source.identity == Identity.params

    def test_params_location_description_examples_do_what_it_says(self):
        """The examples in the description are the ones authors copy: each validates, and
        each gives the values the description states, on the locations it shows."""
        doc = ParamsSpec.model_fields["location"].description
        examples = re.findall(r"`location: '([^']+)'`", doc)
        assert len(examples) == 3
        for location in examples:
            raw = files_cfg(source={"batch": {"directory": "/d",
                                              "params": {"location": location}}})
            assert load_dataset(raw)[0].source.body.params.location == location

        def found(location, text):
            return {k: _from_text(v) for k, v in re.search(location, text).groupdict().items()}

        files, one_batch, several = examples
        assert "`cell07/sweep_250mV.h5`" in doc and "gives cell 7 and bias_mV 250" in doc
        assert found(files, "cell07/sweep_250mV.h5") == {"cell": 7, "bias_mV": 250}
        assert "`shots/part_03.h5:41`" in doc and "matches several files" in doc
        assert found(one_batch, "shots/part_03.h5:41") == {"shot": 41}
        assert found(several, "shots/part_03.h5:41") == {"part": 3, "shot": 41}
        # the row alone is the same in two files; with the file part it is not
        assert found(one_batch, "part_00.h5:0") == found(one_batch, "part_01.h5:0")
        assert found(several, "part_00.h5:0") != found(several, "part_01.h5:0")

    def test_groups_takes_a_glob_entity_group_and_exclude_groups(self):
        raw = files_cfg(source={"groups": {
            "directory": "/d", "entity_group": "/*", "exclude_groups": ["calibration", "_*"],
            "params": {"groups": {"calibration": "../calibration", "own": "/"},
                       "location": r":/(?P<site>[^/]+)/(?P<detector>[^/]+)$"}}})
        cfg, warnings = load_dataset(raw)
        body = cfg.source.body
        assert warnings == [] and body.entity_group == "/*"
        assert body.exclude_groups == ["calibration", "_*"]
        assert body.params.paths == {"calibration": "../calibration", "own": "/"}

    def test_the_entity_group_default_names_the_group_and_not_the_entities(self):
        """`entity_group` names the group whose subgroups are the entities, so its stated
        default has to be a group. Read as naming the entities instead, "the file's
        top-level groups" would make each entity a *subgroup* of a top-level group -- what
        '/*' does, and a different set of entities on the same file, which
        tests/test_manifest.py::TestGroups::test_top_level_groups_when_no_entity_group
        runs both ways to prove.

        The default group is the file root, so the clause that states it names the root:
        that word is the fact and not a turn of phrase, since the default is a path and
        the root is the only path it can be. What the clause must not do is name the
        alternative, so '/*' has to appear later in the description, as the contrast, and
        never in the clause itself."""
        from tilewright.contract import GroupsSource

        field = GroupsSource.model_fields["entity_group"]
        assert field.default is None
        default_clause, rest = field.description.split("Default:")[1].split(".", 1)
        assert "root" in default_clause, default_clause
        assert "'/*'" not in default_clause, default_clause
        assert "'/*'" in rest

    @pytest.mark.parametrize("path", ["..", "../..", "../calibration", "/../calibration",
                                      "../../run/beam/", "../../.."])
    def test_a_groups_params_path_may_start_with_dotdot(self, path):
        for params in ({"group": path}, {"groups": {"up": path}}):
            raw = files_cfg(source={"groups": {"directory": "/d", "params": params}})
            cfg, warnings = load_dataset(raw)
            assert warnings == [] and list(cfg.source.body.params.paths.values()) == [path]

    def test_groups_recursion_stays_for_paths_inside_the_entity_group(self):
        # '..cal' is a group name, not the segment '..'
        params = {"groups": {"own": "/", "readout": "/readout", "odd": "..cal"},
                  "recursive": True}
        raw = files_cfg(source={"groups": {"directory": "/d", "entity_group": "/*",
                                           "params": params}})
        cfg, warnings = load_dataset(raw)
        assert warnings == [] and cfg.source.body.params.recursive

    def test_exclude_groups_defaults_to_empty(self):
        raw = files_cfg(source={"groups": {"directory": "/d"}})
        assert load_dataset(raw)[0].source.body.exclude_groups == []

    def test_params_location_defaults_to_none(self):
        cfg, _ = load_dataset(files_cfg())
        assert cfg.source.body.params.location is None

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

    @pytest.mark.parametrize("location, error", [
        ("BCI_(?P<year>\\d{4}", "is not a Python regular expression ({}); write it in "
                                "single quotes so that YAML keeps the backslashes"),
        ("(?P<1year>x)", "is not a Python regular expression ({}); write it in single "
                         "quotes so that YAML keeps the backslashes"),
        (r"BCI_(\d{4})\.h5", "has no named group, so it gives no parameter: write "
                              "(?P<name>...) around each value"),
        ("", "has no named group, so it gives no parameter: write (?P<name>...) around each "
             "value"),
        (r"(?P<uid>\d+)", "may not name a group uid: 'uid' and 'source_group' are manifest "
                          "columns; choose another name"),
        (r"(?P<source_group>\w+):(?P<uid>\d+)", "may not name a group source_group or uid: "
                                                "'uid' and 'source_group' are manifest "
                                                "columns; choose another name"),
        # '_provenance' was hashed into the uid, then dropped from entities.parquet
        (r"run_(?P<_provenance>\d+)", "may not name a group _provenance: a name that starts "
                                      "with '_' is kept for the manifest's own use; choose "
                                      "another name"),
        (r"(?P<_run>\d+)_(?P<site>\w+)_(?P<__x>\w)", "may not name a group __x or _run: a "
                                                    "name that starts with '_' is kept for "
                                                    "the manifest's own use; choose another "
                                                    "name"),
    ])
    def test_params_location_must_name_parameters(self, location, error):
        if "({})" in error:  # re's own words, e.g. 'missing ), unterminated subpattern ...'
            with pytest.raises(re.error) as exc:
                re.compile(location)
            error = error.format(exc.value)
        raw = files_cfg()
        raw["source"]["files"]["params"] = {"location": location}
        assert errors_of(raw) == [f"source.files.params.location: {error}"]

    @pytest.mark.parametrize("tag", ["files", "batch"])
    @pytest.mark.parametrize("params, field, path", [
        ({"group": "../params"}, "group", "../params"),
        ({"group": ".."}, "group", ".."),
        ({"group": "/../params"}, "group", "/../params"),
        ({"groups": {"own": "/entry", "cal": "../cal"}}, "groups.cal", "../cal"),
        # without an entity group, 'recursive' is not what is wrong
        ({"group": "..", "recursive": True}, "group", ".."),
    ])
    def test_dotdot_needs_an_entity_group(self, tag, params, field, path):
        raw = files_cfg(source={tag: {"directory": "/d", "params": params}})
        assert errors_of(raw) == [
            f"source.{tag}: params.{field} {path!r} starts with '..', which leaves an entity "
            f"group, and only a 'groups' source has one: here a params path is inside the "
            f"file, from its root"]

    # The YAMLs that recursed from '..' in the tests of rounds 1-3 of #21, and the case of
    # its third review (a glob segment above the last one): recursion from outside the
    # entity group read other entities' values, and is refused (ADR-0011).
    @pytest.mark.parametrize("entity_group, params, field, path", [
        ("/run", {"groups": {"run": "..", "own": "/"}}, "groups.run", ".."),
        ("/*", {"groups": {"top": "../..", "own": "/"}}, "groups.top", "../.."),
        ("/*", {"groups": {"own": "/", "cal": "../calibration", "top": "../.."}},
         "groups.cal", "../calibration"),
        ("/*/sites/*", {"groups": {"campaign": "../../..", "own": "/"}},
         "groups.campaign", "../../.."),
        ("/*/sites/*", {"groups": {"campaign": "../../../..", "own": "/"}},
         "groups.campaign", "../../../.."),
        ("/sites/*", {"groups": {"top": "../../..", "own": "/"}}, "groups.top", "../../.."),
        ("/run_*/scans", {"groups": {"up": "../../..", "own": "/"}}, "groups.up",
         "../../.."),
        (None, {"group": "/.."}, "group", "/.."),
    ], ids=["dotdot", "above-the-matched-groups", "beside-the-entities", "deeper-glob-run",
            "deeper-glob-root", "above-a-link", "review-3", "group"])
    def test_recursive_takes_no_path_that_starts_with_dotdot(self, entity_group, params,
                                                            field, path):
        source = {"directory": "/d", "params": {**params, "recursive": True}}
        if entity_group:
            source["entity_group"] = entity_group
        raw = files_cfg(source={"groups": source})
        assert errors_of(raw) == [
            f"source.groups: params.{field} {path!r} starts with '..', and 'recursive: "
            f"true' is for paths inside the entity group only: from a group outside it the "
            f"reader would reach values that belong to other entities\n"
            f"Fix: name each group you need under params.groups, without recursive"]
        del source["params"]["recursive"]
        assert load_dataset(raw)[1] == []

    @pytest.mark.parametrize("tag", ["files", "batch", "groups"])
    @pytest.mark.parametrize("params, field, path", [
        ({"group": "a/../b"}, "group", "a/../b"),
        ({"group": "../a/.."}, "group", "../a/.."),
        ({"groups": {"cal": "run/.."}}, "groups.cal", "run/.."),
    ])
    def test_dotdot_may_only_lead_a_path(self, tag, params, field, path):
        raw = files_cfg(source={tag: {"directory": "/d", "params": params}})
        assert errors_of(raw) == [
            f"source.{tag}.params: {field} {path!r}: '..' may only lead the path "
            f"('../calibration'), to leave the entity group"]

    def test_exclude_groups_are_name_patterns(self):
        raw = files_cfg(source={"groups": {"directory": "/d",
                                           "exclude_groups": ["ok_*", "run/cal", ""]}})
        assert errors_of(raw) == [
            "source.groups.exclude_groups: 'run/cal', '': each entry is a pattern matched "
            "against the name of a subgroup, so it is not empty and has no '/'"]
        raw["source"]["groups"]["exclude_groups"] = "calibration"
        assert errors_of(raw) == ["source.groups.exclude_groups must be a list"]

    @pytest.mark.parametrize("tag", ["files", "batch"])
    def test_exclude_groups_belongs_to_groups(self, tag):
        raw = files_cfg(source={tag: {"directory": "/d", "exclude_groups": ["cal"]}})
        assert errors_of(raw) == [f"source.{tag}.exclude_groups is not a contract key"]

    def test_params_location_must_be_a_string(self):
        raw = files_cfg(source={"batch": {"directory": "/d", "params": {"location": 3}}})
        assert errors_of(raw) == ["source.batch.params.location must be a string"]

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

    # params.location is a fact only when set (ADR-0010): model_dump includes defaults,
    # so an unset location must leave every fingerprint above alone.
    @pytest.mark.parametrize("stem, params", [
        ("files", {"location": None}),
        ("batch", {"group": "/params", "location": None}),
        ("groups", {"group": "params", "location": None}),
    ])
    def test_an_unset_location_keeps_the_b268731_fingerprint(self, stem, params):
        raw = YAML(typ="safe").load((EXAMPLES / f"{stem}.yml").read_text())
        raw["source"][stem]["params"] = params
        assert source_fingerprint(load_dataset(raw)[0]) == self.GOLDEN[stem]

    GOLDEN_LOCATIONS = [
        ("files", {"location": r"run_(?P<run>\d+)\.h5$"}, "de222b76e970ac45"),
        ("files", {"location": r"run_(?P<run>\d+)"}, "63df688425414bcf"),
        ("batch", {"group": "/params", "location": r":(?P<row>\d+)$"}, "34173690e5acaa23"),
        ("groups", {"group": "params", "location": r"sample_(?P<sample>\d+)$"}, "a0c5767df7c1ad6c"),
    ]

    @pytest.mark.parametrize("stem, params, expected", GOLDEN_LOCATIONS,
                             ids=["files", "files-other-regex", "batch", "groups"])
    def test_fingerprint_with_a_location_is_pinned(self, stem, params, expected):
        raw = YAML(typ="safe").load((EXAMPLES / f"{stem}.yml").read_text())
        raw["source"][stem]["params"] = params
        assert source_fingerprint(load_dataset(raw)[0]) == expected

    # exclude_groups is a fact only when it names a pattern (ADR-0011): an empty list, the
    # default, leaves the b268731 value alone. A glob entity_group is a string, hashed as
    # any entity_group was: its value below is the same at b268731.
    GOLDEN_NESTED = [
        ({"entity_group": "/*"}, "4b72253433bfd0d9"),
        ({"exclude_groups": ["calibration"]}, "05db7622963a325b"),
        ({"exclude_groups": ["calibration", "_*"]}, "ff82157c7bae495b"),
        ({"entity_group": "/*", "exclude_groups": ["calibration"],
          "params": {"groups": {"calibration": "../calibration"}}}, "6812c1180cae1855"),
    ]

    @staticmethod
    def groups_fingerprint(override):
        raw = YAML(typ="safe").load((EXAMPLES / "groups.yml").read_text())
        raw["source"]["groups"].update(override)
        return source_fingerprint(load_dataset(raw)[0])

    def test_empty_exclude_groups_keeps_the_b268731_fingerprint(self):
        assert self.groups_fingerprint({"exclude_groups": []}) == self.GOLDEN["groups"]

    @pytest.mark.parametrize("override, expected", GOLDEN_NESTED,
                             ids=["glob", "exclude", "exclude-two", "nested"])
    def test_fingerprint_of_nested_groups_is_pinned(self, override, expected):
        assert self.groups_fingerprint(override) == expected

    def test_the_order_of_exclude_groups_does_not_change_the_fingerprint(self):
        assert (self.groups_fingerprint({"exclude_groups": ["_*", "calibration"]})
                == self.groups_fingerprint({"exclude_groups": ["calibration", "_*", "_*"]}))

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

    def test_the_data_type_description_lists_the_vocabulary_ids(self):
        """The description names every data_type id and no other value, so an author who
        reads only the field reference writes an id (the vocabulary had 'optimization',
        the description did not)."""
        from tilewright.contract import DatasetMetadata

        doc = DatasetMetadata.model_fields["data_type"].description
        ids = [entry["id"] for entry in load_vocabulary()["data_types"]]
        assert re.findall(r"'([^']+)'", doc) == ids

    def test_the_data_type_description_explains_every_id_it_lists(self):
        """Listing an id is not defining it. `vocabulary.yml` gives 'benchmark' and
        'optimization' no label, and no page mentions them, so the field description is
        the only place an author can learn when to pick one: each id is named again
        outside the list that introduces it."""
        from tilewright.contract import DatasetMetadata

        doc = DatasetMetadata.model_fields["data_type"].description.lower()
        for entry in load_vocabulary()["data_types"]:
            assert doc.count(entry["id"]) >= 2, entry["id"]

    def test_the_method_description_says_what_to_write_when_no_method_applies(self):
        """'method' is required and the vocabulary has no id for "none", so an author
        whose data was produced by no method writes something that is not a method unless
        the field says what to do. It points at the same escape hatch 'material'
        documents, and that value really does validate, with a note and nothing else."""
        from tilewright.contract import DatasetMetadata

        doc = DatasetMetadata.model_fields["method"].description
        assert "not_applicable" in doc
        assert "not_applicable" in DatasetMetadata.model_fields["material"].description

        cfg, notes = load_dataset(files_cfg(metadata={
            "method": ["not_applicable"], "data_type": "benchmark",
            "material": "not_applicable"}))
        assert cfg.metadata.method == ["not_applicable"]
        assert [n for n in notes if n.startswith("metadata.method")] == [
            "metadata.method 'not_applicable' is not in the vocabulary; it is registered "
            "as written (known: " + ", ".join(
                sorted(e["id"] for e in load_vocabulary()["methods"])) + ")"]
        assert [n for n in notes if n.startswith("metadata.material")] == []

    def test_the_description_rule_says_which_keys_count(self):
        """"Every number must also exist as a metadata key" has to say *which* keys, or
        an author with a number that only entities carry cannot apply it. The block it
        means is the one this model is: the rule names it by the same name the YAML gives
        it, so renaming the block renames it here too. It also rules an entity parameter
        out, and gives one test for what counts as a number."""
        from tilewright.contract import DatasetConfig, DatasetMetadata

        block = next(name for name, f in DatasetConfig.model_fields.items()
                     if f.annotation is DatasetMetadata)
        doc = DatasetMetadata.model_fields["description"].description
        assert f"key of this '{block}' block" in doc
        assert "entity parameter is not a key of this block" in doc
        assert "Key('...') == query on that number" in doc
        # and the whole rule reaches the page a reader reads, verbatim
        assert doc in REFERENCE_PAGE.read_text()

    def test_the_contact_description_covers_a_record_with_no_address(self):
        """`Name <email>` is the shape, not a requirement: plenty of records publish no
        address, and the field says what to write then rather than leaving the author to
        guess one or drop the field. Saying it means showing a contact with no address in
        it -- and that one has to validate, unremarked, or the advice is wrong."""
        from tilewright.contract import DatasetMetadata

        doc = DatasetMetadata.model_fields["contact"].description
        addressless = [ex for ex in re.findall(r"'([^']+)'", doc) if "@" not in ex]
        assert addressless, doc
        for example in addressless:
            cfg, notes = load_dataset(files_cfg(metadata=dict(META, contact=example)))
            assert cfg.metadata.contact == example
            assert [n for n in notes if n.startswith("metadata.contact")] == []

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
# artifacts: one array ('dataset') or one per dataset in a group ('group', ADR-0012)
# ---------------------------------------------------------------------------

def artifacts_cfg(*artifacts, tag="files", shared=()):
    return files_cfg(source={tag: {"directory": "/d"}}, artifacts=list(artifacts),
                     shared=list(shared))


class TestArtifactGroups:

    @pytest.mark.parametrize("tag", ["files", "groups"])
    def test_a_group_entry_is_accepted_by_files_and_groups(self, tag):
        cfg, warnings = load_dataset(artifacts_cfg(
            {"type": "{name}", "group": "/frames"},
            {"type": "trace_{name}", "group": "channels", "members": "ch_[ab]",
             "optional": True},
            {"type": "{{{name}}}", "group": "/frames"},
            {"type": "spectrum", "dataset": "/spectrum"}, tag=tag))
        assert warnings == []
        first, second, braces, plain = cfg.artifacts
        assert (first.group, first.members, first.dataset, first.optional) == (
            "/frames", "*", None, False)
        assert (second.members, second.optional) == ("ch_[ab]", True)
        assert braces.type.format(name="f") == "{f}"
        assert (plain.dataset, plain.group, plain.members) == ("/spectrum", None, "*")

    def test_group_entries_with_one_template_pass_the_contract(self):
        # their types are known only once the manifest expands them
        load_dataset(artifacts_cfg({"type": "{name}", "group": "/a"},
                                   {"type": "{name}", "group": "/b"}))

    @pytest.mark.parametrize("entry", [{"type": "s"}, {"type": "s", "dataset": "/s",
                                                       "group": "/g"}])
    def test_exactly_one_of_dataset_and_group(self, entry):
        assert errors_of(artifacts_cfg(entry)) == [
            "artifacts[0]: give exactly one of 'dataset' (one array) or 'group' (one array "
            "per dataset in that group)"]

    def test_members_needs_a_group(self):
        assert errors_of(artifacts_cfg({"type": "s", "dataset": "/s", "members": "*"})) == [
            "artifacts[0]: 'members' picks the datasets of a 'group'; remove it, or name a "
            "'group' instead of 'dataset'"]

    def test_members_is_a_non_empty_string(self):
        errs = errors_of(artifacts_cfg({"type": "{name}", "group": "/g", "members": ""},
                                       {"type": "{name}", "group": "/g", "members": ["a"]}))
        assert errs == ["artifacts[0].members must be a non-empty string",
                        "artifacts[1].members must be a string"]

    def test_a_dataset_entry_has_no_name_placeholder(self):
        assert errors_of(artifacts_cfg({"type": "frame_{name}", "dataset": "/f"})) == [
            "artifacts[0]: type 'frame_{name}' holds '{name}', which only a 'group' entry "
            "fills in; write the type out, or name a 'group'"]
        # other braces are plain text in a dataset entry, as before
        assert load_dataset(artifacts_cfg({"type": "a{b}", "dataset": "/f"}))[1] == []

    def test_a_group_entry_needs_the_name_placeholder(self):
        assert errors_of(artifacts_cfg({"type": "frame", "group": "/f"},
                                       {"type": "{{name}}", "group": "/f"})) == [
            f"artifacts[{i}]: type {t!r} has no '{{name}}': with 'group', each member's name "
            f"goes into its type, as in 'trace_{{name}}'" for i, t in ((0, "frame"),
                                                                     (1, "{{name}}"))]

    @pytest.mark.parametrize("template, other", [
        ("{}_{name}", "{}"), ("{0}", "{0}"), ("{name:>6}", "{name:>6}"),
        ("{name!r}", "{name!r}"), ("{run}_{name}_{name.x}", "{run}, {name.x}"),
    ])
    def test_name_is_the_only_placeholder(self, template, other):
        assert errors_of(artifacts_cfg({"type": template, "group": "/f"})) == [
            f"artifacts[0]: type {template!r} holds {other}; '{{name}}' is the only "
            f"placeholder, and a literal brace is written '{{{{' or '}}}}'"]

    @pytest.mark.parametrize("template", ["{name", "a}{name}", "{name}}"])
    def test_a_lone_brace_in_a_group_type(self, template):
        [err] = errors_of(artifacts_cfg({"type": template, "group": "/f"}))
        assert err.startswith(f"artifacts[0]: type {template!r} is not a template (")
        assert err.endswith("); write a literal brace as '{{' or '}}'")

    def test_a_batch_source_takes_dataset_entries_only(self):
        raw = artifacts_cfg({"type": "spectrum", "dataset": "/spectra"},
                            {"type": "{name}", "group": "/frames"},
                            {"type": "t_{name}", "group": "/traces"}, tag="batch")
        assert errors_of(raw) == [
            "artifacts[1], artifacts[2]: a 'batch' source takes 'dataset' entries only, "
            "because its first artifact sets the batch size; name each array of the group "
            "in an entry of its own"]

    def test_a_shared_entry_takes_no_group(self):
        raw = artifacts_cfg({"type": "{name}", "group": "/frames"},
                            shared=[{"type": "axis_{name}", "group": "/axes"}])
        assert errors_of(raw) == ["shared[0].dataset is required",
                                  "shared[0].group is not a contract key"]

    # A dataset entry was never a fingerprint fact and still is not; a group entry is, as
    # its group and members (not its type, not optional): the spec, not its expansion.
    # The group is hashed without a '/' at either end, so '/frames' hashes as 'frames'.
    GOLDEN_GROUPS = [
        ("files", [{"type": "{name}", "group": "/frames"}], "74d3f36c871059cf"),
        ("files", [{"type": "{name}", "group": "/frames", "members": "frame_00[0-4]?"}],
         "bb4af104c7af1476"),
        ("groups", [{"type": "trace_{name}", "group": "channels"}], "2abb181af26a665d"),
    ]

    @staticmethod
    def fingerprint(stem, extra):
        raw = YAML(typ="safe").load((EXAMPLES / f"{stem}.yml").read_text())
        raw["artifacts"] += extra
        return source_fingerprint(load_dataset(raw)[0])

    @pytest.mark.parametrize("stem, extra, expected", GOLDEN_GROUPS,
                             ids=["files", "files-members", "groups"])
    def test_fingerprint_with_a_group_entry_is_pinned(self, stem, extra, expected):
        assert self.fingerprint(stem, extra) == expected

    @pytest.mark.parametrize("stem", ["files", "groups", "batch"])
    def test_a_dataset_entry_keeps_the_b268731_fingerprint(self, stem):
        extra = [{"type": "extra", "dataset": "/extra", "optional": True}]
        assert self.fingerprint(stem, extra) == TestKeyAndFingerprint.GOLDEN[stem]

    @pytest.mark.parametrize("change", [
        {"optional": True}, {"type": "frame_{name}"}, {"members": "*"}])
    def test_optional_and_the_type_do_not_change_the_fingerprint(self, change):
        entry = {"type": "{name}", "group": "/frames", **change}
        assert self.fingerprint("files", [entry]) == "74d3f36c871059cf"

    @pytest.mark.parametrize("group", ["frames", "frames/", "/frames/"])
    def test_the_slashes_around_a_group_do_not_change_the_fingerprint(self, group):
        # the manifest reads all three as the group /frames, so they are one fact
        entry = {"type": "{name}", "group": group}
        assert (self.fingerprint("files", [entry])
                == self.fingerprint("files", [{"type": "{name}", "group": "/frames"}]))

    def test_the_root_group_has_one_fingerprint(self):
        assert (self.fingerprint("files", [{"type": "{name}", "group": "/"}])
                == self.fingerprint("files", [{"type": "{name}", "group": "//"}]))

    def test_the_order_of_group_entries_does_not_change_the_fingerprint(self):
        a = {"type": "a_{name}", "group": "/a"}
        b = {"type": "b_{name}", "group": "/b", "members": "x*"}
        assert self.fingerprint("files", [a, b]) == self.fingerprint("files", [b, a])
        assert self.fingerprint("files", [a, b]) != self.fingerprint("files", [a])


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
        "groups": common | hdf5 | {"entity_group", "exclude_groups", "params"},
        "table": common | {"path", "id", "locator"},
    }
    assert _keys(ParamsSpec) == {"group", "groups", "from", "recursive", "exclude",
                                 "location"}
    assert _keys(ArtifactSpec) == {"type", "dataset", "group", "members", "optional"}
    assert _keys(SharedAxisSpec) == {"type", "dataset"}
