# Parameters from the location: a regular expression with named groups

**Status:** accepted, 2026-09-17. Extends ADR-0006 (a new key in `params`, which the
three HDF5 tags share) and ADR-0007 (a new identity input and a new fingerprint fact,
hashed only when set). Decided in the public comment on
[#10](https://github.com/slaclab/TileWright/issues/10#issuecomment-5712407046).

## Decision

**`params.location` is a Python regular expression.** `tilewright manifest` searches it
with `re.search` in each entity's location string:

| Source | Location string | Example |
|---|---|---|
| `files` | the file path relative to `directory`, with `/` separators | `2011/BCI_2011APR.h5` |
| `groups` | `<relative file path>:/<group path>` | `samples.h5:/samples/sample_7` |
| `batch` | `<relative file path>:<row number>` | `sim/batch_0.h5:41` |

The location string is the provenance string that `identity: provenance` already hashes,
so there is one way to name where an entity came from.

**Each named group becomes a flat entity parameter.** Its type comes from the text it
captured:

- `[+-]?\d+` becomes an int, so leading zeros are lost (`0042` is 42);
- a decimal or exponent literal (`0.4`, `.5`, `1e-3`) becomes a float;
- anything else stays a string (`APR`, `x0.4`, `inf`, `1_000`);
- a group that takes no part in the match is null.

Unnamed groups are wildcards only. The expression must compile and must have at least
one named group; a group may not be called `uid` or `source_group`, which are columns of
`entities.parquet` that are not parameters. These are contract errors.

**Location parameters are parameters.** They sit beside the ones read inside the
container, are queryable, take part in `identity: params`, and appear in the collision
report like any other parameter. The report's `Fix:` line under `params` now names
`params.location` as a place a distinguishing value can come from.

**Two data errors, each naming the entity** (the file, `<file>:/<group>`, or
`<file> row <i>`):

- an entity whose location does not match;
- a name that is also read inside the container: a parameter, a `<field>_<attr>` label,
  or the parent of a dotted key (`instrument` for `instrument.Ei`, which registration
  nests). One value would otherwise hide the other.

**The fingerprint hashes `location` only when it is set.** `ParamsSpec.model_dump`
includes defaults, so `source_fingerprint` drops `location` from the params facts while
it is unset. No YAML written without `location` gets a new fingerprint; adding or
changing a `location` gives a new one, because it changes the uids under `params`. Tests
pin the unchanged values and four fingerprints with a `location`.

**The contract now also states** (from #13, F13, and the follow-ups of
[#15](https://github.com/slaclab/TileWright/pull/15), which could not touch
`contract.py`):

- `params.group` may name a dataset under `from: attrs`, whose attributes are then the
  parameters, and an attribute name with a dot is a dotted key, nested on registration;
- `from: datasets` reads scalar datasets, 0-dim or of size 1, and a `batch` source
  broadcasts both;
- under `from: attrs`, an `exclude` path for an attribute is `<group path>/<attribute>`,
  such as `/version`.

## Why

A 32-dataset stress test (#1) found five `files` sources whose distinguishing value lives
only in a name: a year and month in `BCI_<YYYY><MON>.h5` (osti/1414275), a year
(osti/1822259), a mock index (zenodo/10113272), an ensemble member (zenodo/6675429), and
two acquisition dates in a directory name, `In<date1>_<date2>/` (osti/2404535). Every
`params` form reads inside the container, so three of them registered with no queryable
parameter and two with only incidental ones. A `batch` file with nothing per row
(osti/1787546) had no way to give its rows a number to query.

A regular expression covers all six with one key:

| Dataset | `location` |
|---|---|
| osti/1414275 | `'BCI_(?P<year>\d{4})(?P<month>[A-Z]{3})\.h5$'` |
| osti/1822259 | `'_(?P<year>\d{4})\.nc$'` |
| zenodo/10113272 | `'mock_(?P<mock>\d+)\.h5df$'` |
| zenodo/6675429 | `'trans_(?P<member>[^_]+)_'` |
| osti/2404535 | `'In(?P<date1>\d{8})_(?P<date2>\d{8})/'` |
| osti/1787546 (`batch`) | `':(?P<row>\d+)$'` |

Python parses it, so TileWright writes no parser. Typing by the text keeps a year
queryable as a number without a type table in the YAML.

**The arguments that lost.**

- *A `{name:d}` template*, such as `BCI_{year:d}{month}.h5`. It is friendlier and needs
  no escaping. It lost because these names need anonymous wildcards (the parts of
  `CLIO2_0ka_trans_<member>_013000to015000_sst.nc4` that are not values), a template
  would need a parser written and documented here, and its type markers are a second
  typing rule.
- *A `table` sidecar joined on the path*, listing each file's values. It needs no new
  syntax, and a table can hold values no name has. It lost because it is a second file
  to keep in step with the data, and a table source cannot carry arrays, so the join
  would be a new mechanism anyway.

## Consequences

- An author writes the expression in single quotes: YAML keeps every backslash there.
  In double quotes `"\d"` is a YAML error and `"\b"` silently becomes a backspace. The
  field description and the explanation page say so; the example `files.yml` shows it.
- Typing by text is per entity. A group that captures `12` in one name and `AC` in
  another gives an int and a string, and writing the manifest fails in pyarrow naming
  the column. `errors.md` says to capture the same kind of text everywhere.
- A captured integer beyond the int64 range (above 9223372036854775807: some 19-digit
  numbers, and every longer one) is still an int, and pyarrow cannot write it to the
  manifest. No such name was seen; the rule was kept simple rather than typed by size.
- Under `params`, renaming a file changes a location parameter and so the entity's key,
  as `provenance` does. Moving the whole directory changes nothing.
- A group path or a batch row number alone can repeat from file to file: every batch
  file's rows start again at 0. With several files and nothing else that differs, the
  expression has to capture part of the file path too, or the rows collide; the field
  description says so and shows `'part_(?P<part>\d+)\.h5:(?P<shot>\d+)$'`.
- A named group called like a locator of a declared artifact type (`path_<type>`,
  `dataset_<type>`, `index_<type>`) is refused by the same data check as any other
  parameter with such a name; its `Fix:` line says to rename the group in
  `params.location`, since neither `exclude` nor renaming something in the file helps.
- The examples on the pages authors read (the field description, the explanation page,
  the onboarding skill) are invented. The dataset expressions in the table above stay
  here: the pages that onboard a dataset must not hand its answer to the person
  onboarding it.
- `tests/test_contract.py::test_concept_budget` lists `location` among the keys of
  `params`.
- The reference page, the onboarding skill's Step 2, `ONBOARDING.md`,
  `explanation/sources.md` (the home of the rule), `explanation/identity.md` and
  `errors.md` describe the key.
