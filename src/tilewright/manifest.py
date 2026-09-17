"""``tilewright manifest``: a dataset YAML -> its two Parquet manifests.

Reads the contract (``contract.py``), walks the data once, and writes
``entities.parquet`` (uid + one column per parameter) and ``artifacts.parquet`` (uid,
type, file, dataset, index, shape, dtype, ...; a ``shared:`` axis is a row with no uid).
Shape and dtype are captured here so registration never opens a file.

Also the step that derives the catalog key: if the YAML has no ``key:``, slug(label) is
written into it. Identity follows ADR-0007: parameter-value hash by default, provenance
hash on request or when there are no parameters; duplicate uids are a hard error here,
never a silent merge at registration. Parameters come from inside each container and,
with ``params.location``, from the entity's path (ADR-0010).

    tilewright manifest .tilewright/datasets/<KEY>.yml            # -> .tilewright/manifests/<KEY>/
    tilewright manifest <yaml> --check                             # validate only
"""

import argparse
import datetime
import hashlib
import json
import os
import posixpath
import re
import sys
from collections import OrderedDict
from fnmatch import fnmatchcase
from pathlib import Path

import h5py
import hdf5plugin  # noqa: F401  registers the filters h5py lacks (LZ4, Bitshuffle, ...)
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .contract import (
    TYPE_RULE, ArtifactSpec, ContractError, DatasetConfig, Identity, ParamsSpec,
    SharedAxisSpec, climb, key_problem, load_dataset, slugify_key, source_fingerprint,
)
from .utils import ARTIFACT_STANDARD_COLS

# Column order of artifacts.parquet; any further column is metadata on the array node.
ARTIFACT_COLUMNS = ["uid", "type", "file", "dataset", "index", "file_size", "file_mtime",
                    "shape", "dtype"]


# ---------------------------------------------------------------------------
# YAML in, key out
# ---------------------------------------------------------------------------

def _yaml():
    y = YAML()
    y.preserve_quotes = True
    return y


def read_yaml(yaml_path):
    """Load a dataset YAML (comments preserved). Returns ``(cfg, raw, warnings)``.

    Prints nothing; raises ``ContractError`` on any contract problem.
    """
    with open(yaml_path) as f:
        raw = _yaml().load(f)
    cfg, warnings = load_dataset(raw)
    return cfg, raw, warnings


def stamp_key(yaml_path, raw, key):
    """Write ``key:`` into the YAML as one new line right after the ``label:`` line.

    Every other byte stays as the author wrote it: comments, quoting, flow lists, folded
    text, line widths. A label that spans several lines gets the key line just before
    it instead. A placement is kept only if the file then parses to its old data plus
    ``key``; when neither does (an empty ``key:``, a top-level flow mapping), the
    document is dumped whole, which keeps comments but not the layout. Returns whether
    the file was written.
    """
    if raw.get("key") == key:
        return False
    with open(yaml_path, newline="") as f:
        text = f.read()
    safe = YAML(typ="safe")

    def parses_as_before_plus_key(candidate):
        try:
            got = safe.load(candidate)
        except YAMLError:
            return False
        return isinstance(got, dict) and got.pop("key", None) == key and repr(got) == before

    try:
        before = repr(safe.load(text))
    except YAMLError:
        before = None
    if before is not None and "label" in raw and "key" not in raw:
        line, col = raw.lc.key("label")
        # Split where the YAML reader counts lines, keeping each line's own break.
        parts = re.split(r"(\r\n|[\r\n\x85\u2028\u2029])", text)
        breaks = parts[1::2]
        lines = [s + b for s, b in zip(parts[0::2], breaks + [""])]
        eol = breaks[line] if line < len(breaks) else (breaks[0] if breaks else "\n")
        stamp = " " * col + f"key: {key}"
        for at in (line + 1, line):
            head, tail = "".join(lines[:at]), "".join(lines[at:])
            candidate = head + stamp + eol + tail if at < len(lines) else head + eol + stamp
            if parses_as_before_plus_key(candidate):
                with open(yaml_path, "w", newline="") as f:
                    f.write(candidate)
                return True

    if "key" in raw:
        raw["key"] = key
    else:
        raw.insert(list(raw.keys()).index("label") + 1 if "label" in raw else 0, "key", key)
    with open(yaml_path, "w") as f:
        _yaml().dump(raw, f)
    return True


def manifest_dir(yaml_path, key):
    """Where a YAML's manifests go: ``<root>/manifests/<KEY>/`` where ``<root>`` is the
    YAML's directory, or its parent when the YAML sits in a ``datasets/`` directory (the
    ``.tilewright/datasets/<KEY>.yml`` -> ``.tilewright/manifests/<KEY>/`` layout)."""
    here = Path(yaml_path).resolve().parent
    root = here.parent if here.name == "datasets" else here
    return root / "manifests" / key


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

