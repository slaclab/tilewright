"""The dataset YAML contract: what a valid dataset description is.

These pydantic models are the **contract surface**. An agent or a person learns what a
dataset YAML may contain by reading this file (or the reference page generated from it),
never by reading the generator. Every field carries a ``description``.

Shape (ADR-0006): the top level is exactly ``label, key, metadata, source, artifacts,
shared``. ``source`` is a tagged union — one of ``files | batch | groups | table`` — and each
tag owns only the keys that make sense for it, so an illegal combination cannot be written.
Closed sections ``forbid`` unknown keys; ``metadata`` allows any extra key (it becomes a
queryable facet). Values of the vocabulary facets are soft-checked in ``vocabulary.py``
(ADR-0003): unknown values warn, they never block.

Identity (ADR-0007): an entity's uid is a hash of its parameter values unless the source
says ``identity: provenance`` (hash of where it came from), which is forced when
``params: null``. ``key`` is derived from ``label`` by ``tilewright manifest``; a key that
drifted from its label is an error.
"""

import hashlib
import json
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TOP_LEVEL_KEYS = frozenset({"label", "key", "metadata", "source", "artifacts", "shared"})
SOURCE_TAGS = ("files", "batch", "groups", "table")


class StrEnum(str, Enum):
    def __str__(self):
        return self.value


class Identity(StrEnum):
    """How an entity's uid is computed (``source.<tag>.identity``).

    - ``params`` (default) — sha256 of the parameter *values*. The same physics is the same
      entity across re-registration and file moves; two entities with identical
      parameters are a contract error (``tilewright manifest`` names them).
    - ``provenance`` — sha256 of where the entity came from (file path relative to the
      directory, plus row or group). Never collides; forced when ``params: null``.
    """

    params = "params"
    provenance = "provenance"


def slugify_key(label):
    """The catalog key for a label: uppercase, runs of non-alphanumerics -> ``_``.

    ``"Broad Sigma"`` -> ``BROAD_SIGMA``; ``"SUNNY NiPS3 10K"`` -> ``SUNNY_NIPS3_10K``.
    """
    key = re.sub(r"[^A-Z0-9]+", "_", str(label or "").upper()).strip("_")
    if not key:
        raise ValueError("label has no letters or digits to derive a key from")
    return key


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

class DatasetMetadata(BaseModel):
    """Dataset-level facets. Any extra key is kept and becomes queryable."""

    model_config = ConfigDict(extra="allow")

    method: list[str] = Field(
        min_length=1,
        description="Scientific methods, e.g. ['RIXS']; at least one. Vocabulary facet.",
    )
    data_type: str = Field(
        min_length=1,
        description="'simulation', 'experimental' or 'benchmark'. Vocabulary facet.",
    )
    material: str = Field(
        min_length=1,
        description="Material or system studied, e.g. 'NiPS3'; 'not_applicable' for "
        "non-physical data. Vocabulary facet.",
    )
    producer: str | None = Field(
        default=None,
        description="Code that produced or reduced the data ('sunny_jl', 'mantid'). "
        "Vocabulary facet.",
    )
    project: str | None = Field(
        default=None,
        description="Project or collaboration ('MAIQMag'). Vocabulary facet.",
    )
    proposal: str | None = Field(
        default=None,
        description="Beamtime proposal id ('IPTS-37598'). Vocabulary facet.",
    )
    facility: str | None = Field(
        default=None,
        description="Where experimental data was collected ('SNS'). Vocabulary facet.",
    )
    instrument: str | None = Field(
        default=None,
        description="Instrument or beamline ('SEQUOIA', 'JEOL NeoARM'). Free text.",
    )
    contact: str | None = Field(
        default=None,
        description="Who to ask about this dataset, as 'Name <email>'.",
    )
    description: str | None = Field(
        default=None,
        description="One paragraph a reader uses to decide whether to open the dataset. "
        "Repeat the defining numbers here freely, but every number in it must also "
        "exist as a metadata key: the key is authoritative, the prose is the summary.",
    )


# ---------------------------------------------------------------------------
# source: the tagged union
# ---------------------------------------------------------------------------

