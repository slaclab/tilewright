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
    ArtifactSpec, ContractError, DatasetConfig, Identity, ParamsSpec, SharedAxisSpec,
    climb, load_dataset, slugify_key, source_fingerprint,
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
        shared_rows = _shared_axis_rows(files, Path(body.directory), cfg.shared)

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
        table = pa.Table.from_pandas(df, preserve_index=False)
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})
        pq.write_table(table, path)

    print(f"dataset={key} entities={len(ent_df)} artifacts={len(art_rows)} "
          f"shared={len(shared_rows)} -> {output_dir}")
    return str(ent_path), str(art_path)


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

# HDF5's own bookkeeping attributes (dimension-scale machinery). Never carried along.
_HDF5_INTERNAL_ATTRS = frozenset(
    {"CLASS", "NAME", "REFERENCE_LIST", "DIMENSION_LIST", "DIMENSION_LABELS"}
)
# Artifact-manifest columns the broker writes; a dataset attribute of the same name would
# overwrite the column, so it is dropped with one warning per (path, attribute).
_ARTIFACT_RESERVED = ARTIFACT_STANDARD_COLS | {"file_size", "file_mtime"}
_reserved_warned = set()


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


def _attrs(obj, label_of=None, skip=()):
    """HDF5 attributes of ``obj`` as native values, sorted by name.

    ``label_of`` None: every attribute (the ``from: attrs`` parameters). ``label_of`` a
    field name: scalar attributes as ``<field>_<attr>`` labels of that field. ``label_of``
    ``""``: bare names, for an artifact's own node metadata (manifest column names are
    dropped with a warning). Labels are stored beside a value, never hashed into the uid.
    An empty attribute (``h5py.Empty``) is None: kept as a null parameter, and left out of
    labels, which carry only str, int and float. Names in ``skip`` (``params.exclude``)
    are never read.
    """
    out = OrderedDict()
    for name in sorted(obj.attrs.keys()):
        if name in skip:
            continue
        val = _to_python(obj.attrs[name])
        if label_of is None:
            out[name] = val
        elif name in _HDF5_INTERNAL_ATTRS:
            continue
        elif label_of == "" and name in _ARTIFACT_RESERVED:
            if (obj.name, name) not in _reserved_warned:
                _reserved_warned.add((obj.name, name))
                print(f"  WARNING: {obj.name}@{name} is not carried as array metadata: "
                      f"'{name}' is a manifest column. Rename the attribute if you need it.")
        elif isinstance(val, (str, int, float)) and not isinstance(val, bool):
            out[f"{label_of}_{name}" if label_of else name] = val
    return out


def _read_params(container, spec: ParamsSpec, batch_size=None, siblings=None, skip=()):
    """One entity's (or one batch file's) parameters from its container.

    Returns ``(params, labels)``. ``params`` maps dotted keys (``instrument.Ei``) to values,
    or in batch mode to length-N arrays; ``labels`` are the fields' attribute labels.

    ``siblings`` is ``(i, n, memo)`` for a ``groups`` entity: its position among the n
    entity groups beside it, and a dict the n share. A group path that starts with ``..``
    leaves the entity group (ADR-0011); such a group is read once for the n siblings, by
    the batch rule with N = n, and the entity takes element i. The contract refuses
    ``recursive`` on such a path. ``skip`` holds the object ids of the groups that
    recursion never enters, whatever link leads to them (see ``_read_group``).
    """
    out, labels = OrderedDict(), OrderedDict()
    for gname, gpath in spec.paths.items():
        ups, rest = climb(gpath)
        if not ups:
            found = _read_group(container, rest, gname, gpath, spec, batch_size, skip)
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