def generate_manifests(yaml_path, output_dir=None, append=False):
    """Generate the two manifests for one YAML. Returns ``(entities_path, artifacts_path)``.

    Writes ``key:`` into the YAML when absent. Raises ``ContractError`` for contract
    problems and ``ValueError``/``KeyError`` with the file and path named for data
    problems.
    """
    cfg, raw, warnings = read_yaml(yaml_path)
    for w in warnings:
        print(f"  note: {w}")
    key = cfg.catalog_key
    if stamp_key(yaml_path, raw, key):
        print(f"  key: '{key}' written into {yaml_path} (slug of label '{cfg.label}')")

    output_dir = Path(output_dir) if output_dir else manifest_dir(yaml_path, key)
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_uids = set()
    ent_path, art_path = output_dir / "entities.parquet", output_dir / "artifacts.parquet"
    if append and ent_path.exists():
        existing_uids = set(pd.read_parquet(ent_path, columns=["uid"])["uid"])
        print(f"  append: {len(existing_uids)} existing entities will be skipped")

    tag, body = cfg.source.tag, cfg.source.body
    identity = cfg.source.identity
    walker = _Walker(cfg, existing_uids)
    if tag == "table":
        ent_rows, art_rows, shared_rows = walker.table(), [], []
    else:
        files = _find_files(body.directory, body.pattern)
        print(f"  {len(files)} files match {body.pattern!r} under {body.directory}")
        ent_rows, art_rows = {"files": walker.files, "batch": walker.batch,
                              "groups": walker.groups}[tag](files)
        shared_rows = _shared_axis_rows(files, Path(body.directory), cfg.shared, cfg.source)

    _check_collisions(ent_rows, key, cfg.source)
    for row in ent_rows:
        row.pop("_provenance", None)

    ent_df = pd.DataFrame(ent_rows, columns=["uid"] if not ent_rows else None)
    art_df = pd.DataFrame(art_rows + shared_rows,
                          columns=ARTIFACT_COLUMNS if not (art_rows + shared_rows) else None)
    if append and existing_uids and art_path.exists():
        old_ent, old_art = pd.read_parquet(ent_path), pd.read_parquet(art_path)
        old_art = old_art[old_art["uid"].notna()]  # shared axes are re-resolved each run
        ent_df = pd.concat([old_ent, ent_df], ignore_index=True)
        art_df = pd.concat([old_art, art_df], ignore_index=True)
        print(f"  merged: {len(old_ent)} existing + {len(ent_rows)} new entities")

    meta = {
        b"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().encode(),
        b"generator": b"tilewright",
        b"key": key.encode(),
        b"source": tag.encode(),
        b"identity": str(identity).encode(),
        b"fingerprint": source_fingerprint(cfg).encode(),
        b"config_hash": _sha256_file(yaml_path).encode(),
        b"entity_count": str(len(ent_df)).encode(),
        b"artifact_count": str(len(art_rows)).encode(),
        b"shared_count": str(len(shared_rows)).encode(),
    }
    for df, path in ((ent_df, ent_path), (art_df, art_path)):
        table = _arrow_table(df, path.name)
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})
        pq.write_table(table, path)

    print(f"dataset={key} entities={len(ent_df)} artifacts={len(art_rows)} "
          f"shared={len(shared_rows)} -> {output_dir}")
    return str(ent_path), str(art_path)


_ARROW_ERRORS = (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError)


def _arrow_table(df, name):
    """``df`` as an Arrow table, with any column Arrow cannot type stored as JSON text.

    One Parquet file holds every artifact type and the shared rows, and every file of a
    source is read on its own, so one column can hold a list in one row and a scalar in
    the next (an attribute that is an array for one type only), or two kinds of value
    (#31). Arrow has no type for such a column: it is written as JSON text, with one note
    naming it, rather than ending the run after the whole walk. Every other column keeps
    the type it has today.
    """
    try:
        return pa.Table.from_pandas(df, preserve_index=False)
    except _ARROW_ERRORS:
        pass
    out = df.copy()
    for column in df.columns:
        try:
            pa.Table.from_pandas(df[[column]], preserve_index=False)
        except _ARROW_ERRORS:
            out[column] = [None if v is None or (isinstance(v, float) and np.isnan(v))
                           else json.dumps(v, default=str) for v in df[column]]
            print(f"  note: column '{column}' of {name} holds values of more than one "
                  f"kind across rows; stored as JSON text")
    return pa.Table.from_pandas(out, preserve_index=False)


def _find_files(directory, pattern):
    root = Path(directory)
    files = sorted(root.glob(pattern)) or sorted(root.rglob(pattern))
    files = [p for p in files if p.is_file()]
    if not files:
        raise FileNotFoundError(f"no files match {pattern!r} under {directory}")
    return files


def _sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _check_collisions(ent_rows, key, source):
    """Two entities with the same uid is a contract error, named, never a silent merge.

    For every shared uid the report says where each entity came from and lists each
    column (parameter) whose values differ between them, one value per entity in that
    order; under ``identity: params`` it also shows the parameters they share. One Fix
    line follows, chosen by the source's tag and identity.
    """
    by_uid = {}
    for row in ent_rows:
        by_uid.setdefault(row["uid"], []).append(row)
    dupes = {u: rows for u, rows in by_uid.items() if len(rows) > 1}
    if not dupes:
        return
    table = source.tag == "table"
    by_params = not table and source.identity == Identity.params
    ids = source.body.id if table else []
    ids = [ids] if isinstance(ids, str) else list(ids)
    lines = [f"{key}: {sum(len(r) for r in dupes.values())} entities share "
             f"{len(dupes)} uids; every entity must be distinct."]
    cover, some_equal = [], False  # one differing column per uid tells every group apart
    for u, rows in dupes.items():
        where = ", ".join(str(r.get("_provenance", "?")) for r in rows)
        if table:
            where = (", ".join(f"{c}={json.dumps(rows[0].get(c), default=str)}" for c in ids)
                     + f" at table rows {where} (first data row = 0)")
        lines.append(f"  uid {u}: {where}")
        names = [k for k in dict.fromkeys(k for r in rows for k in r)
                 if k not in ("uid", "source_group") and not k.startswith("_")]
        equal, differing = {}, []
        for name in names:
            values = [json.dumps(r[name], default=str, sort_keys=True) if name in r
                      else "(absent)" for r in rows]
            if len(set(values)) == 1:
                equal[name] = rows[0][name]
                continue
            lines.append(f"    {name}: " + " | ".join(
                v if len(v) <= 60 else v[:57] + "..." for v in values))
            differing.append(name)
        if differing and not set(differing) & set(cover):
            cover.append(differing[0])
        if len(equal) == len(names):
            some_equal = True
            lines.append(f"    no {'column' if table else 'parameter'} differs")
        if by_params and equal:
            lines.append(f"    equal: {json.dumps(equal, default=str)[:160]}")
    if table and cover:
        lines.append(f"Fix: for each uid, list one of the columns that differ in 'id', so "
                     f"that together they are unique, e.g. id: [{', '.join(ids + cover)}]."
                     + (" Rows equal in every column are duplicates: de-duplicate the "
                        "table." if some_equal else ""))
    elif table:
        lines.append("Fix: these rows are equal in every column; de-duplicate the table.")
    elif by_params:
        lines.append("Fix: add a field that distinguishes them (a run number, a seed) to the "
                     "parameters, from inside the container or from its path with "
                     "'params.location', or set 'identity: provenance' under the source.")
    else:
        lines.append("Fix: these entities have the same provenance; the pattern or "
                     "entity_group is matching the same thing twice.")
    raise ValueError("\n".join(lines))


# ---------------------------------------------------------------------------
# reading parameters and attributes
# ---------------------------------------------------------------------------

