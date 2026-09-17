# Float parameters keep at least 12 significant digits; a size-1 dataset is a scalar

**Status:** accepted, 2026-09-17. Amends ADR-0007: it changes how `identity: params`
hashes a float, and which datasets are read as parameters. It also extends the batch rule
written in ADR-0008: a size-1 member is broadcast like a 0-dim one. Decided in
[#15](https://github.com/slaclab/TileWright/pull/15), for
[#4](https://github.com/slaclab/TileWright/issues/4) and
[#5](https://github.com/slaclab/TileWright/issues/5).

## Decision

**A float keeps 12 decimal places or 12 significant digits, whichever is more digits.**
Under `identity: params`, the entity uid hashes each float parameter `v` as:

- `round(v, 12)` when `|v| >= 0.1`. This is the rule from before this change, so these
  values hash as they did;
- `float(f"{v:.12g}")` when `|v| < 0.1`. There, 12 decimal places would keep fewer than
  12 significant digits.

From 0.1 up, 12 decimal places keep 12 or more significant digits, so the rule always
uses the finer of the two. `nan`, `inf` and `-inf` take the first branch, and `0.0` and
`-0.0` take the second. All five hash as they did before, and `-0.0` stays apart from
`0.0`. Ints, strings and bools are hashed as they are.

Digits past the ones kept are not a new entity: `0.1 + 0.2` hashes as `0.3`, and
`300.0 + 1e-13` as `300.0`. Two values are one entity when they round to the same number.

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

**Twelve decimal places lose small values.** `round(v, 12)` turns every value with
`|v| < 5e-13` into `0.0`. The entities of a dataset whose parameters are in SI units
(openPMD timesteps near 1e-13 s) all got one uid, so `tilewright manifest` refused the
dataset. Its error sent the author looking for a duplicate that did not exist. Above that
limit, a value below 0.1 kept fewer significant digits the smaller it was: a value near
1e-9 kept 4. So below 0.1, identity depended on the unit an author chose.

**Only values below 0.1 need a new rule.** From 0.1 up, `round(v, 12)` already keeps 12
or more significant digits, so the rule there stays as it was. As a result:

- no float with `|v| >= 0.1` is hashed differently, whatever its digits. Float32 `2.5666`,
  stored as `2.5666000843048096`, keeps its uid, and so do the short decimals that authors
  type (`300.0`, `2.5666`);
- no two entities that were apart before are merged, except for values that differ by
  less than one step of the finer grid (see Consequences);
- the values that are hashed differently are below 0.1 and have digits past the twelfth
  decimal place: float32 values stored as float64, values written at full precision, and
  every nonzero value below 5e-13.

**The cost: from 0.1 up, noise suppression still depends on the units.** Twelve decimal
places are 12 significant digits at 0.1 and 22 at 1e9. From about 1e4 up they are more
digits than a float64 holds, so there any difference in the stored value is a new entity.
This was so before the change too. It is also what keeps timestamps in epoch seconds
apart (next paragraph).

**The argument that lost: 12 significant digits for every value**
(`float(f"{v:.12g}")`, the first version of this decision). It is simpler: one expression,
no threshold, and the same precision at every scale. It lost because for `|v| >= 10` it
keeps fewer digits than `round(v, 12)`, so it merges values that the old rule kept apart.

- Three files whose only parameter is `start_epoch`, `1726560000.000`, `.001` and `.002`,
  gave three entities before and one uid under this rule. So `manifest` refused a dataset
  that it had accepted before. The review of #15 found this.
- Epoch-second timestamps less than about 0.01 s apart, MJD values and fine steps on a
  large offset are exposed in the same way.
- It also re-keyed every float with `|v| >= 1` and a nonzero digit past its twelfth
  significant digit (and within twelve decimal places), such as float32 `2.5666`.

**The argument that lost: keep `round(v, 12)`.** It re-keys nothing, and its error already
offered a fix (`identity: provenance`). It lost because that rule is the defect. Distinct
values merge below 5e-13, and below 0.1 the precision depends on the units. Telling
authors to rescale their parameters, or to give up content identity, puts the defect on
them.

**The argument that lost: a relative tolerance** (two floats are the same when
`math.isclose` says so). A tolerance compares two values. A hash needs one canonical form
per value, computed for each entity on its own, and a tolerance cannot give one:
"close to" is not transitive (a is close to b and b to c, but a is not close to c). To
turn a tolerance into a canonical form, values must be put into buckets, and that is what
rounding already does. Buckets have edges either way.

**The argument that lost: a different number of digits.** Full precision (no rounding)
would make float noise (`0.1 + 0.2`) a new entity. Fewer digits would merge a sweep with
fine steps. Twelve is the number the old rule used, so from 0.1 up the rule is the old
one and nothing there is re-keyed.

**Shape-`(1,)` scalars were lost.** `_read_params` took a dataset only when it was 0-dim.

- Under `identity: params`, a group holding only such scalars failed with "no parameters
  found". The message named the group, and the group was correct.
- Under `identity: provenance`, the scalars were dropped without a message. The manifest
  had only a `uid` column, the dataset registered, and no query could find its entities.

This was seen on the SINQ DMC NeXus example and on two public Zenodo records (1246857 and
17785191).

**The argument that lost: read size-1 datasets only in `files` and `groups`.** This is the
guard suggested in #4, to keep `batch` as it was. It lost because it drops the parameter
without a message in every batch file with N > 1, which is the silent loss this decision
removes. A corpus that mixes N = 1 and N > 1 files would have the parameter in some
entities and not in others.

## Consequences

**Some registered datasets get new uids.** Only HDF5 sources (`files`, `batch`, `groups`)
under `identity: params`, the default, are affected. There, an entity gets a new uid when:

- **(float rule)** it has a float parameter with `0 < |v| < 0.1` whose value at 12
  significant digits has a nonzero digit after the twelfth decimal place. For example,
  float32 `0.05` is stored as `0.05000000074505806`; it was hashed as `0.050000000745`
  and is now hashed as `0.0500000007451`. This includes every nonzero `|v| < 5e-13`, which
  the old rule hashed as `0.0`. Such a dataset could be registered only when another
  parameter told its entities apart;
- **(size-1 rule)** its params group, or its batch file, holds a size-1 dataset. That
  dataset is now one more parameter. A group that held only such datasets never
  registered under `params`;
- **(`exclude` under `from: attrs`)** its `exclude` names one of its attributes as
  `<group path>/<name>`. That attribute is no longer read or hashed.

No uid changes for:

- `identity: provenance`, `params: null` and `table` sources;
- int, str and bool parameters;
- a float with `|v| >= 0.1`, and `0.0`, `-0.0`, `nan`, `inf` and `-inf`;
- an empty attribute or dataset. Before this change, `manifest` failed on it when it
  wrote the Parquet file, so no such dataset was ever registered;
- the fixtures in `tests/testdata/` (`nips3`, `vdp`): none of their 55 float values is
  hashed differently.

Under `identity: provenance`, the size-1 rule and the `exclude` fix change which
parameters an entity carries, but not its uid. `register` skips an entity that is already
registered, so the new parameters reach the catalog only when the dataset is deleted and
registered again.

**Entities merge only at noise level.** Two values below 0.1 can have had two uids and
now have one. This happens only when they differ by less than one step of the
12-significant-digit grid (1e-13 near 0.05), and the old 12-decimal rounding put them on
two sides of a rounding edge. For example, `0.05000000000049` and `0.05000000000051` were
hashed as `0.05` and `0.050000000001`, and are both `0.0500000000005` now. `manifest`
refuses such a dataset, and its report lists these values as the parameter that differs.
The way out is a parameter that tells the entities apart, or `identity: provenance`, which
re-keys every entity of the dataset. No value with `|v| >= 0.1` merges with another.

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

These are the steps `register` already prints for a file that changed on disk. For a
dataset whose entities merge (above), the first step fails; add the distinguishing
parameter or `identity: provenance` to the YAML first. To see whether a manifest has a
float that the two rules hash differently, run the following on its `entities.parquet`.
It also checks float label columns, which are not hashed, so it can report too much:

```python
import pandas as pd
df = pd.read_parquet("entities.parquet")
print([c for c in df.select_dtypes("float") if any(
    abs(v) < 0.1 and round(v, 12) != float(f"{v:.12g}") for v in df[c].dropna())])
```

**This was acceptable.** TileWright is at v0.2.0. The only registrations known when this
was decided were in throwaway catalogs made for single test runs.

**Tests pin the rules** in `tests/test_manifest.py`:

- `TestIdentity::test_floats_keep_12_decimals_or_12_significant_digits_whichever_is_finer`
  checks both branches: small values stay apart, epoch seconds a millisecond apart stay
  apart, digits past the ones kept merge, and two uids computed at `b268731` for short
  values have not changed;
- `TestIdentity::test_from_one_tenth_up_a_float_hashes_as_before` compares uids with
  `b268731`'s rule for a spread of values with `|v| >= 0.1`, and
  `TestIdentity::test_zero_and_non_finite_floats_hash_as_before` does the same for `0.0`,
  `-0.0`, `nan`, `inf` and `-inf`;
- `TestIdentity::test_si_scale_parameters_stay_distinct` and
  `TestIdentity::test_epoch_seconds_a_millisecond_apart_stay_distinct` run `manifest` on
  the two cases;
- `TestParameterGroups::test_shape_one_scalars_are_parameters` and
  `TestBatch::test_size_one_member_is_broadcast_whatever_the_batch_length`;
- `TestFiles::test_exclude_applies_to_attrs`, `TestFiles::test_empty_attribute_is_null`
  and `TestFiles::test_empty_dataset_is_null_and_empty_labels_are_left_out`.

**The contract text is not yet updated.** #15 does not change `contract.py`. Two
descriptions there still say "0-dim": the one for `params.from`, and the batch rule
written in ADR-0008. The description of `exclude` does not say how to write an
attribute's path. The next change to the contract should correct these descriptions and
regenerate `docs/reference/dataset-yaml.md`.
