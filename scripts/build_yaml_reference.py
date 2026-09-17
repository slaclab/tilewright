"""Generate docs/reference/dataset-yaml.md from the contract models.

The pydantic models in src/tilewright/contract.py are the single source of truth for the
dataset YAML; this script renders their fields and descriptions into the reference page so
the docs cannot drift from the code. Run it after any change to contract.py and commit the
result; the docs workflow runs it and fails if the committed page is stale.

    uv run scripts/build_yaml_reference.py            # writes docs/reference/dataset-yaml.md
    uv run scripts/build_yaml_reference.py --check    # exit 1 if the page is out of date
"""

import argparse
import inspect
import sys
from pathlib import Path

from pydantic_core import PydanticUndefined

from tilewright import contract

OUT = Path(__file__).resolve().parent.parent / "docs" / "reference" / "dataset-yaml.md"


def _type(annotation):
    text = str(annotation).replace("typing.", "").replace("tilewright.contract.", "")
    text = text.replace("<class '", "").replace("<enum '", "").replace("'>", "")
    return {"str | None": "str", "list[str]": "list of str", "dict[str, str]": "mapping",
            "str | list[str]": "str or list of str", "dict[str, str] | None": "mapping",
            "Literal['datasets', 'attrs']": "`datasets` \\| `attrs`",
            "list[ArtifactSpec]": "list", "list[SharedAxisSpec]": "list",
            "ParamsSpec | None": "mapping or `null`", "ParamsSpec": "mapping",
            "DatasetMetadata": "mapping", "Source": "mapping",
            "FilesSource | None": "mapping", "BatchSource | None": "mapping",
            "GroupsSource | None": "mapping", "TableSource | None": "mapping",
            "Identity": "`params` \\| `provenance`"}.get(text, text)


def _default(field):
    d = field.default
    if d is PydanticUndefined:
        return ""
    if field.default_factory is not None:
        made = field.default_factory()
        return "`{}`" if isinstance(made, dict) else "`[]`" if isinstance(made, list) else "*(defaults)*"
    if d is None:
        return ""
    if hasattr(d, "value"):
        d = d.value
    return f"`{d}`"


def table(model, required_note=True):
    lines = ["| Field | Type | Required | Default | Description |", "|---|---|---|---|---|"]
    for name, field in model.model_fields.items():
        key = field.alias or name
        req = "**yes**" if field.is_required() else "no"
        desc = (field.description or "").replace("\n", " ").replace("|", "\\|").replace("*", "\\*")
        lines.append(f"| `{key}` | {_type(field.annotation)} | {req} | {_default(field)} | {desc} |")
    return "\n".join(lines)


def render():
    tag_models = {"files": contract.FilesSource, "batch": contract.BatchSource,
                  "groups": contract.GroupsSource, "table": contract.TableSource}
    parts = [f"""# The dataset YAML contract

*Generated from `src/tilewright/contract.py` by `scripts/build_yaml_reference.py`; edit
the models, not this page.*

One YAML describes one dataset. To author one, see [How to publish a dataset](../ONBOARDING.md);
to copy a working file, see `examples/datasets/<source>.yml`, one per source tag with its
expected counts in the header.

## Shape

```yaml
label: Broad Sigma               # authored; the key derives from it
key: BROAD_SIGMA                 # written by `tilewright manifest`
metadata: {{...}}                  # facets; method, data_type, material required
source:
  <files | batch | groups | table>:   # exactly one tag
    directory: /abs/path
    ...
artifacts: [{{type, dataset}}, ...]
shared: [{{type, dataset}}, ...]     # optional
```

Unknown keys are rejected everywhere except inside `metadata`, where any key becomes a
queryable facet. An empty string counts as missing. Every problem is reported at once, one
sentence each, as `contract error: <field> <what to do>`.

## Top level

{table(contract.DatasetConfig)}

## `metadata`

Values of the facets marked *vocabulary facet* are soft-checked: a known alias is rewritten
to its id, an unknown value warns and registers as written
([the soft vocabulary](../explanation/vocabulary.md)).

{table(contract.DatasetMetadata)}

## `source`

Exactly one of the four tags. Each owns only the keys below, so an illegal combination
cannot be written ([sources](../explanation/sources.md)). `identity` and `pattern` belong
to the three HDF5 tags; a `table` has neither.

"""]
    for tag, model in tag_models.items():
        parts.append(f"### `source.{tag}`\n\n{model.__doc__.strip()}\n\n{table(model)}\n\n")
    parts.append(f"""### `params`

Where an entity's parameters are read from, within its container (the file for `files`
and `batch`, the entity group for `groups`). Scalars found there become the entity's
queryable metadata; each field's own HDF5 attributes ride along as `<field>_<attr>`
labels, stored beside the value and never part of the identity. `location` adds the
values that only the entity's path holds: a number in a file or directory name, a group
name, a batch row number ([parameters from the location](../explanation/sources.md#parameters-from-the-location)).

{table(contract.ParamsSpec)}

`groups` nests: `{{instrument: /entry/instrument}}` puts `Ei` at `metadata.instrument.Ei`,
queryable as `Key("instrument.Ei") > 50`.

### `identity`

{inspect.cleandoc(contract.Identity.__doc__)}

## `artifacts`

One array child of every entity per entry.

{table(contract.ArtifactSpec)}

## `shared`

Arrays identical for every entity, registered once as array children of the dataset
container and announced on its metadata as `shared_dataset_<type>`.

{table(contract.SharedAxisSpec)}

## Migration from the `data:` / `parameters:` contract

| Before | Now |
|---|---|
| `data.layout: per_entity` | `source.files:` |
| `data.layout: batched` | `source.batch:` |
| `data.layout: grouped` | `source.groups:` |
| `data.directory`, `data.file_pattern`, `data.server_base_dir` | same names inside the tag; `file_pattern` is `pattern` |
| `parameters.location: root_scalars` | `params: {{group: /}}` (the default) |
| `parameters.location: root_attributes` | `params: {{group: /, from: attrs}}` |
| `parameters.location: group` + `group:` | `params: {{group: ...}}` |
| `parameters.location: group_scalars` + `entity_group:` | `groups.entity_group` + `params` relative to each entity group |
| `parameters.groups` / `recursive` / `exclude` | same names inside `params` |
| `provenance:` block | its fields directly under `metadata` |
| `extra_metadata` | `params.groups` |
| `tilewright stamp-key` | `tilewright manifest` writes `key` |

A YAML in the old shape gets one error naming this table.
""")
    return "".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the page is stale")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is out of date: run scripts/build_yaml_reference.py", file=sys.stderr)
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