# HDF5's own bookkeeping attributes (the dimension-scale machinery, and the two netCDF-4
# writes to tie a variable to its dimensions). Never carried along. DIMENSION_LABELS is
# not one of them: it holds the axis names, and is kept (#31).
_HDF5_INTERNAL_ATTRS = frozenset({"CLASS", "NAME", "REFERENCE_LIST", "DIMENSION_LIST",
                                  "_Netcdf4Coordinates", "_Netcdf4Dimid"})
# Artifact-manifest columns the broker writes; a dataset attribute of the same name would
# overwrite the column, so it is dropped with one warning per (path, attribute).
_ARTIFACT_RESERVED = ARTIFACT_STANDARD_COLS | {"file_size", "file_mtime"}
_reserved_warned = set()
_unstorable_noted = set()


def _to_python(val):
    if isinstance(val, h5py.Empty):  # a null dataspace (netCDF's empty attribute): no value
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, np.generic):
        return val.item()
    if isinstance(val, np.ndarray):
        # a size-1 array is a scalar; its item can be bytes (an '|S' array), so convert it too
        return _to_python(val.item()) if val.size == 1 else val.tolist()
    return val


def _as_label(val):
    """A ``_to_python`` value as a label: ``(value, problem)``, ``problem`` None when it
    is stored. A label holds what a ``from: attrs`` parameter holds — a str, int, float,
    bool or None, or a list of them, which is what an array attribute's ``tolist()``
    gives (#31) — and nothing HDF5 alone can resolve, such as an object or region
    reference, whose target no catalog can follow."""
    if isinstance(val, bytes):                      # an '|S' array's elements
        return val.decode("utf-8", errors="replace"), None
    if isinstance(val, (h5py.Reference, h5py.RegionReference)):
        return None, "HDF5 object references cannot be stored"
    if val is None or isinstance(val, (str, bool, int, float)):
        return val, None
    if isinstance(val, (list, tuple)):
        kept = []
        for item in val:
            value, problem = _as_label(item)
            if problem:
                return None, problem
            kept.append(value)
        return kept, None
    return None, f"a value of type {type(val).__name__} cannot be stored"


def _attrs(obj, label_of=None, skip=()):
    """HDF5 attributes of ``obj`` as native values, sorted by name.

    ``label_of`` None: every attribute (the ``from: attrs`` parameters). ``label_of`` a
    field name: its attributes as ``<field>_<attr>`` labels of that field. ``label_of``
    ``""``: bare names, for an artifact's own node metadata (manifest column names are
    dropped with a warning). Labels are stored beside a value, never hashed into the uid.
    They carry what a ``from: attrs`` parameter carries (``_as_label``); one that cannot
    be stored is left out with one note per (object, attribute). An empty attribute
    (``h5py.Empty``) is None: kept as a null parameter, and left out of labels. Names in
    ``skip`` (``params.exclude``) are never read.
    """
    out = OrderedDict()
    for name in sorted(obj.attrs.keys()):
        if name in skip:
            continue
        val = _to_python(obj.attrs[name])
        if label_of is None:
            out[name] = val
            continue
        if name in _HDF5_INTERNAL_ATTRS:
            continue
        if label_of == "" and name in _ARTIFACT_RESERVED:
            if (obj.name, name) not in _reserved_warned:
                _reserved_warned.add((obj.name, name))
                print(f"  WARNING: {obj.name}@{name} is not carried as array metadata: "
                      f"'{name}' is a manifest column. Rename the attribute if you need it.")
            continue
        value, problem = _as_label(val)
        if problem:
            if (obj.name, name) not in _unstorable_noted:
                _unstorable_noted.add((obj.name, name))
                print(f"  note: {obj.name}@{name} is not carried as "
                      f"{'array metadata' if label_of == '' else 'a label'}: {problem}")
        elif value is not None:
            out[f"{label_of}_{name}" if label_of else name] = value
    return out


def _read_params(container, spec: ParamsSpec, batch_size=None, siblings=None, closed=None):
    """One entity's (or one batch file's) parameters from its container.

    Returns ``(params, labels)``. ``params`` maps dotted keys (``instrument.Ei``) to values,
    or in batch mode to length-N arrays; ``labels`` are the fields' attribute labels.

    ``siblings`` is ``(i, n, memo)`` for a ``groups`` entity: its position among the n
    entity groups beside it, and a dict the n share. A group path that starts with ``..``
    leaves the entity group (ADR-0011); such a group is read once for the n siblings, by
    the batch rule with N = n, and the entity takes element i. The contract refuses
    ``recursive`` on such a path. ``closed`` maps the object id of every entity group of
    the file being read, and of every group ``entity_group`` matched in it, to its path:
    a hard link cannot lead out of the subtree recursion stays in, so it is the one way
    such a group is still reached from inside another one (ADR-0013, ``_read_group``).
    """
    out, labels = OrderedDict(), OrderedDict()
    for gname, gpath in spec.paths.items():
        ups, rest = climb(gpath)
        if not ups:
            found = _read_group(container, rest, gname, gpath, spec, batch_size, closed)
        else:
            i, n, memo = siblings
            above = [p for p in container.name.split("/") if p]
            if ups > len(above):
                field = f"groups.{gname}" if gname else "group"
                raise ValueError(
                    f"{container.file.filename}:{container.name}: params.{field} {gpath!r} "
                    f"climbs {ups} levels from an entity group {len(above)} levels below the "
                    f"file root, so above the root; remove {ups - len(above)} '..'")
            if gname not in memo:
                where = "/".join(above[:len(above) - ups] + [rest]).strip("/")
                memo[gname] = _read_group(container.file, where, gname, gpath, spec,
                                          None if spec.from_ == "attrs" else n)
            found = memo[gname]
            if spec.from_ == "datasets":
                found = ({k: _to_python(v[i]) for k, v in found[0].items()}, found[1])
        out.update(found[0])
        labels.update(found[1])
    return out, labels


