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

Identity (ADR-0007, ADR-0008): in the HDF5 sources an entity's uid is a hash of its
parameter values unless the source says ``identity: provenance`` (hash of where it came
from), which is forced when ``params: null``; a ``table`` has no ``identity`` key, its uid
is a hash of its ``id`` column(s). ``key`` is derived from ``label`` by
``tilewright manifest``; a key that drifted from its label is an error.
"""

import hashlib
import json
import re
import string
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator,
)

TOP_LEVEL_KEYS = frozenset({"label", "key", "metadata", "source", "artifacts", "shared"})
SOURCE_TAGS = ("files", "batch", "groups", "table")
# Columns of entities.parquet that are not parameters; params.location may not name them.
_ENTITY_COLUMNS = frozenset({"uid", "source_group"})


class StrEnum(str, Enum):
    def __str__(self):
        return self.value


class Identity(StrEnum):
    """How an entity's uid is computed (``source.<tag>.identity``, for ``files``,
    ``batch`` and ``groups``).

    - ``params`` (default) — sha256 of the parameter *values*. The same physics is the same
      entity across re-registration and file moves; two entities with identical
      parameters are a contract error (``tilewright manifest`` names them).
    - ``provenance`` — sha256 of where the entity came from (file path relative to the
      directory, plus row or group). Never collides unless ``pattern`` or
      ``entity_group`` matches the same thing twice; forced when ``params: null``.

    A ``table`` has no ``identity`` key: its identity is its ``id`` column(s), the sha256
    of their values. Rows that repeat those values are a contract error; list a further
    column in ``id``, or de-duplicate the table. The manifest records a table's mode as
    ``provenance``.
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
        description="What kind of data, as one of the data_type ids in the vocabulary: "
        "'simulation', 'experimental', 'benchmark' or 'optimization'. A measurement of "
        "the world is experimental wherever the instrument stood, a laboratory, a field "
        "site or an orbit; what a model or a code computed is simulation. Vocabulary "
        "facet.",
    )
    material: str = Field(
        min_length=1,
        description="Material or system studied, e.g. 'NiPS3'. A physical system that is "
        "not a substance is named as the system it is ('upper atmosphere', 'seafloor "
        "sediment'); 'not_applicable' is for data with no physical subject at all, such "
        "as a benchmark of a solver. Vocabulary facet.",
    )
    producer: str | None = Field(
        default=None,
        description="Code that produced or reduced the data ('sunny_jl', 'mantid'). When "
        "a chain of codes made the files, it names the last one that shaped the arrays "
        "being registered; name the earlier steps in 'description'. Vocabulary facet.",
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
        description="Who to ask about this dataset, as `Name <email>`.",
    )
    description: str | None = Field(
        default=None,
        description="One paragraph a reader uses to decide whether to open the dataset. "
        "Repeat the defining numbers here freely, but every number in it must also "
        "exist as a metadata key: the key is authoritative, the prose is the summary. A "
        "number is a quantity someone could query on (a count, a size, a rate, a "
        "temperature); a year in a name, a version string, a DOI and a field name are "
        "prose, and need no key. Nothing checks the rule, so a prose number that no key "
        "carries, or a key whose value the prose contradicts, is found by a reader.",
    )


# ---------------------------------------------------------------------------
# source: the tagged union
# ---------------------------------------------------------------------------

def climb(path):
    """Split a params group path into ``(ups, rest)``: the number of leading ``..``
    segments, which leave a ``groups`` entity group (ADR-0011), and the path below the
    group they reach. Empty segments are dropped, so ``'/'`` is ``(0, '')``. A ``..``
    after a name is a ValueError: it may only lead the path."""
    parts = [p for p in str(path).split("/") if p]
    ups = next((i for i, p in enumerate(parts) if p != ".."), len(parts))
    if ".." in parts[ups:]:
        raise ValueError(f"{path!r}: '..' may only lead the path ('../calibration'), "
                         f"to leave the entity group")
    return ups, "/".join(parts[ups:])