class ParamsSpec(BaseModel):
    """Where an entity's parameters are read from, within its container.

    The container is the file (``files``, ``batch``) or the entity group (``groups``).
    Scalar datasets (or attributes) found there become the entity's queryable metadata;
    each field's own HDF5 attributes ride along as ``<field>_<attr>`` labels.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    group: str | None = Field(
        default=None,
        description="One HDF5 group whose fields become flat metadata keys. '/' is the "
        "container itself. Default '/' when neither 'group' nor 'groups' is given.",
    )
    groups: dict[str, str] | None = Field(
        default=None,
        description="Several groups, keyed by the name each nests under: "
        "{instrument: /entry/instrument, sample: /entry/sample} -> metadata.instrument.Ei, "
        "metadata.sample.mass; queryable as Key('instrument.Ei').",
    )
    from_: Literal["datasets", "attrs"] = Field(
        default="datasets",
        alias="from",
        description="'datasets': 0-dim datasets in the group are parameters (in 'batch', a "
        "1-D dataset of length N is one value per entity). 'attrs': the group's HDF5 "
        "attributes are the parameters.",
    )
    recursive: bool = Field(
        default=False,
        description="Descend into subgroups, nesting one level per subgroup.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="HDF5 paths (same frame as the group paths) to skip: a JSON blob, say. "
        "Under 'from: attrs', an attribute's path is `<group path>/<attribute>`: "
        "`/operator_note` skips the root's attribute 'operator_note'.",
    )

    @model_validator(mode="after")
    def _one_way_to_name_groups(self):
        if self.group and self.groups:
            raise ValueError("'group' and 'groups' are mutually exclusive; to nest one "
                             "group, name it under 'groups'")
        if self.groups is not None and not self.groups:
            raise ValueError("'groups' must name at least one group")
        return self


def _absolute(path, what):
    if not str(path).startswith("/"):
        raise ValueError(f"{what} must be an absolute path (registration builds file:// "
                         f"URIs from it)")
    if ".." in str(path).split("/"):
        raise ValueError(f"{what} must not contain '..'")
    return path


class _SourceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(
        min_length=1,
        description="Absolute path of the data root on the machine that runs "
        "'tilewright manifest' (and '--upload').",
    )
    server_base_dir: str | None = Field(
        default=None,
        description="The same root as the Tiled server sees it, when its mount differs. "
        "Ignored for --upload.",
    )
    identity: Identity = Field(
        default=Identity.params,
        description="How entity uids are computed; see Identity. Write it only to override.",
    )

    @model_validator(mode="after")
    def _paths(self):
        _absolute(self.directory, "directory")
        if self.server_base_dir is not None:
            _absolute(self.server_base_dir, "server_base_dir")
        return self


class FilesSource(_SourceBase):
    """One HDF5 file per entity."""

    pattern: str = Field(
        default="**/*.h5",
        description="Glob for the entity files under 'directory'.",
    )
    params: ParamsSpec | None = Field(
        default_factory=ParamsSpec,
        description="Where the parameters live in each file; default: 0-dim datasets at "
        "the root. 'null' declares that entities have no parameters (identity becomes "
        "provenance).",
    )


class BatchSource(_SourceBase):
    """Many entities stacked along axis 0 of each file's datasets; entity i is row i."""

    pattern: str = Field(
        default="**/*.h5",
        description="Glob for the batch files under 'directory'.",
    )
    params: ParamsSpec = Field(
        default_factory=ParamsSpec,
        description="Group holding one 1-D dataset of length N per parameter (0-dim "
        "datasets are broadcast to every entity in the file).",
    )


class GroupsSource(_SourceBase):
    """One HDF5 group per entity inside each file."""

    pattern: str = Field(
        default="**/*.h5",
        description="Glob for the files under 'directory'.",
    )
    entity_group: str | None = Field(
        default=None,
        description="Group whose subgroups are the entities ('/samples'). Default: the "
        "file's top-level groups.",
    )
    params: ParamsSpec | None = Field(
        default_factory=ParamsSpec,
        description="Where the parameters live, relative to each entity group; default: "
        "the entity group's own 0-dim datasets. 'null' declares none.",
    )