def _read_group(holder, path, gname, frame, spec: ParamsSpec, batch_size=None, closed=None):
    """The parameters and labels of the one group (or, under ``from: attrs``, dataset) at
    ``path`` in ``holder``, with keys nested under ``gname``. ``frame`` is the path as
    written in the YAML, against which ``spec.exclude`` is matched.

    The rule splits at the group the author named (ADR-0013). Its own members are read as
    they are without ``recursive``, a link there followed wherever it leads; ``recursive``
    -- descending into a subgroup, and everything read below that group -- follows only
    what lies inside its subtree, subgroups and datasets alike, each member placed by the
    object it resolves to rather than by the text of a path (``_outside``). A member that
    leads out, a subgroup already on the
    path being read, which a link back to an ancestor makes (#29) and whose walk would
    never end, and a subgroup ``closed`` names, are each named in a WARNING and skipped.
    Groups on the path, and those ``closed`` names, are told apart by their HDF5 object id
    (``Group.id``), which compares equal whichever link opened them.

    A member HDF5 cannot resolve at all is named and skipped the same way, whether it is a
    link that leads nowhere (``KeyError``) or one HDF5 refuses to follow (``RuntimeError``:
    a chain longer than its link limit, which a cycle reaches at once). One unreadable
    member costs its own value, never the run (#40).

    Under ``from: attrs`` a container that does not hold the group (or dataset) is an
    error naming both, since there its attributes are the parameters."""
    written, frame = frame, frame.strip("/")
    exclude = {p.strip("/") for p in spec.exclude}
    out = OrderedDict()
    if spec.from_ == "attrs":
        target = holder.get(path) if path else holder
        if target is None:
            field = f"params.groups.{gname}" if gname else "params.group"
            where = "/" + "/".join(p for p in (holder.name.strip("/"), path.strip("/")) if p)
            raise KeyError(
                f"{holder.file.filename}:{where}: {field} {written!r} names no group or "
                f"dataset there, and under 'from: attrs' a group that a container lacks "
                f"is an error, since its attributes are the parameters. Fix: narrow "
                f"'pattern' (and 'entity_group') to the containers that hold it, name a "
                f"group every one of them has, or read the parameters with "
                f"'from: datasets', where a missing group leaves null columns")
        # an attribute's exclude path is '<group path>/<name>': '/version' at the root
        left_out = {n for n in target.attrs if f"{frame}/{n}".strip("/") in exclude}
        for name, val in _attrs(target, skip=left_out).items():
            key = f"{gname}.{name}" if gname else name
            out[key] = np.full(batch_size, val) if batch_size else val
        return out, OrderedDict()
    labels = OrderedDict()
    if path and not (path in holder and isinstance(holder[path], h5py.Group)):
        return out, labels
    start = holder[path] if path else holder["/"] if isinstance(holder, h5py.File) else holder
    root = (start, start.name.rstrip("/") or "/")   # the subtree recursion stays in
    pending = [(start, "", ((start.id, start.name),))]   # with the groups above each one
    while pending:
        g, prefix, ancestors = pending.pop(0)
        for name in sorted(g.keys()):
            rel = f"{prefix}/{name}" if prefix else name
            if f"{frame}/{rel}".strip("/") in exclude:
                continue
            try:
                obj = g[name]
            except (KeyError, RuntimeError) as e:  # dangling, or a chain HDF5 will not follow
                print(f"  WARNING: {g.file.filename}:{g.name.rstrip('/')}/{name} "
                      f"unreadable ({e}); skipped")
                continue
            link = f"{g.file.filename}:{g.name.rstrip('/')}/{name}"
            if isinstance(obj, h5py.Group):
                if spec.recursive:
                    away = _outside(g, name, obj, root)
                    back = next((n for i, n in ancestors if i == obj.id), None)
                    if away is not None:
                        print(f"  WARNING: {link} links to {away}, outside the group "
                              f"being read ({root[1]}); skipped")
                    elif back is not None:
                        print(f"  WARNING: {link} links back to {back}, which is already "
                              f"being read; skipped")
                    elif closed and obj.id in closed:
                        print(f"  WARNING: {link} links into {closed[obj.id]}, an entity "
                              f"group of this dataset; skipped")
                    else:
                        pending.append((obj, rel, ancestors + ((obj.id, obj.name),)))
                continue
            if not isinstance(obj, h5py.Dataset):
                continue
            if prefix:    # below the group the author named: recursion, so the same rule
                away = _outside(g, name, obj, root)
                if away is not None:
                    print(f"  WARNING: {link} links to {away}, outside the group being "
                          f"read ({root[1]}); skipped")
                    continue
            key = ".".join(p for p in (gname, *rel.split("/")) if p)
            # A scalar is a 0-dim or a size-1 dataset (NeXus writes scalars as shape
            # (1,)). In 'batch' a scalar is broadcast to every row whatever N is, and a
            # 1-D dataset of length N > 1 is one value per row. With N == 1 a length-1
            # dataset is both, and both readings give the one row the same value.
            if obj.ndim == 0 or obj.size == 1:
                val = _to_python(obj[()])
                out[key] = np.full(batch_size, val) if batch_size else val
            elif batch_size and obj.ndim == 1 and obj.shape[0] == batch_size:
                out[key] = obj[:]
            else:
                continue
            labels.update(_attrs(obj, label_of=key))
    return out, labels


