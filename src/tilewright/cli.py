"""
CLI entry points for TileWright.

    tilewright manifest   validate a dataset YAML, derive its key, write its Parquet manifests
    tilewright register   register manifests into a running Tiled server over HTTP
    tilewright delete     delete registered data from a running Tiled server
"""

import os
import sys
import argparse
from pathlib import Path


def _load_dataset(config_path):
    """Read + validate a dataset YAML for register/delete. Exits with every contract
    error printed; requires the key that `tilewright manifest` writes."""
    from .contract import ContractError
    from .manifest import read_yaml

    try:
        cfg, raw, warnings = read_yaml(config_path)
    except ContractError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    for w in warnings:
        print(f"  note: {w}")
    if not raw.get("key"):
        print(f"\nERROR: {config_path} has no 'key:' yet. Run\n"
              f"    tilewright manifest {config_path}\n"
              f"to derive '{cfg.catalog_key}' from the label and build the manifests.",
              file=sys.stderr)
        sys.exit(1)
    return cfg


def _build_dataset_metadata(cfg):
    """The dataset container's metadata: every metadata key as written, plus one
    `shared_dataset_<type>` locator per shared axis (how readers find the axes)."""
    md = cfg.metadata.model_dump(by_alias=True, exclude_none=True)
    md.setdefault("label", cfg.label)
    for ax in cfg.shared:
        md[f"shared_dataset_{ax.type}"] = ax.dataset
    return md


def _manifest_stamps(ent_path):
    """What the dataset container carries from the manifest rather than the YAML: the
    field dictionary (``fields``) and, for ``entity: file``, the total row count
    (``rows``). Both are read from the Parquet schema metadata ``tilewright manifest``
    wrote; a manifest from before they existed stamps nothing."""
    import json
    import pyarrow.parquet as pq

    meta = pq.read_schema(ent_path).metadata or {}
    stamps = {}
    if b"fields" in meta:
        stamps["fields"] = json.loads(meta[b"fields"])
    if b"rows" in meta:
        stamps["rows"] = int(meta[b"rows"])
    return stamps


def _find_manifests(config_path, key):
    """The manifest pair for a YAML, or (None, None)."""
    from .manifest import manifest_dir

    d = manifest_dir(config_path, key)
    ep, ap = d / "entities.parquet", d / "artifacts.parquet"
    return (ep, ap) if ep.exists() and ap.exists() else (None, None)


# ── tilewright register ──────────────────────────────────────────────