class TableSource(_SourceBase):
    """A sidecar table whose rows are the entities: for data Tiled cannot read."""

    path: str = Field(
        min_length=1,
        description="Parquet or CSV file, relative to 'directory'. Every column becomes "
        "entity metadata.",
    )
    id: str = Field(
        min_length=1,
        description="Column whose value identifies a row; it is the entity's identity.",
    )
    locator: dict[str, str] = Field(
        default_factory=dict,
        description="Extra metadata rendered per row from '{column}' templates, e.g. "
        "{globus_url: 'https://.../{filename}'}.",
    )


class Source(BaseModel):
    """Exactly one of the four tags."""

    model_config = ConfigDict(extra="forbid")

    files: FilesSource | None = Field(default=None, description="One file per entity.")
    batch: BatchSource | None = Field(default=None, description="Entities stacked on axis 0.")
    groups: GroupsSource | None = Field(default=None, description="One group per entity.")
    table: TableSource | None = Field(default=None, description="Rows of a sidecar table.")

    @model_validator(mode="after")
    def _exactly_one(self):
        present = [t for t in SOURCE_TAGS if getattr(self, t) is not None]
        if len(present) != 1:
            raise ValueError(f"exactly one of {' | '.join(SOURCE_TAGS)} is required"
                             + (f" (found {', '.join(present)})" if present else ""))
        return self

    @property
    def tag(self):
        return next(t for t in SOURCE_TAGS if getattr(self, t) is not None)

    @property
    def body(self):
        return getattr(self, self.tag)

    @property
    def identity(self):
        if self.tag == "table" or getattr(self.body, "params", "absent") is None:
            return Identity.provenance
        return self.body.identity


# ---------------------------------------------------------------------------
# artifacts and the whole dataset
# ---------------------------------------------------------------------------

class ArtifactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        min_length=1,
        description="Name of the array; becomes its key under the entity.",
    )
    dataset: str = Field(
        min_length=1,
        description="HDF5 path of the array: absolute for 'files' and 'batch', relative to "
        "each entity group for 'groups'.",
    )
    optional: bool = Field(
        default=False,
        description="True if some entities lack this array; it is skipped for them. "
        "Otherwise a missing array is an error.",
    )


class SharedAxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        min_length=1,
        description="Name of the array; becomes its key under the dataset container.",
    )
    dataset: str = Field(
        min_length=1,
        description="Absolute HDF5 path (in every source) of an array identical for all "
        "entities. Read from the first file that holds it; every other file must agree.",
    )


_MIGRATION = {
    "data": "the contract changed: 'data' and 'parameters' are now one 'source' block with "
            "one tag (files | batch | groups | table); see the YAML reference, Migration",
    "parameters": "the contract changed: 'parameters' now lives inside 'source.<tag>.params'",
    "provenance": "'provenance' is retired: put its fields directly under 'metadata'",
    "extra_metadata": "'extra_metadata' is retired: capture per-entity scalars with "
                      "'source.<tag>.params.groups'",
}