def _outside(holder, name, obj, root, hops=32):
    """Where the member ``name`` of the group ``holder``, which HDF5 resolves to ``obj``,
    leads when that is not inside the subtree recursion stays in -- as ``<file>:<path>``,
    or as ``<file>`` where only the file is known; None when it is inside (ADR-0013).
    ``root`` is ``(group, path)`` of the group the walk started from.

    Both tests are made on the **object** a name resolves to, never on the text of a path,
    and both before any value is read. A path is not evidence: any component of it can be
    a link, and ``h5py`` resolves every link inside a path it is handed in one ``get()``.

    1. The target path is walked **component by component** from the group the walk started
       from. Each component is read with ``get(..., getlink=True)``, which reports the link
       and resolves nothing (``h5py`` reports the *opened* path for a linked object, so
       ``Group.name`` cannot say where a link led). A soft link met at a component is
       tested like any other and the walk starts again at its target, so the one loop
       covers the member itself, every hop of a **chain** (``hop -> direct ->
       /elsewhere``), and every segment of a path that *runs through* a link
       (``sub/hop -> /entry/out/gain``, where ``out`` links to ``/elsewhere``: jumping to
       the parent of the target lands at ``/elsewhere`` with the link that led there never
       tested).
    2. The **file** of ``obj``, independently: an object whose ``file.filename`` differs
       from that of the group the walk started from is in another file, whatever its path
       says, and is named by that file. An external link is the only way to reach one, so
       the walk names it first and more precisely; this stands behind the walk and decides
       the cross-file half on its own.

    Each kind of link, in the walk:

    - an **external link** resolves in another file, so it is never inside the subtree.
      Its own file name -- made absolute against the file that holds it, as HDF5 resolves
      a relative one -- and its own path are reported, so that a soft link reaching it
      does not pair the target file with a path in the source file;
    - a **soft link**'s target path, resolved against the group that holds the link when
      it is relative, must be the group the walk started from or one under it, in that
      file; when it is, the walk goes on through that path's own components, and whatever
      is still to be walked below the link follows them;
    - a **hard link** is one of the object's own names, and that name is inside the group
      that holds it, so the walk descends it (or, at the end of the path, ends inside) --
      which is why ``closed`` is still needed for an entity group a hard link names from
      inside another one.

    ``hops`` bounds the soft links the walk may follow; descending a hard link is a step
    along a path the file already holds and costs none. HDF5 traverses at most 16 links
    before it refuses to resolve one (``H5Pset_nlinks``), so twice that never decides for a
    member the library could open, a path of any depth inside the subtree is still walked
    to its end, and a file that manages to loop is named and skipped rather than walked for
    ever (the guarantee of #29).
    """
    start, path = root
    fileno, base = start.id.fileno, path.rstrip("/")   # '' when the subtree is the root
    where, member, below, links = holder, name, (), 0
    while True:
        link = where.get(member, getlink=True)
        if isinstance(link, h5py.ExternalLink):
            other = link.filename
            if not posixpath.isabs(other):
                other = posixpath.normpath(
                    posixpath.join(posixpath.dirname(where.file.filename), other))
            return f"{other}:{link.path}"
        if isinstance(link, h5py.SoftLink):
            target = posixpath.normpath(link.path if link.path.startswith("/")
                                        else f"{where.name.rstrip('/')}/{link.path}")
            links += 1
            if links > hops or not (where.id.fileno == fileno and (
                    not base or target == base or target.startswith(f"{base}/"))):
                return f"{where.file.filename}:{target}"
            where = start           # the target's own components, then what was left
            below = tuple(p for p in target[len(base):].split("/") if p) + below
        elif link is not None and below:
            child = where[member]   # a hard link: this one component crosses none
            if not isinstance(child, h5py.Group):
                break               # a dataset: nothing below it to walk
            where = child
        else:
            break                   # a hard link at the end of the path, or nothing there
        if not below:
            break                   # every component walked, and each one inside
        member, below = below[0], below[1:]
    if obj.file.filename != start.file.filename:
        return obj.file.filename
    return None


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

_INT_TEXT = re.compile(r"[+-]?\d+")
_FLOAT_TEXT = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


def _from_text(text):
    """A value captured by ``params.location``, typed by its text (ADR-0010): an integer
    literal is an int (``'0042'`` -> 42), a decimal or exponent literal a float, anything
    else the string itself; a group that took no part in the match stays None."""
    if text is None:
        return None
    if _INT_TEXT.fullmatch(text):
        return int(text)
    if _FLOAT_TEXT.fullmatch(text):
        return float(text)
    return text


def _uid(payload):
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _params_uid(key, params):
    # A float keeps 12 decimal places or 12 significant digits, whichever is more digits.
    # From |v| >= 0.1 that is round(v, 12), the rule before #4, so those uids (nan and inf
    # included) are unchanged. Below 0.1 it is 12 significant digits, so SI-unit values
    # (1e-13 s) stay apart: 12 decimal places turned every |v| < 5e-13 into 0.0.
    canonical = {k: (float(f"{v:.12g}") if abs(v) < 0.1 else round(v, 12))
                 if isinstance(v, float) else v
                 for k, v in sorted(params.items())}
    return _uid(json.dumps({"ns": key, "params": canonical}, sort_keys=True, default=str))


def _file_fingerprint(path):
    st = os.stat(path)
    mtime = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).isoformat()
    return st.st_size, mtime


def _artifact_row(uid, art_type, rel_path, dataset, index, fsize, fmtime, shape, dtype,
                  labels=None):
    """``shape`` is the shape *as registered* (batch rows have the leading axis dropped),
    JSON-encoded for an exact Parquet round trip."""
    row = OrderedDict(uid=uid, type=art_type, file=rel_path, dataset=dataset, index=index,
                      file_size=fsize, file_mtime=fmtime, shape=json.dumps(list(shape)),
                      dtype=dtype)
    row.update(labels or {})
    return row


def _get_artifact(f, path, art: ArtifactSpec, where):
    """The HDF5 dataset for an artifact, or None if optional and absent."""
    p = path.lstrip("/")
    if p in f and isinstance(f[p], h5py.Dataset):
        return f[p]
    if art.optional:
        return None
    raise KeyError(f"{where}: artifact type={art.type!r} dataset {path!r} not found "
                   f"(mark it 'optional: true' if some entities lack it)")


