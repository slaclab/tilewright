# Float parameters are hashed at 12 significant digits; a size-1 dataset is a scalar

**Status:** accepted, 2026-09-17. Amends ADR-0007: it changes how `identity: params`
hashes a float, and which datasets are read as parameters. It also extends the batch rule
written in ADR-0008: a size-1 member is broadcast like a 0-dim one. Decided in
[#15](https://github.com/slaclab/TileWright/pull/15), for
[#4](https://github.com/slaclab/TileWright/issues/4) and
[#5](https://github.com/slaclab/TileWright/issues/5).

## Decision

**A float is hashed at 12 significant digits.** Under `identity: params`, the entity uid
hashes each float parameter as `float(f"{v:.12g}")`. Before this change it was
`round(v, 12)`, which is 12 decimal places. Ints, strings and bools are hashed as they
are. Noise past the twelfth significant digit is still not a new entity, and a value keeps
12 digits at any scale.

**A size-1 dataset is a scalar.** Under `from: datasets`, a dataset with one element
(shape `(1,)`, as many NeXus writers store scalars) is a parameter, like a 0-dim dataset.
This holds for every source.

- Its value is converted like any other, so an `|S` array gives a `str`, not `bytes`.
- In `batch`, a scalar is broadcast to every row, whatever the batch length N. A 1-D
  dataset of length N > 1 is still one value per row. When N = 1, a length-1 dataset is
  both a scalar and a column, and both readings give the one row the same value.

The same change fixes two defects under `from: attrs` (#5). These follow the contract as
written, so they are not new rules, but the first one changes what is hashed:

- `exclude` now applies to attributes. An attribute's path is `<group path>/<name>`, for
  example `/version` at the root, and an excluded attribute is never read.
- An empty attribute (`h5py.Empty`, a null dataspace) is a null parameter. So is a
  dataset with a null dataspace.

Where each rule is stated for authors: the float rule is in
[identity and keys](../explanation/identity.md). The size-1 rule is in
[the NeXus page](../explanation/nexus.md) and the onboarding skill.

## Why

**Twelve decimal places depend on the units.** `round(v, 12)` turns every value with
`|v| < 5e-13` into `0.0`. The entities of a dataset whose parameters are in SI units
(openPMD timesteps near 1e-13 s) all got one uid, so `tilewright manifest` refused the
dataset. Its error sent the author looking for a duplicate that did not exist. Above that
limit, the precision still depended on the units: a value in eV kept three fewer
significant digits than the same value in meV. Identity must not depend on the unit an
author chose.

**Twelve significant digits changes the fewest hashes.** Any fix changes the hashed form
of some values. With 12 significant digits:

- a value with `0.1 <= |v| < 1` hashes exactly as before, because there both rules keep
  12 digits (`0.1 + 0.2` still hashes as `0.3`);
- the short decimals that authors type (`300.0`, `2.5666`, `1.5e-06`) hash as before;
- the values that change are mostly float32 values stored as float64, or values written
  at full precision.

**Shape-`(1,)` scalars were lost.** `_read_params` took a dataset only when it was 0-dim.

- Under `identity: params`, a group holding only such scalars failed with "no parameters
  found". The message named the group, and the group was correct.
- Under `identity: provenance`, the scalars were dropped without a message. The manifest
  had only a `uid` column, the dataset registered, and no query could find its entities.

This was seen on the SINQ DMC NeXus example and on two public Zenodo records (1246857 and
17785191).

**The argument that lost: keep `round(v, 12)`.** It re-keys nothing, and its error already
offered a fix (`identity: provenance`). It lost because that rule is the defect. Distinct
values merge below 5e-13, and the precision depends on the units. Telling authors to
rescale their parameters, or to give up content identity, puts the defect on them.

**The argument that lost: a relative tolerance** (two floats are the same when
`math.isclose` says so). A tolerance compares two values. A hash needs one canonical form
per value, computed for each entity on its own, and a tolerance cannot give one:
"close to" is not transitive (a is close to b and b to c, but a is not close to c). To
turn a tolerance into a canonical form, values must be put into buckets, and that is what
rounding to significant digits already does. Buckets have edges either way.

**The argument that lost: a different number of digits.** Full precision (no rounding)
would make float noise (`0.1 + 0.2`) a new entity. Fewer digits would merge a sweep with
fine steps. Twelve is the number the old rule used, so it changes the fewest hashes.

**The argument that lost: read size-1 datasets only in `files` and `groups`.** This is the
guard suggested in #4, to keep `batch` as it was. It lost because it drops the parameter
without a message in every batch file with N > 1, which is the silent loss this decision
removes. A corpus that mixes N = 1 and N > 1 files would have the parameter in some
entities and not in others.

## Consequences

**Some registered datasets get new uids.** Only HDF5 sources (`files`, `batch`, `groups`)
under `identity: params`, the default, are affected. There, an entity gets a new uid when:

- **(float rule)** a float parameter is hashed differently by the two rules:
  - `|v| < 0.1` with a nonzero digit after the 12th decimal place, for example float32
    `0.05`, stored as `0.05000000074505806`. This includes every nonzero `|v| < 5e-13`,
    which the old rule hashed as `0.0`. Such a dataset could be registered only when
    another parameter told its entities apart;
  - `|v| >= 1` with a nonzero digit after its 12th significant digit (and within 12
    decimal places), for example float32 `2.5666`, stored as `2.5666000843048096`;
- **(size-1 rule)** its params group, or its batch file, holds a size-1 dataset. That
  dataset is now one more parameter. A group that held only such datasets never
  registered under `params`;
- **(`exclude` under `from: attrs`)** its `exclude` names one of its attributes as
  `<group path>/<name>`. That attribute is no longer read or hashed.

No uid changes for:

- `identity: provenance`, `params: null` and `table` sources;
- int, str and bool parameters;
- an empty attribute or dataset. Before this change, `manifest` failed on it when it
  wrote the Parquet file, so no such dataset was ever registered;
- the fixtures in `tests/testdata/` (`nips3`, `vdp`): none of their 55 float values is
  hashed differently.

Under `identity: provenance`, the size-1 rule and the `exclude` fix change which
parameters an entity carries, but not its uid. `register` skips an entity that is already
registered, so the new parameters reach the catalog only when the dataset is deleted and
registered again.

**`register` does not notice.** The fingerprint hashes the facts in the YAML, not the code,
so an affected dataset keeps its fingerprint. Running `register` again adds each affected
entity a second time, under its new key, next to the old one. The summary counts these as
`Entities:` where `Skipped:` was expected.

**The recovery is a rebuild.** For an affected dataset, run:

```
tilewright manifest <dataset.yml>
tilewright delete <KEY>
tilewright register <dataset.yml>
```

These are the steps `register` already prints for a file that changed on disk. To see
whether a manifest has a float that the two rules hash differently, run the following on
its `entities.parquet`. It also checks float label columns, which are not hashed, so it
can report too much:

```python
import pandas as pd
df = pd.read_parquet("entities.parquet")
print([c for c in df.select_dtypes("float") if any(
    round(v, 12) != float(f"{v:.12g}") for v in df[c].dropna())])
```

**This was acceptable.** TileWright is at v0.2.0. The only registrations known when this
was decided were in throwaway catalogs made for single test runs.

**Tests pin the rules** in `tests/test_manifest.py`:

- `TestIdentity::test_floats_are_hashed_at_12_significant_digits` checks that SI-scale
  values stay apart, that noise past the 12th digit merges, and that two uids computed at
  `b268731` for short values have not changed;
- `TestIdentity::test_si_scale_parameters_stay_distinct`;
- `TestParameterGroups::test_shape_one_scalars_are_parameters` and
  `TestBatch::test_size_one_member_is_broadcast_whatever_the_batch_length`;
- `TestFiles::test_exclude_applies_to_attrs`, `TestFiles::test_empty_attribute_is_null`
  and `TestFiles::test_empty_dataset_is_null_and_empty_labels_are_left_out`.

**The contract text is not yet updated.** #15 does not change `contract.py`. Two
descriptions there still say "0-dim": the one for `params.from`, and the batch rule
written in ADR-0008. The description of `exclude` does not say how to write an
attribute's path. The next change to the contract should correct these descriptions and
regenerate `docs/reference/dataset-yaml.md`.