def _read_group(holder, path, gname, frame, spec: ParamsSpec, batch_size=None, skip=()):
    """The parameters and labels of the one group (or, under ``from: attrs``, dataset) at
    ``path`` in ``holder``, with keys nested under ``gname``. ``frame`` is the path as
    written in the YAML, against which ``spec.exclude`` is matched; ``recursive`` does
    not descend into the groups whose object ids (``Group.id``) are in ``skip``: an id
    compares equal whichever link the group was opened through."""
    frame = frame.strip("/")
    exclude = {p.strip("/") for p in spec.exclude}
    out = OrderedDict()
    if spec.from_ == "attrs":
        target = holder[path] if path else holder
        # an attribute's exclude path is '<group path>/<name>': '/version' at the root
        left_out = {n for n in target.attrs if f"{frame}/{n}".strip("/") in exclude}
        for name, val in _attrs(target, skip=left_out).items():
            key = f"{gname}.{name}" if gname else name
            out[key] = np.full(batch_size, val) if batch_size else val
        return out, OrderedDict()
    labels = OrderedDict()
    if path and not (path in holder and isinstance(holder[path], h5py.Group)):
        return out, labels
    pending = [(holder[path] if path else holder, "")]
    while pending:
        g, prefix = pending.pop(0)
        for name in sorted(g.keys()):
            rel = f"{prefix}/{name}" if prefix else name
            if f"{frame}/{rel}".strip("/") in exclude:
                continue
            try:
                obj = g[name]
            except KeyError as e:  # dangling link
                print(f"  WARNING: {g.file.filename}:{g.name}/{name} unreadable ({e}); skipped")
                continue
            if isinstance(obj, h5py.Group):
                if spec.recursive and obj.id not in skip:
                    pending.append((obj, rel))
                continue
            if not isinstance(obj, h5py.Dataset):
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
        # names (reference/manifest.md). A table declares no artifacts, so none for it.
        self.reserved = {f"{kind}_{art.type}": art.type for art in cfg.artifacts
                         for kind in ("path", "dataset", "index")}

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

    def entity(self, uid, params, labels, provenance, source_group=None):
        row = OrderedDict(uid=uid)
        if source_group is not None:
            row["source_group"] = source_group
        row.update(params)
        row.update(labels)
        if self.reserved:
            for name in row:
                if name.split(".", 1)[0] in self.reserved:  # a dotted name nests under it
                    raise ValueError(self.reserved_error(name, params, provenance))
        row["_provenance"] = provenance  # dropped before writing; used by collision report
        return row

    def reserved_error(self, name, params, provenance):
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
                f"registration writes the locator of artifact '{self.reserved[head]}' under "
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
                ent_rows.append(self.entity(uid, params, labels, rel))
                for art in self.artifacts:
                    ds = _get_artifact(f, art.dataset, art, str(h5_path))
                    if ds is None:
                        continue
                    art_rows.append(_artifact_row(uid, art.type, rel, art.dataset, None,
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
                parents = []
                for base in _matching_groups(f, pattern):
                    parent = f[base] if base else f
                    parents.append((base, sorted(
                        k for k in parent.keys() if isinstance(parent[k], h5py.Group)
                        and not any(fnmatchcase(k, x) for x in excluded))))
                if not parents:
                    raise KeyError(f"{h5_path}: entity_group '/{pattern}' matches no group")
                count = sum(len(names) for _, names in parents)
                if not count:
                    raise ValueError(f"{h5_path}: no groups under entity_group '/{pattern}' "
                                     f"to treat as entities"
                                     + (" (after exclude_groups)" if excluded else ""))
                # every matched group and every entity group of the file, as HDF5 objects,
                # so that a link to one is the same group: recursion inside an entity group
                # enters none of them, whatever link leads there (ADR-0011)
                closed = {f[base or "/"].id for base, _ in parents} | {
                    f[base or "/"][n].id for base, names in parents for n in names}
                for base, names in parents:
                    memo = {}  # a group reached through '..' is read once per sibling set
                    gpaths = [f"{base}/{n}" if base else n for n in names]
                    for i, gpath in enumerate(gpaths):
                        g = f[gpath]
                        siblings = (i, len(gpaths), memo)
                        params, labels = (_read_params(g, spec, siblings=siblings,
                                                       skip=closed)
                                          if spec is not None else ({}, {}))
                        prov = f"{rel}:/{gpath}"
                        params = self.located(params, labels, prov, f"{h5_path}:/{gpath}")
                        uid = self.uid(params, prov, f"{h5_path}:/{gpath}")
                        if uid in self.existing:
                            continue
                        ent_rows.append(self.entity(uid, params, labels, prov,
                                                    source_group=gpath))
                        for art in self.artifacts:
                            full = f"/{gpath}/{art.dataset.lstrip('/')}"
                            ds = _get_artifact(f, full, art, f"{h5_path}:/{gpath}")
                            if ds is None:
                                continue
                            art_rows.append(_artifact_row(uid, art.type, rel, full, None,
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


def _shared_axis_rows(paths, root, shared: list[SharedAxisSpec]):
    """One artifact row per ``shared:`` axis, uid None: an artifact of the dataset.

    Recorded from the first file that holds it; every other file that holds it must agree
    (a differing axis varies per entity, so it belongs under ``artifacts:``).
    """
    rows, seen = [], {}
    if not shared:
        return rows
    for h5_path in paths:
        rel = h5_path.relative_to(root).as_posix()
        with h5py.File(h5_path, "r") as f:
            for ax in shared:
                p = ax.dataset.lstrip("/")
                if p not in f or not isinstance(f[p], h5py.Dataset):
                    continue
                ds = f[p]
                if ax.type in seen:
                    ref_file, ref = seen[ax.type]
                    equal_nan = bool(np.issubdtype(ref.dtype, np.floating))
                    if ds.shape != ref.shape or not np.array_equal(ds[()], ref, equal_nan=equal_nan):
                        raise ValueError(f"shared axis {ax.type!r} ({ax.dataset}) differs between "
                                         f"{ref_file} and {rel}; a shared axis must be identical "
                                         f"in every file. If it varies per entity, list it under "
                                         f"'artifacts:'.")
                    continue
                seen[ax.type] = (rel, ds[()])
                fsize, fmtime = _file_fingerprint(h5_path)
                rows.append(_artifact_row(None, ax.type, rel, ax.dataset, None, fsize, fmtime,
                                          ds.shape, str(ds.dtype), labels=_attrs(ds, label_of="")))
    missing = [ax for ax in shared if ax.type not in seen]
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
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