class _Walker:
    """The four source walkers share one way of naming an entity and resolving its uid."""

    def __init__(self, cfg: DatasetConfig, existing_uids):
        self.cfg = cfg
        self.key = cfg.catalog_key
        self.body = cfg.source.body
        self.identity = cfg.source.identity
        self.artifacts = cfg.artifacts
        self.existing = existing_uids
        self.root = Path(self.body.directory)
        # Registration writes each artifact's locators beside the parameters under these
        # names (reference/manifest.md). A table declares no artifacts, so none for it;
        # the types of a 'group' entry are added per entity, once expanded (ADR-0012).
        self.reserved = {f"{kind}_{art.type}": art.type for art in cfg.artifacts
                         if art.dataset for kind in ("path", "dataset", "index")}

    def located(self, params, labels, location, where):
        """``params`` with the named groups of ``params.location`` searched in the entity's
        ``location`` (its provenance string) added in front. Raises when the location does
        not match, or when a name is also read in the container: as a key, as the parent
        of a dotted key (registration nests those), or as a ``<field>_<attr>`` label."""
        spec = self.body.params
        if spec is None or spec.location is None:
            return params
        match = re.search(spec.location, location)
        if match is None:
            raise ValueError(f"{where}: its location {location!r} does not match "
                             f"params.location {spec.location!r}; widen the expression, or "
                             f"narrow 'pattern' to the entities it describes")
        found = {name: _from_text(text) for name, text in match.groupdict().items()}
        for inside in (*params, *labels):
            name = inside.split(".")[0]
            if name in found:
                container = "entity group" if self.cfg.source.tag == "groups" else "file"
                raise ValueError(f"{where}: params.location names {name!r}, and {inside!r} "
                                 f"is also read inside the {container}; rename the group "
                                 f"in 'location', or leave the other out with 'exclude'")
        return {**found, **params}

    def uid(self, params, provenance, where):
        if self.identity == Identity.params:
            if not params:
                raise ValueError(f"{where}: no parameters found, so no identity. Either "
                                 f"point 'params' at the right group, declare 'params: "
                                 f"null', or set 'identity: provenance'.")
            return _params_uid(self.key, params)
        return _uid(f"{self.key}:{provenance}")

    def entity(self, uid, params, labels, provenance, source_group=None, artifacts=()):
        """The entity's row. ``artifacts`` are its expanded ones (``expand``), whose types
        reserve their locator names too."""
        row = OrderedDict(uid=uid)
        if source_group is not None:
            row["source_group"] = source_group
        row.update(params)
        row.update(labels)
        reserved = {**self.reserved, **{f"{kind}_{art_type}": art_type
                                        for art_type, _, _ in artifacts
                                        for kind in ("path", "dataset", "index")}}
        if reserved:
            for name in row:
                if name.split(".", 1)[0] in reserved:  # a dotted name nests under it
                    raise ValueError(self.reserved_error(name, params, provenance, reserved))
        row["_provenance"] = provenance  # dropped before writing; used by collision report
        return row

    def expand(self, f, base, where):
        """One entity's artifacts, as ``(type, dataset path, h5py dataset)``.

        A ``dataset`` entry gives one, or none when optional and absent. A ``group``
        entry gives one per dataset directly in its group whose name matches ``members``,
        in sorted name order, with ``{name}`` in its type filled in (ADR-0012). ``base``
        is the entity group's path, ``''`` for a file. A type that comes twice, from two
        entries or from an entry and a shared axis, is an error naming both.
        """
        out = []
        given = {ax.type: f"shared[{k}] (dataset {ax.dataset!r})"
                 for k, ax in enumerate(self.cfg.shared)}
        for i, art in enumerate(self.artifacts):
            if art.dataset:
                path = f"/{base}/{art.dataset.lstrip('/')}" if base else art.dataset
                ds = _get_artifact(f, path, art, where)
                found = [] if ds is None else [
                    (art.type, path, ds, f"artifacts[{i}] (dataset {art.dataset!r})")]
            else:
                gpath = "/" + "/".join(p for p in (base, art.group.strip("/")) if p)
                group = f.get(gpath)
                if not isinstance(group, h5py.Group):
                    if group is None and art.optional:
                        continue
                    raise KeyError(f"{where}: artifact type={art.type!r} group {gpath!r} "
                                   + ("is a dataset: name it with 'dataset'" if group
                                      else "not found (mark it 'optional: true' if some "
                                           "entities lack it)"))
                found = []
                for name in sorted(group):
                    if not fnmatchcase(name, art.members):
                        continue
                    full = f"{gpath.rstrip('/')}/{name}"  # gpath is '/' for the root group
                    try:
                        ds = group[name]
                    except (KeyError, RuntimeError) as e:  # dangling, or a chain HDF5 won't follow
                        print(f"  WARNING: {where}: {full} unreadable ({e}); skipped")
                        continue
                    if not isinstance(ds, h5py.Dataset) or ds.shape is None:
                        continue
                    art_type = art.type.format(name=name)
                    problem = key_problem(art_type)
                    if problem:
                        raise ValueError(
                            f"{where}: artifact type={art.type!r} group {gpath!r}: the member "
                            f"{name!r} gives the type {art_type!r}, and that type {problem}; "
                            f"{TYPE_RULE}. Leave the member out with 'members', or rename "
                            f"it in the file")
                    found.append((art_type, full, ds,
                                  f"artifacts[{i}] (type {art.type!r}, group {art.group!r}, "
                                  f"member {name!r})"))
                if not found and not art.optional:
                    held = sorted(n for n in group if isinstance(group.get(n), h5py.Dataset))
                    raise ValueError(
                        f"{where}: artifact type={art.type!r} group {gpath!r} has no dataset "
                        f"whose name matches members {art.members!r}; it holds "
                        f"{len(held)} datasets" + (f" ({', '.join(map(repr, held[:3]))}"
                                                   f"{', ...' if len(held) > 3 else ''})"
                                                   if held else "")
                        + ". Correct 'members' or 'group', or mark the entry 'optional: "
                          "true' if some entities lack them")
            for art_type, path, ds, entry in found:
                if art_type in given:
                    raise ValueError(f"{where}: {given[art_type]} and {entry} both give the "
                                     f"type {art_type!r}; types must be unique within an "
                                     f"entity, since each becomes a node key. Change a "
                                     f"'type', or narrow 'members'")
                given[art_type] = entry
                out.append((art_type, path, ds))
        return out

    def reserved_error(self, name, params, provenance, reserved):
        """The message for a parameter or label named like a locator. The fix depends on
        where the name came from: a params.location group, a params.groups name, an
        attribute, a dataset, or a dataset's attribute label."""
        head = name.split(".", 1)[0]
        what, field, rename = f"parameter '{name}'", name, "rename it in the file"
        if name not in params:  # a '<field>_<attr>' label
            field = max((k for k in params if name.startswith(f"{k}_")), key=len,
                        default=name)
            attr = name[len(field) + 1:]
            what = f"label '{name}' (attribute '{attr}' of parameter '{field}')"
            rename = f"rename the attribute '{attr}' in the file"
        spec = self.body.params
        if spec.from_ == "attrs":
            rename = f"rename the attribute '{name}' in the file"
        if spec.location is not None and name in re.compile(spec.location).groupindex:
            fix = f"rename the named group '{name}' in params.location."
        elif spec.groups:
            fix = f"rename '{head}' under params.groups."
        else:
            # exclude names an attribute by its whole name, a dataset by its first part
            leaf = name if spec.from_ == "attrs" else field.split(".", 1)[0]
            path = "/" + "/".join(p for p in ((spec.group or "").strip("/"), leaf) if p)
            fix = (f"add '{path}' to params.exclude under the source"
                   + (f" (this also leaves out the parameter '{field}')"
                      if field != name else "")
                   + f", or {rename}.")
        return (f"{self.root / str(provenance)}: {what} is named like a locator: "
                f"registration writes the locator of artifact '{reserved[head]}' under "
                f"the name '{head}'. path_<type>, dataset_<type> and index_<type> are "
                f"reserved for every artifact type.\nFix: {fix}")

    # -- files ---------------------------------------------------------------

    def files(self, paths):
        ent_rows, art_rows = [], []
        spec = self.body.params
        for i, h5_path in enumerate(paths):
            rel = h5_path.relative_to(self.root).as_posix()
            with h5py.File(h5_path, "r") as f:
                params, labels = _read_params(f, spec) if spec is not None else ({}, {})
                params = self.located(params, labels, rel, str(h5_path))
                uid = self.uid(params, rel, str(h5_path))
                if uid in self.existing:
                    continue
                fsize, fmtime = _file_fingerprint(h5_path)
                arts = self.expand(f, "", str(h5_path))
                ent_rows.append(self.entity(uid, params, labels, rel, artifacts=arts))
                for art_type, path, ds in arts:
                    art_rows.append(_artifact_row(uid, art_type, rel, path, None,
                                                  fsize, fmtime, ds.shape, str(ds.dtype),
                                                  labels=_attrs(ds, label_of="")))
            if (i + 1) % 1000 == 0:
                print(f"  {i + 1}/{len(paths)} files")
        return ent_rows, art_rows

    # -- batch ---------------------------------------------------------------

    def batch(self, paths):
        ent_rows, art_rows = [], []
        spec = self.body.params
        for h5_path in paths:
            rel = h5_path.relative_to(self.root).as_posix()
            fsize, fmtime = _file_fingerprint(h5_path)
            with h5py.File(h5_path, "r") as f:
                first = _get_artifact(f, self.artifacts[0].dataset, self.artifacts[0], str(h5_path))
                if first is None:
                    raise KeyError(f"{h5_path}: the first artifact ({self.artifacts[0].type}) "
                                   f"sets the batch size and cannot be optional")
                n = first.shape[0]
                art_info = {}
                for art in self.artifacts:
                    ds = _get_artifact(f, art.dataset, art, str(h5_path))
                    if ds is None:
                        continue
                    if ds.shape[0] != n:
                        raise ValueError(f"{h5_path}: artifact {art.type!r} has {ds.shape[0]} "
                                         f"rows but {self.artifacts[0].type!r} has {n}; every "
                                         f"artifact's leading axis is the entity axis")
                    art_info[art.type] = (ds.shape[1:], str(ds.dtype), _attrs(ds, label_of=""))
                columns, labels = (_read_params(f, spec, batch_size=n)
                                   if spec is not None else ({}, {}))
                for i in range(n):
                    params = {k: _to_python(v[i]) for k, v in columns.items()}
                    prov = f"{rel}:{i}"
                    params = self.located(params, labels, prov, f"{h5_path} row {i}")
                    uid = self.uid(params, prov, f"{h5_path} row {i}")
                    if uid in self.existing:
                        continue
                    ent_rows.append(self.entity(uid, params, labels, prov))
                    for art in self.artifacts:
                        if art.type not in art_info:
                            continue
                        shape, dtype, alabels = art_info[art.type]
                        art_rows.append(_artifact_row(uid, art.type, rel, art.dataset, i,
                                                      fsize, fmtime, shape, dtype, labels=alabels))
            print(f"  {h5_path.name}: {n} entities")
        return ent_rows, art_rows

    # -- groups --------------------------------------------------------------

    def groups(self, paths):
        ent_rows, art_rows = [], []
        spec = self.body.params
        pattern = (self.body.entity_group or "").strip("/")
        excluded = self.body.exclude_groups
        for h5_path in paths:
            rel = h5_path.relative_to(self.root).as_posix()
            fsize, fmtime = _file_fingerprint(h5_path)
            with h5py.File(h5_path, "r") as f:
                # each group entity_group matches, with its entity groups (ADR-0011)
                parents = _entity_groups(f, pattern, excluded)
                if not parents:
                    raise KeyError(f"{h5_path}: entity_group '/{pattern}' matches no group")
                count = sum(len(names) for _, names in parents)
                if not count:
                    raise ValueError(f"{h5_path}: no groups under entity_group '/{pattern}' "
                                     f"to treat as entities"
                                     + (" (after exclude_groups)" if excluded else ""))
                # the groups of this file that are entities of their own, by object id: a
                # hard link is the one link that still names one from inside another
                closed = {f[base or "/"].id: f"/{base}" for base, _ in parents}
                for base, names in parents:
                    parent = f[base] if base else f
                    for n in names:
                        closed[parent[n].id] = "/" + (f"{base}/{n}" if base else n)
                for base, names in parents:
                    memo = {}  # a group reached through '..' is read once per sibling set
                    gpaths = [f"{base}/{n}" if base else n for n in names]
                    for i, gpath in enumerate(gpaths):
                        g = f[gpath]
                        siblings = (i, len(gpaths), memo)
                        params, labels = (_read_params(g, spec, siblings=siblings,
                                                       closed=closed)
                                          if spec is not None else ({}, {}))
                        prov = f"{rel}:/{gpath}"
                        params = self.located(params, labels, prov, f"{h5_path}:/{gpath}")
                        uid = self.uid(params, prov, f"{h5_path}:/{gpath}")
                        if uid in self.existing:
                            continue
                        arts = self.expand(f, gpath, f"{h5_path}:/{gpath}")
                        ent_rows.append(self.entity(uid, params, labels, prov,
                                                    source_group=gpath, artifacts=arts))
                        for art_type, full, ds in arts:
                            art_rows.append(_artifact_row(uid, art_type, rel, full, None,
                                                          fsize, fmtime, ds.shape,
                                                          str(ds.dtype),
                                                          labels=_attrs(ds, label_of="")))
            print(f"  {h5_path.name}: {count} entity groups")
        return ent_rows, art_rows

    # -- table ---------------------------------------------------------------

    def table(self):
        path = self.root / self.body.path
        if not path.exists():
            raise FileNotFoundError(f"{path}: table not found")
        df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        ids = self.body.id
        for column in [ids] if isinstance(ids, str) else ids:
            if column not in df.columns:
                raise KeyError(f"{path}: id column {column!r} not among {list(df.columns)}")
        if "uid" in df.columns:
            raise ValueError(f"{path}: 'uid' is a reserved column name")
        ent_rows = []
        for i, record in enumerate(df.to_dict(orient="records")):
            params = {k: _to_python(v) for k, v in record.items()}
            for name, template in self.body.locator.items():
                params[name] = template.format(**record)
            # one column: its value, as before ADR-0008; several: the JSON list of values
            value = (str(record[ids]) if isinstance(ids, str) else
                     json.dumps([_to_python(record[c]) for c in ids], default=str))
            uid = _uid(f"{self.key}:{value}")
            if uid in self.existing:
                continue
            ent_rows.append(self.entity(uid, params, {}, i))
        print(f"  {path.name}: {len(ent_rows)} rows")
        return ent_rows