class ParamsSpec(BaseModel):
    """Where an entity's parameters are read from: within its container, and from its
    location.

    The container is the file (``files``, ``batch``) or the entity group (``groups``),
    which a ``groups`` path can leave with ``..`` (ADR-0011). Scalar datasets (or
    attributes) found there become the entity's queryable metadata; each field's own HDF5
    attributes ride along as ``<field>_<attr>`` labels. ``location`` adds the values that
    only the file, directory or group name (or a batch row number) holds (ADR-0010).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    group: str | None = Field(
        default=None,
        description="One HDF5 group whose fields become flat metadata keys. '/' is the "
        "container itself: the file for 'files' and 'batch', and for 'groups' the entity "
        "group, not the file root, since every 'groups' path is relative to the entity "
        "group ('params' and '/params' name the same group). Under 'groups' only, a path "
        "may start with '..' segments to leave the entity group: see 'params' under "
        "'source.groups'. Default '/' when neither 'group' nor 'groups' is given. With "
        "'from: attrs' it may also name a dataset: that dataset's attributes are then the "
        "parameters. An attribute name with a dot in it ('run.number') is a dotted key, "
        "nested on registration like the keys 'groups' makes (metadata.run.number).",
    )
    groups: dict[str, str] | None = Field(
        default=None,
        description="Several groups, keyed by the name each nests under: "
        "{instrument: /entry/instrument, sample: /entry/sample} -> metadata.instrument.Ei, "
        "metadata.sample.mass; queryable as Key('instrument.Ei'). Each path is read as "
        "in 'group', '..' included.",
    )
    from_: Literal["datasets", "attrs"] = Field(
        default="datasets",
        alias="from",
        description="'datasets': scalar datasets in the group are parameters, 0-dim or of "
        "size 1 (NeXus writes scalars with shape (1,)); in 'batch', a 1-D dataset of "
        "length N is one value per entity, and so it is under 'groups' in a group reached "
        "through '..', with N the number of sibling entity groups. Under 'files' and "
        "'groups' every other dataset, a (7,) array or a (3, 4) matrix say, is skipped "
        "without a message, attributes and all. Every container is read on its own, each "
        "file and under 'groups' each entity group, so two more cases pass without a "
        "message: a dataset of size 1 in some of them and a bigger one in others is a "
        "parameter only where one of the rules above makes it one, and a group that some "
        "files or entity groups lack (one of 'groups', say) gives their entities none of "
        "its parameters. Those entities hold null in the columns they miss. 'attrs': the "
        "group's HDF5 attributes are the parameters, and a group that a file or an entity "
        "group lacks is an error naming it. Every attribute of that group is read whatever "
        "its value holds: an array-valued attribute becomes a list parameter, an empty one "
        "(a null dataspace) becomes null. One block reads one way, for every path in it, "
        "and a source takes one 'params' block: a container that keeps some values in "
        "scalar datasets and others in attributes gives up one of the two, so copy what is "
        "left over into 'metadata' by hand, or ask the producer to move it.",
    )
    recursive: bool = Field(
        default=False,
        description="Descend into subgroups, nesting one level per subgroup. The rule "
        "stops at the group the path names: that group's own members are read as they are "
        "without 'recursive', so an HDF5 link written there is followed wherever it leads, "
        "and the descent below it follows only what lies inside that group -- a subgroup "
        "or a dataset an HDF5 link leads out of it (a soft link elsewhere in the file, an "
        "external link, which resolves in another file, a chain of links ending outside, "
        "or a link whose target path is spelled inside the group but runs through a link "
        "that is not) is named in a warning and skipped. So a member of the group itself "
        "is the author's own choice, link and all: write the link out of the group if what "
        "it names should not be read. Below that group no other entity's values, and "
        "nothing from another file, is read through a link, whatever its target path "
        "spells: the object a name resolves to decides, not the text. A group named under "
        "'group' or 'groups' is likewise read wherever its path leads. It applies to every "
        "path of the block, so under 'groups' a block with 'recursive: true' may hold no "
        "path that starts with '..' (see 'params' under 'source.groups'). The key is the "
        "path: a field kept as a group of its own ('/beam_current' holding 'data' and "
        "'description') gives 'beam_current.data' and 'beam_current.description', and "
        "nothing renames a key: the parameter a reader queries is the one the file spells.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="HDF5 paths (same frame as the group paths) to skip: a JSON blob, say. "
        "Under 'from: attrs', an attribute's path is `<group path>/<attribute>`: "
        "`/operator_note` skips the root's attribute 'operator_note'. It skips paths, not "
        "values: under 'recursive', an HDF5 link elsewhere in the group whose target is an "
        "excluded path is inside the group like any other member, so what it names is read "
        "again under the link's own key. Name the link in 'exclude' as well.",
    )
    location: str | None = Field(
        default=None,
        description="A Python regular expression, searched (re.search) in each entity's "
        "location. For 'files', the location is the file path relative to 'directory', "
        "with '/' separators, so a directory name can be matched too "
        "(`cell07/sweep_250mV.h5`); for 'groups', `<file path>:/<group path>` "
        "(`samples.h5:/samples/sample_7`); for 'batch', `<file path>:<row number>` "
        "(`shots/part_03.h5:41`). Each named group, `(?P<name>...)`, becomes a flat "
        "parameter beside those read in the container, and is part of the identity like "
        "them. Its type comes from the text it captures: an integer, `[+-]?\\d+`, becomes "
        "an int, so leading zeros are lost (`07` -> 7); a decimal or exponent literal "
        "(`0.4`, `1e-3`) becomes a float; anything else stays a string; a group that takes "
        "no part in the match is null. Unnamed groups, `(...)`, are wildcards only; at "
        "least one named group is required. Write it in single quotes, so that YAML keeps "
        "the backslashes: "
        r"`location: 'cell(?P<cell>\d+)/sweep_(?P<bias_mV>[+-]?\d+)mV\.h5$'` "
        "gives cell 7 and bias_mV 250. A batch row number is a legitimate parameter "
        r"when nothing else varies between rows: `location: ':(?P<shot>\d+)$'`. "
        "When 'pattern' matches several files, a group path or a row number alone can "
        "repeat from file to file (every batch file's rows start again at 0), so capture "
        r"part of the file path as well: `location: 'part_(?P<part>\d+)\.h5:(?P<shot>\d+)$'`. "
        "An entity whose location does not match is an error, and so is a name that is "
        "also read in the container. A params block that holds nothing but 'location' is "
        "complete: for files that keep no scalar and no attribute anywhere, the named "
        "groups are the entity's whole identity, and the empty default group is no error.",
    )

    @property
    def paths(self):
        """``{name: group path}`` of the groups read: the one ``group`` (default ``/``)
        under the name ``''``, or ``groups``."""
        return self.groups or {"": self.group or "/"}

    @model_validator(mode="after")
    def _one_way_to_name_groups(self):
        if self.group and self.groups:
            raise ValueError("'group' and 'groups' are mutually exclusive; to nest one "
                             "group, name it under 'groups'")
        if self.groups is not None and not self.groups:
            raise ValueError("'groups' must name at least one group")
        for name, path in self.paths.items():
            try:
                climb(path)
            except ValueError as exc:
                raise ValueError(f"{'groups.' + name if name else 'group'} {exc}") from None
        return self

    @field_validator("location")
    @classmethod
    def _location_names_parameters(cls, value):
        if value is None:
            return value
        try:
            names = re.compile(value).groupindex
        except re.error as exc:
            raise ValueError(f"is not a Python regular expression ({exc}); write it in "
                             f"single quotes so that YAML keeps the backslashes") from None
        if not names:
            raise ValueError("has no named group, so it gives no parameter: write "
                             "(?P<name>...) around each value")
        reserved = sorted(set(names) & _ENTITY_COLUMNS)
        if reserved:
            raise ValueError(f"may not name a group {' or '.join(reserved)}: 'uid' and "
                             f"'source_group' are manifest columns; choose another name")
        # The manifest keeps its own bookkeeping ('_provenance') under such names and
        # drops it before writing, so a parameter there would be hashed, then lost.
        private = sorted(n for n in names if n.startswith("_"))
        if private:
            raise ValueError(f"may not name a group {' or '.join(private)}: a name that "
                             f"starts with '_' is kept for the manifest's own use; choose "
                             f"another name")
        return value


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

    @model_validator(mode="after")
    def _paths(self):
        _absolute(self.directory, "directory")
        if self.server_base_dir is not None:
            _absolute(self.server_base_dir, "server_base_dir")
        params = getattr(self, "params", None)
        for name, path in params.paths.items() if params is not None else ():
            if not climb(path)[0]:
                continue
            field = f"params.groups.{name}" if name else "params.group"
            if not isinstance(self, GroupsSource):
                raise ValueError(f"{field} {path!r} starts with '..', which leaves an "
                                 f"entity group, and only a 'groups' source has one: here "
                                 f"a params path is inside the file, from its root")
            # ADR-0011: from outside the entity group, recursion reaches the groups of
            # other entities and other sibling sets, whose arrays follow their own names
            if params.recursive:
                raise ValueError(f"{field} {path!r} starts with '..', and "
                                 f"'recursive: true' is for paths inside the entity group "
                                 f"only: from a group outside it the reader would reach "
                                 f"values that belong to other entities\n"
                                 f"Fix: name each group you need under params.groups, "
                                 f"without recursive")
        return self


class _HDF5SourceBase(_SourceBase):
    """The keys the three HDF5 sources share: which files, and how an entity's uid is
    computed. A ``table`` has neither (ADR-0008)."""

    identity: Identity = Field(
        default=Identity.params,
        description="How entity uids are computed; see Identity. Write it only to override.",
    )
    pattern: str = Field(
        default="**/*.h5",
        description="Glob for the HDF5 files under 'directory', matched with Python's "
        "Path.glob relative to 'directory': '*', '?' and '[...]' match within one path "
        "segment, and a '**' segment matches any number of directories, so '**/*.h5' "
        "recurses. Names starting with '.' match like any other. There are no braces: "
        "'*.{h5,hdf5}' matches nothing; use a wider glob such as '*.h*5'. A pattern that "
        "matches nothing is retried with Path.rglob, which puts '**/' in front of it, so "
        "it then matches at any depth. Only files are kept, in sorted order.",
    )


class FilesSource(_HDF5SourceBase):
    """One HDF5 file per entity."""

    params: ParamsSpec | None = Field(
        default_factory=ParamsSpec,
        description="Where the parameters live: inside each file, and with 'location' in "
        "its path. Default: the scalar datasets at the root. 'null' declares that entities "
        "have no parameters (identity becomes provenance).",
    )


class BatchSource(_HDF5SourceBase):
    """Many entities stacked along axis 0 of each file's datasets; entity i is row i."""

    params: ParamsSpec | None = Field(
        default_factory=ParamsSpec,
        description="Where the parameters live: inside each file, and with 'location' in "
        "its path and row number. Default: the root. N is the file's leading axis (that of "
        "the first artifact). Only 1-D datasets of length N are per-entity values, one per "
        "row; scalar datasets (0-dim or of size 1) are broadcast to every entity in the "
        "file; any other member, (N, 1) with N > 1 included, is skipped without a message. "
        "'null' declares that entities have no parameters (identity becomes provenance).",
    )