class DatasetConfig(BaseModel):
    """A dataset YAML. Top-level keys are exactly label, key, metadata, source, artifacts,
    shared."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        min_length=1,
        description="Human-readable dataset name. The catalog key is derived from it.",
    )
    key: str | None = Field(
        default=None,
        description="Catalog key, slug(label); written by 'tilewright manifest'. If present "
        "it must equal slug(label).",
    )
    metadata: DatasetMetadata = Field(
        description="Dataset-level facets; method, data_type and material are required.",
    )
    source: Source = Field(description="Where the entities come from: one tag.")
    artifacts: list[ArtifactSpec] = Field(
        default_factory=list,
        description="Arrays each entity exposes; at least one, except for 'table'.",
    )
    shared: list[SharedAxisSpec] = Field(
        default_factory=list,
        description="Arrays shared by every entity, registered once under the dataset.",
    )

    @model_validator(mode="before")
    @classmethod
    def _old_shape(cls, raw):
        if isinstance(raw, dict):
            for old, hint in _MIGRATION.items():
                if old in raw:
                    raise ValueError(hint)
        return raw

    @model_validator(mode="after")
    def _consistency(self):
        expected = slugify_key(self.label)
        if self.key is not None and self.key != expected:
            raise ValueError(f"key '{self.key}' does not match slug(label) '{expected}': "
                             f"restore the label or delete the 'key:' line and re-run "
                             f"'tilewright manifest'")
        if self.source.tag == "table":
            if self.artifacts:
                raise ValueError("a 'table' source has no readable arrays: remove 'artifacts'")
        elif not self.artifacts:
            raise ValueError("'artifacts' needs at least one entry")
        types = [a.type for a in self.artifacts] + [s.type for s in self.shared]
        dupes = sorted({t for t in types if types.count(t) > 1})
        if dupes:
            raise ValueError(f"artifact types must be unique (they become node keys): "
                             f"{', '.join(dupes)}")
        return self

    @property
    def catalog_key(self):
        return self.key or slugify_key(self.label)


# ---------------------------------------------------------------------------
# errors in domain language, fingerprint, loading
# ---------------------------------------------------------------------------

_ERROR_PHRASES = {
    "missing": "{loc} is required",
    "extra_forbidden": "{loc} is not a contract key",
    "string_too_short": "{loc} must be a non-empty string",
    "string_type": "{loc} must be a string",
    "list_type": "{loc} must be a list",
    "too_short": "{loc} needs at least one entry",
    "dict_type": "{loc} must be a mapping",
    "model_type": "{loc} must be a mapping",
    "bool_type": "{loc} must be true or false",
    "enum": "{loc} must be one of {expected}",
    "literal_error": "{loc} must be one of {expected}",
}


def _location(loc):
    parts = []
    for p in loc:
        if isinstance(p, int):
            parts[-1] = f"{parts[-1]}[{p}]" if parts else f"[{p}]"
        else:
            parts.append(str(p))
    return ".".join(parts)


def render_errors(exc: ValidationError):
    """Turn a pydantic error list into one plain sentence per problem.

    ``source.files.pattern must be a non-empty string`` rather than a location tuple and
    ``Input should be a valid string``. Every problem is reported; nothing stops at the
    first. Messages raised by the contract's own validators are passed through verbatim,
    prefixed with where they came from.
    """
    out = []
    for err in exc.errors():
        loc = _location(err["loc"])
        etype, msg = err["type"], err["msg"]
        if etype == "value_error":
            text = msg.removeprefix("Value error, ")
            if loc:
                text = f"{loc}: {text}"
        elif etype in _ERROR_PHRASES:
            expected = (err.get("ctx") or {}).get("expected", "")
            text = _ERROR_PHRASES[etype].format(loc=loc or "top level", expected=expected)
        else:
            text = f"{loc or 'top level'}: {msg}"
        if text not in out:
            out.append(text)
    return out


class ContractError(ValueError):
    """Every contract error of one YAML, already rendered."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(f"contract error: {e}" for e in self.errors))


def load_dataset(raw):
    """Validate a parsed YAML mapping. Returns ``(DatasetConfig, warnings)``.

    Vocabulary aliases in ``raw["metadata"]`` are rewritten to canonical ids in place
    before validation, so the mapping the caller holds (and may write back) is
    normalized. Raises ``ContractError`` carrying every problem.
    """
    from .vocabulary import check, load_vocabulary, resolve_aliases

    if not isinstance(raw, dict):
        raise ContractError(["the YAML must be a mapping at the top level"])
    vocab = load_vocabulary()
    messages = resolve_aliases(raw.get("metadata"), vocab)
    try:
        cfg = DatasetConfig.model_validate(raw)
    except ValidationError as exc:
        raise ContractError(render_errors(exc)) from None
    return cfg, messages + check(cfg.metadata.model_dump(by_alias=True), vocab)


def source_fingerprint(cfg: DatasetConfig):
    """16 hex chars identifying *which data* a YAML describes, independent of its label
    or metadata: the source tag, the directory as the server sees it, the file pattern
    or table path, the params spec and the identity mode. Two YAMLs for the same files
    share it; the same label over different files does not (``tilewright register``
    refuses that)."""
    body = cfg.source.body
    params = getattr(body, "params", None)
    facts = {
        "tag": cfg.source.tag,
        "directory": body.server_base_dir or body.directory,
        "pattern": getattr(body, "pattern", None) or getattr(body, "path", None),
        "params": params.model_dump(by_alias=True) if params is not None else None,
        "entity_group": getattr(body, "entity_group", None),
        "identity": str(cfg.source.identity),
    }
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:16]