def _entity_groups(f, pattern, excluded):
    """One file's entity groups: for each group ``entity_group`` matches, its path and the
    sorted names of its subgroups that ``exclude_groups`` does not name (ADR-0011)."""
    parents = []
    for base in _matching_groups(f, pattern):
        parent = f[base] if base else f
        parents.append((base, sorted(
            k for k in parent.keys() if isinstance(parent[k], h5py.Group)
            and not any(fnmatchcase(k, x) for x in excluded))))
    return parents


def _matching_groups(f, pattern):
    """The paths (no leading '/') of the groups ``entity_group`` names in ``f``, sorted:
    each segment of ``pattern`` is a group name or an fnmatch glob over the names at that
    level (ADR-0011). An empty pattern is the root, ``''``."""
    found = [""]
    for segment in (s for s in pattern.split("/") if s):
        glob = any(c in segment for c in "*?[")
        deeper = []
        for base in found:
            here = f[base] if base else f
            names = sorted(here.keys()) if glob else [segment]
            deeper += [f"{base}/{n}" if base else n for n in names
                       if fnmatchcase(n, segment) and isinstance(here.get(n), h5py.Group)]
        found = deeper
    return found


def _shared_axis_rows(paths, root, shared: list[SharedAxisSpec], source=None):
    """One artifact row per ``shared:`` axis, uid None: an artifact of the dataset.

    Recorded from the path the entry names, in the first file that holds it; **every copy
    the source holds** must agree with it (a differing copy varies per entity, so it
    belongs under ``artifacts:``). Which copies the source holds depends on its tag (#37):

    - ``files``, ``batch``, ``table``: the named path, in each file;
    - ``groups``: the named path lies inside one entity group, so each entity group of
      each file holds its own copy, at the same path relative to its own group. One file
      with four entity groups holds four copies, and comparing files alone would compare
      none of them. A path outside the entity groups (a calibration group beside them) is
      one copy per file, as under the other tags.

    ``source`` is the YAML's source block; without it every tag reads as ``files``, which
    is what a caller that hands over a file list and nothing else means.
    """
    rows, seen, recorded = [], {}, set()
    if not shared:
        return rows
    grouped = source is not None and source.tag == "groups"
    pattern = (source.body.entity_group or "").strip("/") if grouped else ""
    excluded = source.body.exclude_groups if grouped else ()
    for h5_path in paths:
        rel = h5_path.relative_to(root).as_posix()
        with h5py.File(h5_path, "r") as f:
            bases = [f"{base}/{n}" if base else n
                     for base, names in _entity_groups(f, pattern, excluded)
                     for n in names] if grouped else []
            for ax in shared:
                named = ax.dataset.lstrip("/")
                # the entity group the entry names a copy in, and the same path in each of
                # its siblings; outside them (and under every other tag) the one named path
                inside = next((b for b in bases if named.startswith(f"{b}/")), None)
                copies = ([named] + [f"{b}/{named[len(inside) + 1:]}"
                                     for b in bases if b != inside]) if inside else [named]
                for p in copies:
                    if p not in f or not isinstance(f[p], h5py.Dataset):
                        continue
                    ds = f[p]
                    here = f"{rel}:/{p}"
                    if ax.type in seen:
                        ref_where, ref = seen[ax.type]
                        equal_nan = bool(np.issubdtype(ref.dtype, np.floating))
                        if (ds.shape != ref.shape
                                or not np.array_equal(ds[()], ref, equal_nan=equal_nan)):
                            raise ValueError(
                                f"shared axis {ax.type!r} ({ax.dataset}) differs between "
                                f"{ref_where} and {here}; a shared axis must be identical in "
                                f"every copy the source holds. If it varies per entity, list "
                                f"it under 'artifacts:'.")
                    else:
                        seen[ax.type] = (here, ds[()])
                    if p == named and ax.type not in recorded:
                        recorded.add(ax.type)
                        fsize, fmtime = _file_fingerprint(h5_path)
                        rows.append(_artifact_row(None, ax.type, rel, ax.dataset, None, fsize,
                                                  fmtime, ds.shape, str(ds.dtype),
                                                  labels=_attrs(ds, label_of="")))
    missing = [ax for ax in shared if ax.type not in recorded]
    if missing:
        raise KeyError(f"shared axis {missing[0].type!r}: dataset {missing[0].dataset!r} not "
                       f"found in any of the {len(paths)} files under {root}")
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tilewright manifest",
        description="Validate a dataset YAML and generate its Parquet manifests.")
    parser.add_argument("yaml_path", help="the dataset YAML")
    parser.add_argument("-o", "--output-dir", help="where to write the manifests "
                        "(default: <root>/manifests/<KEY>/ next to the YAML)")
    parser.add_argument("--append", action="store_true",
                        help="keep existing manifests and add only new entities")
    parser.add_argument("--check", action="store_true",
                        help="validate the contract and stop; writes nothing")
    args = parser.parse_args(argv)

    try:
        if args.check:
            cfg, raw, warnings = read_yaml(args.yaml_path)
            for w in warnings:
                print(f"  note: {w}")
            key = cfg.catalog_key
            print(f"contract OK: key={key} source={cfg.source.tag} identity={cfg.source.identity} "
                  f"artifacts={len(cfg.artifacts)} shared={len(cfg.shared)}"
                  + ("" if raw.get("key") else f"  (key will be written by 'tilewright manifest')"))
            return 0
        generate_manifests(args.yaml_path, args.output_dir, append=args.append)
        return 0
    except ContractError as e:
        print(str(e), file=sys.stderr)
        return 1
    except (FileNotFoundError, KeyError, ValueError) as e:
        # A KeyError's str() is the repr of its argument, so a message written for a
        # reader would come out double-quoted with its own quotes escaped. Each of these
        # carries exactly one message; print it as it was written.
        message = e.args[0] if isinstance(e, KeyError) and len(e.args) == 1 else e
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