class GroupsSource(_HDF5SourceBase):
    """One HDF5 group per entity inside each file."""

    entity_group: str | None = Field(
        default=None,
        description="Group whose subgroups are the entities ('/samples'). Default: the "
        "file's top-level groups. Any segment may be a glob, matched with fnmatch against "
        "the names of the groups at that level: '*' and '?' match within the name, '[...]' "
        "one character of a set, and case matters. '/*' takes every top-level group, so "
        "that each subgroup of each of them is an entity (`/<site>/<detector>`); "
        "'/run_*/scans' takes the 'scans' group of every run_ group. The matching groups "
        "are taken in sorted order, and the entities are the subgroups of every one of "
        "them. A file in which no group matches is an error, and so is one in which the "
        "matching groups have no subgroup left (see 'exclude_groups').",
    )
    exclude_groups: list[str] = Field(
        default_factory=list,
        description="Subgroups that are not entities: fnmatch patterns matched against the "
        "name of each subgroup of the entity group(s), not against its path. "
        "[calibration] leaves out a group that holds values for the entities beside it; "
        "['tmp*'] every group whose name starts with 'tmp'. Excluded groups are not "
        "counted as siblings (see 'params').",
    )
    params: ParamsSpec | None = Field(
        default_factory=ParamsSpec,
        description="Where the parameters live: relative to each entity group, and with "
        "'location' in its file and group path. Default: the entity group's own scalar "
        "datasets. A group path may start with '..' segments to leave the entity group, "
        "resolved against its path: '..' is the group that holds the entity group and its "
        "siblings, '../calibration' a group beside them, '../..' one level higher. A path "
        "that climbs above the file root is an error. In a group reached through '..', a "
        "1-D dataset whose length equals the number of sibling entity groups (the "
        "subgroups of the same group, after 'exclude_groups') gives one value per entity: "
        "element i goes to the i-th sibling with the names sorted as text. Text is not "
        "numeric order: scan_10 sorts before scan_2, so scan_1 ... scan_12 do not pair "
        "with elements 0 ... 11 in order, while scan_01 ... scan_12 do. Scalar datasets "
        "(0-dim or of size 1) there are given to every sibling, and any other member, a "
        "1-D dataset of another length included, is skipped without a message, as in "
        "'batch'. Under 'from: attrs' the attributes of such a group are given to every "
        "sibling. 'recursive: true' is for paths inside the entity group only: recursion "
        "inside the entity group and a path that starts with '..' cannot be combined in "
        "one params block (a contract error), because from outside the entity group the "
        "reader would reach the groups of other entities, whose arrays follow their own "
        "names. Name each group you need instead, without 'recursive': "
        "`{groups: {site: .., calibration: ../calibration, own: /}}`. The group a path "
        "names is read whatever it is, an entity group included: under a path to one "
        "detector (`../<detector>`), its scalars go to every sibling, and each of its 1-D "
        "datasets whose length is the number of siblings is split among them. Recursion "
        "inside the entity group stays inside it (see 'recursive'), so no sibling entity "
        "group, and no group that 'entity_group' matched, is read through a link, whatever "
        "the text of the link's target path spells; a second "
        "HDF5 name (a hard link) for a group *inside* one of them names a member of this "
        "entity group like any other, and is read. 'null' declares none.",
    )

    @field_validator("exclude_groups")
    @classmethod
    def _names_not_paths(cls, value):
        bad = [p for p in value if not p or "/" in p]
        if bad:
            raise ValueError(f"{', '.join(map(repr, bad))}: each entry is a pattern "
                             f"matched against the name of a subgroup, so it is not empty "
                             f"and has no '/'")
        return value


