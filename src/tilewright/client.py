"""
Reading straight from the files: query the catalog for locators, open the HDF5 with h5py.

For readers on the same filesystem as the data. Everyone else reads through the server:
client["DATASET"]["entity"]["artifact"][:].

Usage:
    from tiled.client import from_uri
    from tiled.queries import Key
    from tilewright.client import query_catalog, load_artifacts

    client = from_uri("http://localhost:8005", api_key="secret")

    # Optional: pre-filter with Tiled's native query API
    filtered = client.search(Key("Ja_meV") >= 0).search(Key("Dc_meV") <= -0.5)

    # Step 1: Query — returns ALL entity metadata as a DataFrame
    manifest = query_catalog(filtered, artifact_type="mh_powder_30T")

    # Step 2: Load — returns raw arrays (no normalization)
    #   base_dir comes from the dataset's YAML config (e.g. config["base_dir"])
    arrays = load_artifacts(manifest, artifact_type="mh_powder_30T",
                            base_dir="/path/to/data")
    X = np.stack(arrays, dtype=np.float32)

    # Assemble Theta from the manifest (caller's choice of columns)
    Theta = manifest[["Ja_meV", "Jb_meV", "Jc_meV", "Dc_meV"]].to_numpy(dtype=np.float32)
"""

import os

import h5py
import numpy as np
import pandas as pd


def query_catalog(client, artifact_type, limit=None):
    """Query Tiled catalog and return all entity metadata as a DataFrame.

    Args:
        client: Tiled client. Pre-filter with client.search(Key(...)) before
            calling to scope results. Only entities with a locator for
            artifact_type are included.
            NOTE: The catalog has a two-level hierarchy (root -> datasets ->
            entities). Pass a dataset-level client or a search() result, not
            the root client.
        artifact_type: Artifact type string (e.g. "mh_powder_30T", "rixs").
            Must match the 'type' column used when the manifest was generated.
        limit: If set, stop after collecting this many rows. Useful for
            testing or previewing large catalogs.

    Returns:
        DataFrame with all entity metadata columns plus 'ent_key'.
        Locator columns (path_{type}, dataset_{type}, and optionally
        index_{type}) are included alongside physics parameters.
        Returns an empty DataFrame if no matching entities are found.
    """
    path_col = f"path_{artifact_type}"
    rows = []
    for ent_key, node in client.items():
        meta = dict(node.metadata)
        if path_col not in meta:
            continue
        meta["ent_key"] = ent_key
        rows.append(meta)
        if limit is not None and len(rows) >= limit:
            break
    return pd.DataFrame(rows)


def load_artifacts(manifest_df, artifact_type, base_dir):
    """Load artifact arrays directly from HDF5 using locator columns.

    Args:
        manifest_df: DataFrame from query_catalog() containing locator columns.
        artifact_type: Artifact type string matching the query_catalog call.
        base_dir: Base directory for resolving relative HDF5 file paths.
            Typically from the dataset's YAML config (config["base_dir"]).

    Returns:
        list[np.ndarray]: Raw arrays, one per manifest row, in row order.
            No normalization is applied — that is the caller's responsibility.

    Raises:
        KeyError: If manifest_df is missing the expected locator columns.
        FileNotFoundError: If an HDF5 file referenced in the manifest does
            not exist.
    """
    path_col = f"path_{artifact_type}"
    dataset_col = f"dataset_{artifact_type}"
    index_col = f"index_{artifact_type}"

    arrays = []
    for _, row in manifest_df.iterrows():
        path = os.path.join(base_dir, row[path_col])
        with h5py.File(path, "r") as f:
            ds = f[row[dataset_col]]
            if index_col in manifest_df.columns and pd.notna(row.get(index_col)):
                arrays.append(ds[int(row[index_col])])
            else:
                arrays.append(ds[:])
    return arrays


def locate(entity):
    """Where each of an entity's artifacts lives on disk: ``{type: {file, dataset, index}}``.

    Read off the ``path_<type>`` / ``dataset_<type>`` / ``index_<type>`` locators that
    registration stamps on every entity. ``file`` is relative to the dataset's directory
    (the caller knows where that is mounted); ``index`` is the row for batch sources,
    else None.
    """
    meta = dict(entity.metadata)
    out = {}
    for k, v in meta.items():
        if k.startswith("path_"):
            t = k[len("path_"):]
            idx = meta.get(f"index_{t}")
            out[t] = {"file": v, "dataset": meta[f"dataset_{t}"],
                      "index": None if idx is None else int(idx)}
    return out


def load(entity, artifact_type, base_dir, slc=None):
    """Read one artifact of one entity straight from its HDF5 file with h5py.

    For readers on the same filesystem as the data. ``slc`` is applied *after* the batch
    row index (``ds[index][slc]``), which is the one detail that is easy to get wrong.
    """
    loc = locate(entity)[artifact_type]
    with h5py.File(os.path.join(base_dir, loc["file"]), "r") as f:
        ds = f[loc["dataset"]]
        arr = ds[loc["index"]] if loc["index"] is not None else ds[()]
    return arr if slc is None else arr[slc]