def register_main():
    """HTTP registration against a running Tiled server (from register.py).

    Reads dataset config files (YAML), loads corresponding Parquet manifests
    from manifests/, and registers into a running Tiled server via HTTP.
    Incremental: skips entities that already exist.

    With --upload, artifact arrays are read from local HDF5 and written
    through the server into its writable storage (for data the server
    cannot read from its own filesystem).
    """
    parser = argparse.ArgumentParser(
        description="Register datasets into a running Tiled server via HTTP."
    )
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    parser.add_argument(
        "-n", "--max-entities",
        type=int,
        default=None,
        metavar="NUM",
        help="Limit number of entities per dataset (default: all)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        metavar="N",
        help="Concurrent registration workers "
             "(default: TILEWRIGHT_MAX_WORKERS env var, or 8)",
    )
    parser.add_argument("--url", default=None, metavar="URL",
                        help="Tiled server URL (default: $TILED_URL, else http://localhost:8005)")
    parser.add_argument("--api-key", default=None, metavar="KEY",
                        help="API key with write scopes (default: $TILED_API_KEY)")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Also merge-patch the dataset container's metadata from the YAML "
             "(same data only; the previous version is kept as a revision)",
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="Claim a container registered before fingerprints existed",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload artifact arrays through the server into its writable "
             "storage, instead of registering pointers to HDF5 files the "
             "server reads from disk. Use when the server cannot see your "
             "data's filesystem (e.g. registering from another institution).",
    )
    args = parser.parse_args()

    max_workers = args.max_workers
    if max_workers is None:
        env_val = os.environ.get("TILEWRIGHT_MAX_WORKERS")
        if env_val:
            max_workers = int(env_val)

    import pandas as pd
    import pyarrow.parquet as pq
    from tilewright.contract import source_fingerprint
    from tilewright.utils import check_server, server_settings
    from tilewright.register import register_dataset_http, verify_registration_http

    print("=" * 50)
    print("Register (HTTP)")
    print("=" * 50)
    print(f"Configs: {args.configs}")

    # Every YAML must be a valid, keyed contract before the network is touched.
    datasets = []
    for config_path in args.configs:
        if not Path(config_path).exists():
            print(f"\nERROR: Config not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        datasets.append((config_path, _load_dataset(config_path)))

    tiled_url, api_key = server_settings(args.url, args.api_key)

    print(f"\nChecking Tiled server at {tiled_url} ...")
    if not check_server(url=tiled_url, api_key=api_key):
        print(f"ERROR: Cannot reach Tiled server at {tiled_url}")
        if not api_key:
            print("\n  No API key set. Export TILED_API_KEY:")
            print("    export TILED_API_KEY=your-key-here")
        print("\n  To use a different server, pass --url or export TILED_URL.")
        sys.exit(1)
    print("Server is running.")

    from tiled.client import from_uri
    client = from_uri(tiled_url, api_key=api_key)
    print(f"Connected to {tiled_url} ({len(client)} existing containers)")

    stale_datasets = []
    for config_path, cfg in datasets:
        label, dataset_key = cfg.label, cfg.catalog_key
        body = cfg.source.body
        base_dir, server_base_dir = body.directory, body.server_base_dir

        if args.upload:
            if not os.path.isdir(base_dir):
                print(f"\nERROR: {config_path}: directory '{base_dir}' not found locally. "
                      "Upload mode reads artifact arrays from your local files.",
                      file=sys.stderr)
                sys.exit(1)
            if server_base_dir:
                print("NOTE: server_base_dir is ignored with --upload "
                      "(the server never reads your files).")

        ent_path, art_path = _find_manifests(config_path, dataset_key)
        if ent_path is None:
            from .manifest import manifest_dir
            print(f"\nERROR: no manifests for '{dataset_key}' in "
                  f"{manifest_dir(config_path, dataset_key)}.\n"
                  f"  Run `tilewright manifest {config_path}` to create them.", file=sys.stderr)
            sys.exit(1)

        ent_df = pd.read_parquet(ent_path)
        art_df = pd.read_parquet(art_path)
        fingerprint = source_fingerprint(cfg)
        stamped = (pq.read_schema(ent_path).metadata or {}).get(b"fingerprint", b"").decode()
        if stamped and stamped != fingerprint:
            print(f"\nERROR: the manifests in {ent_path.parent} were generated from a "
                  f"different source block than {config_path} now has. Run\n"
                  f"    tilewright manifest {config_path}\nto rebuild them.", file=sys.stderr)
            sys.exit(1)

        # Shared axes are artifact rows with no uid. A YAML that declares
        # `shared:` but whose manifest has none was generated before shared
        # axes were captured — regenerate rather than silently register the
        # dataset without them.
        if cfg.shared and art_df["uid"].notna().all():
            print(f"\nERROR: {config_path} declares shared axes but the manifests "
                  f"for '{dataset_key}' carry none. Run\n"
                  f"    tilewright manifest {config_path}\n"
                  f"to rebuild them, then register again.", file=sys.stderr)
            sys.exit(1)

        # Apply limit if specified
        if args.max_entities is not None:
            ent_df = ent_df.head(args.max_entities)

        dataset_metadata = {**_build_dataset_metadata(cfg), **_manifest_stamps(ent_path)}

        kwargs = {}
        if max_workers is not None:
            kwargs["max_workers"] = max_workers

        try:
            summary = register_dataset_http(client, ent_df, art_df, base_dir, label,
                                  dataset_key=dataset_key,
                                  dataset_metadata=dataset_metadata,
                                  server_base_dir=server_base_dir,
                                  upload=args.upload, fingerprint=fingerprint,
                                  update=args.update, adopt=args.adopt,
                                  **kwargs)
        except ValueError as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            sys.exit(1)
        stale = summary.stale
        if stale:
            print(f"\nERROR: {stale} artifact(s) of '{dataset_key}' changed on disk since they "
                  f"were registered; an existing artifact is never rewritten. Rebuild:\n"
                  f"    tilewright manifest {config_path}\n"
                  f"    tilewright delete {dataset_key}\n"
                  f"    tilewright register {config_path}", file=sys.stderr)
            stale_datasets.append(dataset_key)

    verify_registration_http(client, [cfg.catalog_key for _, cfg in datasets])
    if stale_datasets:
        sys.exit(1)

    print("\nDone!")


# ── tilewright delete ────────────────────────────────────────────────

def _normalize_url(url):
    """Canonical URL form for the `tilewright delete all` confirmation match.

    Lowercases scheme and host, strips trailing slashes from the path.
    Path/query/fragment case is preserved (paths are case-sensitive).
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        parts.query,
        parts.fragment,
    ))


def delete_main():
    """Delete registered data from a running Tiled server.

    Granularity is inferred from the number of positional arguments:

        tilewright delete <DATASET>                       # dataset + everything under it
        tilewright delete <DATASET> <ENTITY>              # one entity and its artifacts
        tilewright delete <DATASET> <ENTITY> <ARTIFACT>   # one artifact array
        tilewright delete all                             # every top-level container

    Note: `"all"` is a reserved sentinel — a dataset whose key is literally
    `all` (case-sensitive) cannot be deleted with the single-arg form.

    Confirmation:
      Granular forms prompt for 'y' or 'yes' (bypass with --yes).
      The 'all' form requires retyping the TILED_URL (bypass with
      --confirm <URL>, which must match exactly).

    External HDF5 files are never removed -- only catalog pointers. For
    datasets registered with --upload, the arrays the server stores are
    deleted along with the nodes (the catalog is their only home).
    """
    parser = argparse.ArgumentParser(
        prog="tilewright delete",
        description="Delete registered data from a running Tiled server.",
    )
    parser.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="DATASET [ENTITY [ARTIFACT]], or the sentinel 'all'",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the interactive y/yes confirmation (granular forms only)",
    )
    parser.add_argument(
        "--confirm",
        metavar="URL",
        help="Bypass the URL-retype prompt for 'all' (must match TILED_URL exactly)",
    )
    parser.add_argument("--url", default=None, metavar="URL",
                        help="Tiled server URL (default: $TILED_URL, else http://localhost:8005)")
    parser.add_argument("--api-key", default=None, metavar="KEY",
                        help="API key with write scopes (default: $TILED_API_KEY)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the preview block and exit without deleting",
    )
    args = parser.parse_args()

    from tilewright.utils import check_server, server_settings
    from tilewright.delete import (
        resolve_target, preview_counts, delete_target, delete_all, is_uploaded,
    )

    targets = args.targets
    is_all = targets[0] == "all"
    if is_all and len(targets) > 1:
        print("ERROR: 'all' takes no further arguments.")
        sys.exit(2)
    if not is_all and len(targets) > 3:
        print("ERROR: expected DATASET [ENTITY [ARTIFACT]] (got too many arguments).")
        sys.exit(2)

    print("=" * 50)
    print("Delete")
    print("=" * 50)

    tiled_url, api_key = server_settings(args.url, args.api_key)

    print(f"\nChecking Tiled server at {tiled_url} ...")
    if not check_server(url=tiled_url, api_key=api_key):
        print(f"ERROR: Cannot reach Tiled server at {tiled_url}")
        if not api_key:
            print("\n  No API key set. Export TILED_API_KEY:")
            print("    export TILED_API_KEY=your-key-here")
        print(f"\n  To use a different server, export TILED_URL:")
        print(f"    export TILED_URL={tiled_url}")
        sys.exit(1)
    print("Server is running.")

    from tiled.client import from_uri
    client = from_uri(tiled_url, api_key=api_key)

    # Resolve target and build preview
    uploaded = False
    if is_all:
        granularity = "all"
        path = "(every top-level container)"
        counts = preview_counts(client, granularity)
    else:
        try:
            node, path, granularity = resolve_target(client, *targets)
        except KeyError as e:
            print(f"\nERROR: {e}")
            sys.exit(1)
        counts = preview_counts(node, granularity)
        # The storage marker lives on the dataset container (targets[0]),
        # whichever granularity below it is being deleted.
        uploaded = is_uploaded(client[targets[0]])

    print(f"\nTarget:      {tiled_url}/{path}")
    print(f"Granularity: {granularity}")
    if granularity == "all":
        print(f"Counts:      {counts['n_children']} top-level container(s)")
        if counts["sample_keys"]:
            sample = ", ".join(counts["sample_keys"])
            more = "" if counts["n_children"] <= 10 else f", ... (+{counts['n_children'] - 10} more)"
            print(f"Sample:      {sample}{more}")
    elif granularity == "artifact":
        print(f"Counts:      1 array")
    else:
        print(f"Counts:      {counts['n_children']} child nodes")
    if is_all:
        print("Note:        External datasets keep their HDF5 files; uploaded "
              "datasets lose their server-stored arrays.")
    elif uploaded:
        print("Note:        Uploaded dataset — the arrays stored on the server "
              "WILL be deleted.")
    else:
        print("Note:        External HDF5 files are NOT removed; only catalog entries.")

    if args.dry_run:
        print("\n[--dry-run] No changes made.")
        sys.exit(0)

    # Confirm. Match URL after normalization (lowercase scheme+host, strip
    # trailing slash) so trivially-different shapes of the same URL succeed.
    expected = _normalize_url(tiled_url)
    if is_all:
        if args.confirm is not None:
            if _normalize_url(args.confirm) != expected:
                print(f"\nERROR: --confirm does not match TILED_URL ({tiled_url!r}).")
                sys.exit(1)
        else:
            if not sys.stdin.isatty():
                print("\nERROR: Non-interactive shell. Use --confirm <URL> to proceed.")
                sys.exit(2)
            typed = input(f"\nType the server URL to confirm: ")
            if _normalize_url(typed) != expected:
                print("Aborted: URL did not match.")
                sys.exit(1)
    else:
        if not args.yes:
            if not sys.stdin.isatty():
                print("\nERROR: Non-interactive shell. Use --yes to proceed.")
                sys.exit(2)
            typed = input(f"\nType 'y' or 'yes' to confirm: ").strip().lower()
            if typed not in ("y", "yes"):
                print("Aborted.")
                sys.exit(1)

    # Execute
    from tiled.client.utils import ClientError

    print()
    if is_all:
        successes, failures = delete_all(client)
        for k in successes:
            print(f"  deleted: {k}")
        for k, err in failures:
            print(f"  FAILED:  {k}  ({err})")
        print(f"\n{len(successes)} deleted, {len(failures)} failed.")
        sys.exit(1 if failures else 0)
    else:
        try:
            delete_target(node, external_only=not uploaded)
        except ClientError as e:
            print(f"  FAILED:  {path}")
            print(f"\nERROR: {e}")
            sys.exit(1)
        print(f"  deleted: {path}")
        print("\nDone.")


# ── tilewright (main dispatcher) ────────────────────────────────────

def _manifest_main():
    from .manifest import main
    sys.exit(main(sys.argv[1:]))


def main():
    """Main entry point: tilewright <command> [args]."""
    commands = {
        "manifest": _manifest_main,
        "register": register_main,
        "delete": delete_main,
    }

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("usage: tilewright <command> [args]\n")
        print("commands:")
        print("  manifest    Validate a dataset YAML, derive its key, write its Parquet manifests")
        print("  register    Register manifests into a running Tiled server over HTTP")
        print("  delete      Delete registered data from a running Tiled server")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands)}")
        sys.exit(1)

    # Remove the subcommand from argv so argparse in each handler sees the right args
    sys.argv = [f"tilewright {cmd}"] + sys.argv[2:]
    commands[cmd]()


if __name__ == "__main__":
    main()
