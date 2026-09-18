"""
Shared Utilities.

Common functions used across registration scripts.
"""

import datetime
import math
import os
import re
from collections.abc import Mapping

import numpy as np
import pandas as pd
from ruamel.yaml.scalarbool import ScalarBoolean


def server_settings(url=None, api_key=None):
    """Resolve the server to talk to: explicit values first, then the environment.

    ``TILED_URL`` (default ``http://localhost:8005``) and ``TILED_API_KEY``. Nothing is
    read from files; export the variables or pass ``--url`` / ``--api-key``.
    """
    url = url or os.environ.get("TILED_URL") or "http://localhost:8005"
    if api_key is None:
        api_key = os.environ.get("TILED_API_KEY", "")
    return url.rstrip("/"), api_key


def slugify_key(label):
    """Convert a human-readable label to the catalog key (UPPER_SNAKE).

    Rules: uppercase, replace runs of non-alphanumerics with a single
    underscore, strip leading/trailing underscores.

    Examples:
        "Broad Sigma"            -> "BROAD_SIGMA"
        "SUNNY NiPS3 10K"        -> "SUNNY_NIPS3_10K"
        "NiPS3 Multimodal"       -> "NIPS3_MULTIMODAL"
    """
    if not label:
        raise ValueError("slugify_key: label is empty")
    return re.sub(r"[^A-Z0-9]+", "_", str(label).upper()).strip("_")


# Dataset-container metadata marker recording where artifact bytes live.
# "external": array children point at HDF5 files the server reads from its
# own filesystem (`readable_storage`). "uploaded": arrays were written
# through the server into its writable storage — the server owns the bytes,
# and deleting the nodes deletes them.
STORAGE_KEY = "storage"
STORAGE_EXTERNAL = "external"
STORAGE_UPLOADED = "uploaded"

# Dataset-container metadata key holding contract.source_fingerprint(): which data the
# container describes, so two labels never silently merge (register.dataset_container).
FINGERPRINT_KEY = "fingerprint"


# Standard columns in the artifact manifest that are NOT stored as metadata.
# Everything else becomes artifact-level metadata dynamically.
# `shape`/`dtype` are here because registration re-emits them in structured form
# (a list of ints and a dtype string) — copying the manifest's JSON-encoded
# `shape` through as well would overwrite that with a raw string.
ARTIFACT_STANDARD_COLS = {"uid", "type", "file", "dataset", "index", "shape", "dtype"}