class TableSource(_SourceBase):
    """A sidecar table whose rows are the entities: for data Tiled cannot read."""

    path: str = Field(
        min_length=1,
        description="Parquet or CSV file, relative to 'directory'. Every column becomes "
        "entity metadata, and there is no way to leave one out: a column whose header "
        "cell is empty is read under the name pandas gives it ('Unnamed: 4') and is null "
        "in every row. To drop a column, change the table.",
    )
    id: str | list[str] = Field(
        description="The entity's identity: one column, or a list of columns when no "
        "single column is unique ('id: [specimen, replicate]'); together their values must be "
        "unique across rows. A null cell is allowed and hashed as null, so rows are still "
        "told apart by the cells that are filled in; what no equality search can then "
        "find is that row, because a null is not a value to compare with. Changing it "
        "re-keys every entity: delete the registered "
        "dataset, then register again. A list is part of the fingerprint, so 'register' "
        "refuses a change to, from or between lists until you do.",
    )
    locator: dict[str, str] = Field(
        default_factory=dict,
        description="Extra metadata rendered per row from '{column}' templates, e.g. "
        "{globus_url: 'https://.../{filename}'}.",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _id_columns(cls, value):
        names = [value] if isinstance(value, str) else value
        if not (isinstance(names, list) and names
                and all(isinstance(n, str) and n for n in names)):
            raise ValueError("must be a column name or a list of column names, none of "
                             "them empty")
        if len(set(names)) != len(names):
            raise ValueError("names a column more than once")
        return value


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
        """The mode the uids are computed with. A ``table`` (whose uid hashes its ``id``
        column(s)) and a source with ``params: null`` report ``provenance``."""
        if self.tag == "table" or getattr(self.body, "params", "absent") is None:
            return Identity.provenance
        return self.body.identity


# ---------------------------------------------------------------------------
# artifacts and the whole dataset
# ---------------------------------------------------------------------------

# A type is a Tiled node key. The Tiled client (0.2.18) splits a key on '/' and puts it
# into a URL path as written (tiled/client/container.py, Container.__getitem__); what a
# local server did with each kind of character is in ADR-0012.
_URL_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
TYPE_RULE = ("a type is a node key that travels in a URL, so the server would not serve "
             "that array back")


def key_problem(key):
    """Why ``key``, an artifact or shared ``type``, cannot be a node key that the server
    serves back, as a phrase (``"contains '/', which ..."``); None when it can be."""
    for char, why in (("/", "separates the keys of a path"),
                      ("?", "starts the query of a URL"),
                      ("#", "starts the fragment of a URL")):
        if char in key:
            return f"contains {char!r}, which {why}"
    control = next((c for c in key if ord(c) < 32 or ord(c) == 127), None)
    if control is not None:
        return f"contains the control character {control!r}, which a URL cannot hold"
    escape = _URL_ESCAPE.search(key)
    if escape:
        return f"contains {escape.group()!r}, which a URL reads as an escaped character"
    if key in (".", ".."):
        return "is a dot segment, which a URL reads as a node or its parent"
    return None


def _checked_type(key, example):
    """``key`` when ``example`` (the key, or a template filled in) is a servable node key."""
    problem = key_problem(example)
    if problem:
        raise ValueError(f"type {key!r} {problem}; {TYPE_RULE}. Change the type (a '_' "
                         f"instead, say)")
    return key


class ArtifactSpec(BaseModel):
    """One array of every entity (``dataset``), or one per dataset in a group (``group``,
    ADR-0012), which ``tilewright manifest`` expands, so the manifest rows stay plain."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        min_length=1,
        description="Name of the array; becomes its key under the entity, and names its "
        "locators (`path_<type>`, `dataset_<type>`, `index_<type>`). With 'group', a "
        "template in which '{name}' stands for each member's name. Quote the template, "
        "as in `type: 'trace_{name}'`: YAML reads an unquoted brace as the start of a "
        "mapping. A literal brace in it is written '{{' or '}}'. Any character may "
        "appear except '/', '?', '#', an ASCII control character (tab, newline) and a "
        "'%' followed by two hex digits ('%20'), and the type may not be '.' or '..': it "
        "travels in a URL, so the server would not serve such an array back. Dots, "
        "spaces, brackets, '-', '|', a leading '_' or '.', and non-ASCII "
        "letters all work, and a dot does not nest the locators. A type is taken "
        "exactly as written, so 'gain_a' and 'Gain_A' are two different arrays of one "
        "entity, and only an exact repeat is a duplicate. With --upload, a "
        "server that keeps arrays as files names a directory after the type, "
        "URL-escaped as Python's urllib.parse.quote_plus does it, so that must also fit "
        "in one file name, 255 bytes on most filesystems.",
    )
    dataset: str | None = Field(
        default=None,
        min_length=1,
        description="HDF5 path of the array: absolute for 'files' and 'batch', relative to "
        "each entity group for 'groups'. Give either 'dataset' or 'group'.",
    )
    group: str | None = Field(
        default=None,
        min_length=1,
        description="HDF5 path of a group, instead of 'dataset': the entry becomes one "
        "artifact per dataset directly in the group, in sorted name order. Scalar (0-dim) "
        "datasets are included; subgroups, and datasets with no dataspace (h5py.Empty), "
        "are skipped. Absolute for 'files', relative to each entity group for 'groups'; "
        "a 'batch' source does not take it, because its first artifact sets the batch "
        "size. 'type' must hold '{name}', and nothing else in braces: "
        "`{type: 'trace_{name}', group: /channels}` gives trace_ch_a ... "
        "trace_ch_d for /channels/ch_a ... /channels/ch_d, and `{type: '{name}', group: "
        "/frames}` gives frame_0000 ... frame_0099 for /frames/frame_0000 ... "
        "/frames/frame_0099. The types must stay unique within an entity after this "
        "expansion, shared types included, and a member whose name makes a type that "
        "breaks the 'type' rule is an error that names it. A string dataset is a member "
        "too, and registration refuses a variable-length one (an artifact error): leave "
        "it out with 'members'. A group that is absent, or that holds no dataset "
        "matching 'members', is an error unless 'optional'. Each member becomes "
        "an array node of its own, so thousands of per-step datasets register slowly and "
        "read back one step at a time: stack them into one array, or into a 'batch' file, "
        "before onboarding.",
    )
    members: str = Field(
        default="*",
        min_length=1,
        description="With 'group' only: an fnmatch pattern that a member's name must "
        "match, case-sensitive. '*' takes every dataset in the group; 'frame_00[0-4]?' "
        "takes frame_0000 ... frame_0049.",
    )
    optional: bool = Field(
        default=False,
        description="True if some entities lack this array (with 'group': the group, or "
        "every member that matches); it is skipped for them. Otherwise a missing array is "
        "an error.",
    )

    @model_validator(mode="after")
    def _one_way_to_name_arrays(self):
        if (self.dataset is None) == (self.group is None):
            raise ValueError("give exactly one of 'dataset' (one array) or 'group' (one "
                             "array per dataset in that group)")
        if self.group is None:
            if "members" in self.model_fields_set:
                raise ValueError("'members' picks the datasets of a 'group'; remove it, or "
                                 "name a 'group' instead of 'dataset'")
            if "{name}" in self.type:
                raise ValueError(f"type {self.type!r} holds '{{name}}', which only a 'group' "
                                 f"entry fills in; write the type out, or name a 'group'")
        else:
            try:
                fields = [(name, spec, conv) for _, name, spec, conv
                          in string.Formatter().parse(self.type) if name is not None]
            except ValueError as exc:
                raise ValueError(f"type {self.type!r} is not a template ({exc}); write a "
                                 f"literal brace as '{{{{' or '}}}}'") from None
            other = ["{" + name + (f"!{conv}" if conv else "") + (f":{spec}" if spec else "")
                     + "}" for name, spec, conv in fields
                     if (name, spec, conv) != ("name", "", None)]
            if other:
                raise ValueError(f"type {self.type!r} holds {', '.join(other)}; '{{name}}' is "
                                 f"the only placeholder, and a literal brace is written "
                                 f"'{{{{' or '}}}}'")
            if not fields:
                raise ValueError(f"type {self.type!r} has no '{{name}}': with 'group', each "
                                 f"member's name goes into its type, as in 'trace_{{name}}'")
        _checked_type(self.type, self.type.format(name="_") if self.group else self.type)
        return self


class SharedAxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        min_length=1,
        description="Name of the array; becomes its key under the dataset container. The "
        "characters allowed are those of an artifact 'type'.",
    )
    dataset: str = Field(
        min_length=1,
        description="Absolute HDF5 path (in every source) of an array identical for all "
        "entities. Read from the first file that holds it; every other file must agree. "
        "A file that does not hold the path at all is passed over silently, so one entry "
        "cannot reach values kept under a path that carries the entity's own name "
        "('/<sample>/energy_grid'), however identical: those belong in the dataset "
        "'metadata'. Nothing else is claimed about the values: an axis that repeats or "
        "runs backwards is a valid shared axis as long as every file agrees. A shared "
        "entry names one array: the 'group' form of 'artifacts' is not available here.",
    )

    @model_validator(mode="after")
    def _servable(self):
        _checked_type(self.type, self.type)
        return self


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
        description="Human-readable dataset name. The catalog key is derived from it: "
        "slug(label) keeps A-Z and 0-9 only, so every other character, a non-ASCII "
        "letter included, becomes '_' ('Fernández Powder' -> FERN_NDEZ_POWDER), and a "
        "label with no ASCII letter or digit at all is an error. Write the label as the "
        "name should read; the key is allowed to be the plainer spelling.",
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
        description="Arrays each entity exposes; at least one entry, except for 'table'. "
        "An entry names one array ('dataset') or every array in a group ('group'). The "
        "list says what the dataset serves, not what the files hold: an array no reader "
        "would ask for, a constant placeholder whose meaning is in its own attributes "
        "say, is left out, and nothing checks the files for arrays nobody named.",
    )
    shared: list[SharedAxisSpec] = Field(
        default_factory=list,
        description="Arrays shared by every entity, registered once under the dataset, "
        "each an array child of the dataset container under its 'type'. 'Axis' names the "
        "common case, not the rule: an array that belongs to the dataset rather than to "
        "an entity goes here whether or not it is a coordinate -- a normalization or "
        "lookup table, a detector mask, a response curve. Nothing of an axis is required "
        "of it, not a rank, a dtype or an order; the whole test is the one under "
        "'dataset', that every file holding that path agrees. An array that differs "
        "between entities is an artifact, not a shared entry.",
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
        grouped = [f"artifacts[{i}]" for i, a in enumerate(self.artifacts) if a.group]
        if grouped and self.source.tag == "batch":
            raise ValueError(f"{', '.join(grouped)}: a 'batch' source takes 'dataset' "
                             f"entries only, because its first artifact sets the batch "
                             f"size; name each array of the group in an entry of its own")
        # a 'group' entry's types are known only once the manifest expands it (ADR-0012)
        types = [a.type for a in self.artifacts if a.dataset] + [s.type for s in self.shared]
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
    or table path, the params spec (its ``location`` only when set), the entity group,
    ``exclude_groups`` when it names any (ADR-0011), the identity mode, and a table's
    ``id`` when it is a list. Two YAMLs for the same files share it; the same label over
    different files does not (``tilewright register`` refuses that).

    A single-column ``id`` is not hashed, so no table fingerprinted before ADR-0008
    changes; a list is, so switching a table to a composite id (which re-keys every
    entity) is refused as different data rather than registered beside the old keys.
    An ``artifacts`` entry is hashed only in the group form, as its ``group`` (without a
    ``/`` at either end) and ``members`` (ADR-0012): the spec, which ``register`` can read
    without opening a file, not the members a manifest found."""
    body = cfg.source.body
    params = getattr(body, "params", None)
    if params is not None:
        # model_dump includes defaults, so a params field added after ADR-0007 is dropped
        # while unset: no YAML without it gets a new fingerprint (ADR-0010).
        params = params.model_dump(
            by_alias=True, exclude={"location"} if params.location is None else None)
    facts = {
        "tag": cfg.source.tag,
        "directory": body.server_base_dir or body.directory,
        "pattern": getattr(body, "pattern", None) or getattr(body, "path", None),
        "params": params,
        "entity_group": getattr(body, "entity_group", None),
        "identity": str(cfg.source.identity),
    }
    if getattr(body, "exclude_groups", None):
        # a fact only when non-empty, so no YAML without it is re-fingerprinted; sorted,
        # since the order of the patterns changes no uid
        facts["exclude_groups"] = sorted(set(body.exclude_groups))
    if isinstance(getattr(body, "id", None), list):
        facts["id"] = body.id
    # the group as the manifest reads it: '/frames', 'frames' and '/frames/' are one group
    groups = sorted([a.group.strip("/"), a.members] for a in cfg.artifacts if a.group)
    if groups:  # a fact only then, so no YAML without a group entry changes
        facts["artifact_groups"] = groups
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:16]