def to_json_safe(value, nonfinite=None, _key=""):
    """Convert a value to plain JSON types: dict, list, str, int, float, bool or None.

    Recurses into mappings, lists, tuples and arrays. A subclass of a builtin scalar
    becomes the builtin: ruamel's round-trip loader returns ``ScalarFloat`` for every
    float in a YAML, and the Tiled client's serializer (orjson) refuses float
    subclasses. Dates and times become ISO 8601 strings; None, NaN and NaT become None.

    ``inf`` and ``-inf`` are no more JSON numbers than NaN is, and the client's
    serializer writes any of them as null whatever is sent, so they become None here too
    (skills/onboarding/reference/manifest.md). ``nonfinite``, when given, is called with the key and the
    value before an infinity is dropped — with the path inside a mapping, ``limits.upper``
    — so that a caller can say once per key that the value was not stored. NaN is left to
    it silently: it is also what a row holds where it has no value for a column.
    """
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, Mapping):
        return {str(k): to_json_safe(v, nonfinite, ".".join(p for p in (_key, str(k)) if p))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v, nonfinite, _key) for v in value]
    if pd.isna(value):
        return None
    if isinstance(value, (bool, ScalarBoolean)):  # ScalarBoolean is an int subclass
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):   # ScalarFloat is one too
        if nonfinite is not None:
            nonfinite(_key, float(value))
        return None
    for plain in (str, int, float):
        if isinstance(value, plain):
            return plain(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def check_server(url=None, api_key=None):
    """Check if a Tiled server is running.

    Args:
        url: Server URL. Defaults to TILED_URL.
        api_key: API key. Defaults to TILED_API_KEY.

    Returns:
        bool: True if server responds, False otherwise.
    """
    import ssl
    import urllib.request
    import urllib.error

    url, api_key = server_settings(url, api_key)

    headers = {}
    if api_key:
        headers["Authorization"] = f"Apikey {api_key}"

    try:
        req = urllib.request.Request(f"{url}/api/v1/", headers=headers)
        # Allow self-signed certificates for internal HTTPS servers
        ctx = ssl.create_default_context()
        if url.startswith("https"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def make_entity_key(ent_row, dataset_key):
    """Generate the Tiled node key for an entity from its uid.

    The entity key is derived at registration time from the dataset key
    (slug(label)) and the first 13 characters of the entity's manifest
    uid, so it is not persisted in the manifest itself. ``_make_uid``
    returns 16-char hex (sha256 truncated), so 13 chars gives ample
    collision resistance within a dataset.

    Examples:
        >>> make_entity_key({"uid": "636ce3e41ea05f0f"}, "VDP_SIM")
        'VDP_SIM_636ce3e41ea05'
    """
    return f"{dataset_key}_{str(ent_row['uid'])[:13]}"


def make_artifact_key(art_row):
    """The Tiled node key for an artifact: its manifest ``type`` verbatim.

    `tilewright manifest` guarantees unique type values per entity,
    so the type is already the key (e.g. ``mh_powder_30T``, ``rixs``).
    """
    return art_row["type"]


def read_selection(ds, *selections):
    """``ds[s1][s2]...`` for an h5py dataset, asking h5py for only the elements it returns.

    The one read behind both read paths: a batch row then a user slice
    (``ds[index][slc]``), and a server block between the two
    (``ds[index][block][slc]``). Reading ``ds[index]`` first and slicing in memory would
    read the whole row; here every selection is folded into a single h5py index, so HDF5
    reads only the chunks that index touches.

    Each selection is numpy-style (an int, a slice, ``...``, or a tuple of those) and
    applies to what the previous ones left; a ``None`` selection is skipped. A negative
    step is read forwards and reversed in memory. A selection h5py cannot take (index
    arrays, masks, ``np.newaxis``), and every one after it, is applied in numpy to what
    the selections before it read.
    """
    axes = [range(n) for n in ds.shape]  # per dataset axis: the int or range still selected
    rest = [s for s in selections if s is not None]
    while rest:
        sel = tuple(rest[0]) if isinstance(rest[0], tuple) else (rest[0],)
        if not all(s is Ellipsis or isinstance(s, slice)
                   or (isinstance(s, (int, np.integer)) and not isinstance(s, bool))
                   for s in sel):
            break
        live = [d for d, a in enumerate(axes) if isinstance(a, range)]
        ellipses = [k for k, s in enumerate(sel) if s is Ellipsis]
        given = len(sel) - len(ellipses)
        if len(ellipses) > 1:
            raise IndexError("an index can only have a single ellipsis ('...')")
        if given > len(live):
            raise IndexError(f"too many indices for array: array is {len(live)}-dimensional, "
                             f"but {given} were indexed")
        at = ellipses[0] if ellipses else len(sel)
        sel = sel[:at] + (slice(None),) * (len(live) - given) + sel[at + 1:]
        for axis, (d, s) in enumerate(zip(live, sel)):
            if isinstance(s, slice):
                axes[d] = axes[d][s]
            elif -len(axes[d]) <= int(s) < len(axes[d]):
                axes[d] = axes[d][int(s)]
            else:
                raise IndexError(f"index {int(s)} is out of bounds for axis {axis} "
                                 f"with size {len(axes[d])}")
        rest.pop(0)

    key, flip = [], []
    for a in axes:
        if isinstance(a, int):
            key.append(a)
        elif not a:
            key.append(slice(0, 0))
            flip.append(slice(None))
        elif a.step > 0:
            key.append(slice(a[0], a[-1] + 1, a.step))
            flip.append(slice(None))
        else:  # h5py reads forwards only
            key.append(slice(a[-1], a[0] + 1, -a.step))
            flip.append(slice(None, None, -1))
    arr = ds[tuple(key)]
    if any(f.step for f in flip):
        arr = arr[tuple(flip)]
    for s in rest:
        arr = arr[s]
    return arr
