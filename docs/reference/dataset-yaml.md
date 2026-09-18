# The dataset YAML contract

*Generated from `src/tilewright/contract.py` by `scripts/build_yaml_reference.py`; edit
the models, not this page.*

One YAML describes one dataset. To author one, see [How to publish a dataset](../ONBOARDING.md);
to copy a working file, see `examples/datasets/<source>.yml`, one per source tag with its
expected counts in the header.

## Shape

```yaml
label: Broad Sigma               # authored; the key derives from it
key: BROAD_SIGMA                 # written by `tilewright manifest`
metadata: {...}                  # facets; method, data_type, material required
source:
  <files | batch | groups | table>:   # exactly one tag
    directory: /abs/path
    ...
artifacts: [{type, dataset}, ...]
shared: [{type, dataset}, ...]     # optional
```

Unknown keys are rejected everywhere except inside `metadata`, where any key becomes a
queryable facet. An empty string counts as missing. Every problem is reported at once, one
sentence each, as `contract error: <field> <what to do>`.

## Top level

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `label` | str | **yes** |  | Human-readable dataset name. The catalog key is derived from it: slug(label) keeps A-Z and 0-9 only, so every other character, a non-ASCII letter included, becomes '_' ('Vanterëk Powder' -> VANTER_K_POWDER), and a label with no ASCII letter or digit at all is an error. Write the label as the name should read; the key is allowed to be the plainer spelling. |
| `key` | str | no |  | Catalog key, slug(label); written by 'tilewright manifest'. If present it must equal slug(label). |
| `metadata` | mapping | **yes** |  | Dataset-level facets; method, data_type and material are required. |
| `source` | mapping | **yes** |  | Where the entities come from: one tag. |
| `artifacts` | list | no |  | Arrays each entity exposes; at least one entry, except for 'table'. An entry names one array ('dataset') or every array in a group ('group'). The list says what the dataset serves, not what the files hold: an array no reader would ask for, a constant placeholder whose meaning is in its own attributes say, is left out, and nothing checks the files for arrays nobody named. |
| `shared` | list | no |  | Arrays shared by every entity, registered once under the dataset, each an array child of the dataset container under its 'type'. 'Axis' names the common case, not the rule: an array that belongs to the dataset rather than to an entity goes here whether or not it is a coordinate -- a normalization or lookup table, a detector mask, a response curve. Nothing of an axis is required of it, not a rank, a dtype or an order; the whole test is the one under 'dataset', that every file holding that path agrees. An array that differs between entities is an artifact, not a shared entry. |

## `metadata`

Values of the facets marked *vocabulary facet* are soft-checked: a known alias is rewritten
to its id, an unknown value warns and registers as written
([the soft vocabulary](../explanation/vocabulary.md)).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `method` | list of str | **yes** |  | Scientific methods, e.g. ['RIXS']; at least one. A method is how the values were obtained, so a field of study ('geophysics'), a file format and the name of a code are not methods -- the code is 'producer'. Data produced by no method at all (a reference table compiled from the literature, a solver benchmark, model weights) takes ['not_applicable'], the escape hatch 'material' has, and there is no other way to say it: the field is required and may not be empty. The vocabulary lists no 'not_applicable' among the methods, so it registers as written with a note; that note is the record that this dataset had no method, not a mistake to correct. Vocabulary facet. |
| `data_type` | str | **yes** |  | What kind of data, as one of the data_type ids in the vocabulary: 'simulation', 'experimental', 'benchmark' or 'optimization'. A measurement of the world is experimental wherever the instrument stood, a laboratory, a field site or an orbit; what a model or a code computed is simulation. A benchmark is a set whose purpose is to grade something else -- the accuracy of a solver, the score of a model, the throughput of a pipeline -- so its arrays are the yardstick and not the subject. An optimization is the record of a search for a best value (a fit, a sweep that an objective steered, a training run), and its entities are the attempts. Enumeration is neither: a space computed or measured case by case, with nothing scoring it and nothing steering it, is simulation when a code computed it and experimental when an instrument measured it, however exhaustive the enumeration and whoever later grades a model against it. Vocabulary facet. |
| `material` | str | **yes** |  | Material or system studied, e.g. 'NiPS3'. A physical system that is not a substance is named as the system it is ('upper atmosphere', 'seafloor sediment'); 'not_applicable' is for data with no physical subject at all, such as a benchmark of a solver. Vocabulary facet. |
| `producer` | str | no |  | Code that produced or reduced the data ('sunny_jl', 'mantid'). When a chain of codes made the files, it names the last one that shaped the arrays being registered; name the earlier steps in 'description'. Vocabulary facet. |
| `project` | str | no |  | Project or collaboration ('MAIQMag'). Vocabulary facet. |
| `proposal` | str | no |  | Beamtime proposal id ('IPTS-37598'). Vocabulary facet. |
| `facility` | str | no |  | Where experimental data was collected ('SNS'). Vocabulary facet. |
| `instrument` | str | no |  | Instrument or beamline ('SEQUOIA', 'JEOL NeoARM'). Free text. |
| `contact` | str | no |  | Who to ask about this dataset, as `Name <email>`. Nothing parses it, so a record that publishes no address still fills it: write the name and where it can be reached from ('Lattice Dynamics Group, Vasari Institute (via doi:10.5555/000000)'), or the name alone. A name with no address beats a guessed address, and both beat leaving the field out while someone can be named. |
| `description` | str | no |  | One paragraph a reader uses to decide whether to open the dataset. Repeat the defining numbers here freely, but every number in it must also exist as a key of this 'metadata' block: the key is authoritative, the prose is the summary. The test for both halves is one question -- would anyone write a Key('...') == query on that number to find datasets? A count, a size, a rate, a temperature: yes, so it needs a key. A year in a name, a version string, a DOI, a dtype ('uint8'), a formula ('NiPS3'), and a value quoted to explain what it means ('0 is a valid reading, not a gap'): no, they are prose and need none. An entity parameter is not a key of this block, so a number that describes the entities as a set ('tilt runs from 0 to 30 degrees') takes dataset keys of its own here, or it goes. Nothing checks any of this, so a prose number that no key carries, or a key whose value the prose contradicts, is found by a reader. |

## `source`

Exactly one of the four tags. Each owns only the keys below, so an illegal combination
cannot be written ([sources](../explanation/sources.md)). `identity` and `pattern` belong
to the three HDF5 tags; a `table` has neither.

### `source.files`

One HDF5 file per entity.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | `params` \| `provenance` | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the HDF5 files under 'directory', matched with Python's Path.glob relative to 'directory': '\*', '?' and '[...]' match within one path segment, and a '\*\*' segment matches any number of directories, so '\*\*/\*.h5' recurses. Names starting with '.' match like any other. There are no braces: '\*.{h5,hdf5}' matches nothing; use a wider glob such as '\*.h\*5'. A pattern that matches nothing is retried with Path.rglob, which puts '\*\*/' in front of it, so it then matches at any depth. Only files are kept, in sorted order. |
| `params` | mapping or `null` | no |  | Where the parameters live: inside each file, and with 'location' in its path. Default: the scalar datasets at the root. 'null' declares that entities have no parameters (identity becomes provenance). |

### `source.batch`

Many entities stacked along axis 0 of each file's datasets; entity i is row i.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | `params` \| `provenance` | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the HDF5 files under 'directory', matched with Python's Path.glob relative to 'directory': '\*', '?' and '[...]' match within one path segment, and a '\*\*' segment matches any number of directories, so '\*\*/\*.h5' recurses. Names starting with '.' match like any other. There are no braces: '\*.{h5,hdf5}' matches nothing; use a wider glob such as '\*.h\*5'. A pattern that matches nothing is retried with Path.rglob, which puts '\*\*/' in front of it, so it then matches at any depth. Only files are kept, in sorted order. |
| `params` | mapping or `null` | no |  | Where the parameters live: inside each file, and with 'location' in its path and row number. Default: the root. N is the file's leading axis (that of the first artifact). Only 1-D datasets of length N are per-entity values, one per row; scalar datasets (0-dim or of size 1) are broadcast to every entity in the file; any other member, (N, 1) with N > 1 included, is skipped without a message. 'null' declares that entities have no parameters (identity becomes provenance). |

### `source.groups`

One HDF5 group per entity inside each file.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | `params` \| `provenance` | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the HDF5 files under 'directory', matched with Python's Path.glob relative to 'directory': '\*', '?' and '[...]' match within one path segment, and a '\*\*' segment matches any number of directories, so '\*\*/\*.h5' recurses. Names starting with '.' match like any other. There are no braces: '\*.{h5,hdf5}' matches nothing; use a wider glob such as '\*.h\*5'. A pattern that matches nothing is retried with Path.rglob, which puts '\*\*/' in front of it, so it then matches at any depth. Only files are kept, in sorted order. |
| `entity_group` | str | no |  | Group whose subgroups are the entities ('/samples'). Default: the file root, so that each of the file's own top-level groups is an entity. (The default is the group named here, not the entities: writing '/\*', which names every top-level group, would instead make an entity of every subgroup of one.) Any segment may be a glob, matched with fnmatch against the names of the groups at that level: '\*' and '?' match within the name, '[...]' one character of a set, and case matters. '/\*' takes every top-level group, so that each subgroup of each of them is an entity (`/<site>/<detector>`); '/run_\*/scans' takes the 'scans' group of every run_ group. The matching groups are taken in sorted order, and the entities are the subgroups of every one of them. A file in which no group matches is an error, and so is one in which the matching groups have no subgroup left (see 'exclude_groups'). |
| `exclude_groups` | list of str | no |  | Subgroups that are not entities: fnmatch patterns matched against the name of each subgroup of the entity group(s), not against its path. [calibration] leaves out a group that holds values for the entities beside it; ['tmp\*'] every group whose name starts with 'tmp'. Excluded groups are not counted as siblings (see 'params'). |
| `params` | mapping or `null` | no |  | Where the parameters live: relative to each entity group, and with 'location' in its file and group path. Default: the entity group's own scalar datasets. A group path may start with '..' segments to leave the entity group, resolved against its path: '..' is the group that holds the entity group and its siblings, '../calibration' a group beside them, '../..' one level higher. A path that climbs above the file root is an error. In a group reached through '..', a 1-D dataset whose length equals the number of sibling entity groups (the subgroups of the same group, after 'exclude_groups') gives one value per entity: element i goes to the i-th sibling with the names sorted as text. Text is not numeric order: scan_10 sorts before scan_2, so scan_1 ... scan_12 do not pair with elements 0 ... 11 in order, while scan_01 ... scan_12 do. Scalar datasets (0-dim or of size 1) there are given to every sibling, and any other member, a 1-D dataset of another length included, is skipped without a message, as in 'batch'. Under 'from: attrs' the attributes of such a group are given to every sibling. 'recursive: true' is for paths inside the entity group only: recursion inside the entity group and a path that starts with '..' cannot be combined in one params block (a contract error), because from outside the entity group the reader would reach the groups of other entities, whose arrays follow their own names. Name each group you need instead, without 'recursive': `{groups: {site: .., calibration: ../calibration, own: /}}`. The group a path names is read whatever it is, an entity group included: under a path to one detector (`../<detector>`), its scalars go to every sibling, and each of its 1-D datasets whose length is the number of siblings is split among them. Recursion inside the entity group stays inside it (see 'recursive'), so a member whose own name resolves to a sibling entity group, or to a group 'entity_group' matched, is named in a warning and skipped, whatever the text of its target path spells. A second HDF5 name (a hard link) for a group \*inside\* one of them names a member of this entity group like any other, and is read; so is anything reached \*through\* such a name, since a name is skipped but the path through it is not. A soft link whose target path runs through a hard link to a sibling entity group is followed, and that entity's values enter these parameters and this uid. Write the link out of the group if what it names should not be read. 'null' declares none. |

### `source.table`

A sidecar table whose rows are the entities: for data Tiled cannot read.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `path` | str | **yes** |  | Parquet or CSV file, relative to 'directory'. Every column becomes entity metadata, and there is no way to leave one out: a column whose header cell is empty is read under the name pandas gives it ('Unnamed: 4') and is null in every row. To drop a column, change the table. |
| `id` | str or list of str | **yes** |  | The entity's identity: one column, or a list of columns when no single column is unique ('id: [specimen, replicate]'); together their values must be unique across rows. A null cell is allowed and hashed as null, so rows are still told apart by the cells that are filled in; what no equality search can then find is that row, because a null is not a value to compare with. Changing it re-keys every entity: delete the registered dataset, then register again. A list is part of the fingerprint, so 'register' refuses a change to, from or between lists until you do. |
| `locator` | mapping | no |  | Extra metadata rendered per row from '{column}' templates, e.g. {globus_url: 'https://.../{filename}'}. |

### `params`

Where an entity's parameters are read from, within its container (the file for `files`
and `batch`, the entity group for `groups`, which a path can leave with `..`; see
`source.groups`). Scalars found there become the entity's
queryable metadata; each field's own HDF5 attributes ride along as `<field>_<attr>`
labels, stored beside the value and never part of the identity. `location` adds the
values that only the entity's path holds: a number in a file or directory name, a group
name, a batch row number ([parameters from the location](../explanation/sources.md#parameters-from-the-location)).
Entities that read different parameters get null for the ones they lack
([the data model](../explanation/data-model.md#entities-with-different-parameters)).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `group` | str | no |  | One HDF5 group whose fields become flat metadata keys. '/' is the container itself: the file for 'files' and 'batch', and for 'groups' the entity group, not the file root, since every 'groups' path is relative to the entity group ('params' and '/params' name the same group). Under 'groups' only, a path may start with '..' segments to leave the entity group: see 'params' under 'source.groups'. Default '/' when neither 'group' nor 'groups' is given. With 'from: attrs' it may also name a dataset: that dataset's attributes are then the parameters. An attribute name with a dot in it ('run.number') is a dotted key, nested on registration like the keys 'groups' makes (metadata.run.number). A field of this group named 'uid' or 'source_group' is refused, naming the file and the field: those two are the columns 'tilewright manifest' writes itself -- the identity it computed, and the HDF5 group a 'groups' entity was read from -- so a parameter of that name would take the column instead of sitting beside it. Leave it out with 'exclude', or read its group under a name of your own with 'groups', which nests it ('meta.uid'); nesting renames that group's other parameters too, and every parameter name is part of the identity, so the uids change with it. |
| `groups` | mapping | no |  | Several groups, keyed by the name each nests under: {instrument: /entry/instrument, sample: /entry/sample} -> metadata.instrument.Ei, metadata.sample.mass; queryable as Key('instrument.Ei'). Each path is read as in 'group', '..' included. A name here may not be 'uid' or 'source_group': every key of that group nests under it, and registration nests the metadata the same way, so those keys would land inside a column the manifest writes itself. |
| `from` | `datasets` \| `attrs` | no | `datasets` | 'datasets': scalar datasets in the group are parameters, 0-dim or of size 1 (NeXus writes scalars with shape (1,)); in 'batch', a 1-D dataset of length N is one value per entity, and so it is under 'groups' in a group reached through '..', with N the number of sibling entity groups. Under 'files' and 'groups' every other dataset, a (7,) array or a (3, 4) matrix say, is skipped without a message, attributes and all. Every container is read on its own, each file and under 'groups' each entity group, so two more cases pass without a message: a dataset of size 1 in some of them and a bigger one in others is a parameter only where one of the rules above makes it one, and a group that some files or entity groups lack (one of 'groups', say) gives their entities none of its parameters. Those entities hold null in the columns they miss. 'attrs': the group's HDF5 attributes are the parameters, and a group that a file or an entity group lacks is an error naming it. Every attribute of that group is read whatever its value holds: an array-valued attribute becomes a list parameter, an empty one (a null dataspace) becomes null. One block reads one way, for every path in it, and a source takes one 'params' block: a container that keeps some values in scalar datasets and others in attributes gives up one of the two, so copy what is left over into 'metadata' by hand, or ask the producer to move it. |
| `recursive` | bool | no | `False` | Descend into subgroups, nesting one level per subgroup. The rule stops at the group the path names: that group's own members are read as they are without 'recursive', so an HDF5 link written there is followed wherever it leads, and the descent below it follows only what lies inside that group -- a subgroup or a dataset an HDF5 link leads out of it (a soft link elsewhere in the file, an external link, which resolves in another file, a chain of links ending outside, or a link whose target path is spelled inside the group but runs through a link that is not) is named in a warning and skipped. So a member of the group itself is the author's own choice, link and all: write the link out of the group if what it names should not be read. Below that group nothing from another file is read through a link, whatever its target path spells: the object a name resolves to decides, not the text. Under 'groups', where the other entities are sibling groups of the same file, what is decided that way is a member's own name: a name resolving to a sibling entity group is skipped, and a target path that runs through such a name is followed (see 'params' under 'source.groups'). A group named under 'group' or 'groups' is likewise read wherever its path leads. It applies to every path of the block, so under 'groups' a block with 'recursive: true' may hold no path that starts with '..' (see 'params' under 'source.groups'). The key is the path: a field kept as a group of its own ('/beam_current' holding 'data' and 'description') gives 'beam_current.data' and 'beam_current.description', and nothing renames a key: the parameter a reader queries is the one the file spells. |
| `exclude` | list of str | no |  | HDF5 paths (same frame as the group paths) to skip: a JSON blob, say. Under 'from: attrs', an attribute's path is `<group path>/<attribute>`: `/operator_note` skips the root's attribute 'operator_note'. It skips paths, not values: under 'recursive', an HDF5 link elsewhere in the group whose target is an excluded path is inside the group like any other member, so what it names is read again under the link's own key. Name the link in 'exclude' as well. |
| `location` | str | no |  | A Python regular expression, searched (re.search) in each entity's location. For 'files', the location is the file path relative to 'directory', with '/' separators, so a directory name can be matched too (`cell07/sweep_250mV.h5`); for 'groups', `<file path>:/<group path>` (`samples.h5:/samples/sample_7`); for 'batch', `<file path>:<row number>` (`shots/part_03.h5:41`). Each named group, `(?P<name>...)`, becomes a flat parameter beside those read in the container, and is part of the identity like them. Its type comes from the text it captures: an integer, `[+-]?\d+`, becomes an int, so leading zeros are lost (`07` -> 7); a decimal or exponent literal (`0.4`, `1e-3`) becomes a float; anything else stays a string; a group that takes no part in the match is null. Unnamed groups, `(...)`, are wildcards only; at least one named group is required. Write it in single quotes, so that YAML keeps the backslashes: `location: 'cell(?P<cell>\d+)/sweep_(?P<bias_mV>[+-]?\d+)mV\.h5$'` gives cell 7 and bias_mV 250. A batch row number is a legitimate parameter when nothing else varies between rows: `location: ':(?P<shot>\d+)$'`. When 'pattern' matches several files, a group path or a row number alone can repeat from file to file (every batch file's rows start again at 0), so capture part of the file path as well: `location: 'part_(?P<part>\d+)\.h5:(?P<shot>\d+)$'`. An entity whose location does not match is an error, and so is a name that is also read in the container. A params block that holds nothing but 'location' is complete: for files that keep no scalar and no attribute anywhere, the named groups are the entity's whole identity, and the empty default group is no error. |

`groups` nests: `{instrument: /entry/instrument}` puts `Ei` at `metadata.instrument.Ei`,
queryable as `Key("instrument.Ei") > 50`.

### `identity`

How an entity's uid is computed (``source.<tag>.identity``, for ``files``,
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

## `artifacts`

One array child of every entity per entry.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | str | **yes** |  | Name of the array; becomes its key under the entity, and names its locators (`path_<type>`, `dataset_<type>`, `index_<type>`). With 'group', a template in which '{name}' stands for each member's name. Quote the template, as in `type: 'trace_{name}'`: YAML reads an unquoted brace as the start of a mapping. A literal brace in it is written '{{' or '}}'. Any character may appear except '/', '?', '#', an ASCII control character (tab, newline) and a '%' followed by two hex digits ('%20'), and the type may not be '.' or '..': it travels in a URL, so the server would not serve such an array back. Dots, spaces, brackets, '-', '\|', a leading '_' or '.', and non-ASCII letters all work, and a dot does not nest the locators. A type is taken exactly as written, so 'gain_a' and 'Gain_A' are two different arrays of one entity, and only an exact repeat is a duplicate. With --upload, a server that keeps arrays as files names a directory after the type, URL-escaped as Python's urllib.parse.quote_plus does it, so that must also fit in one file name, 255 bytes on most filesystems. |
| `dataset` | str | no |  | HDF5 path of the array: absolute for 'files' and 'batch', relative to each entity group for 'groups'. Give either 'dataset' or 'group'. |
| `group` | str | no |  | HDF5 path of a group, instead of 'dataset': the entry becomes one artifact per dataset directly in the group, in sorted name order. Scalar (0-dim) datasets are included; subgroups, and datasets with no dataspace (h5py.Empty), are skipped. Absolute for 'files', relative to each entity group for 'groups'; a 'batch' source does not take it, because its first artifact sets the batch size. 'type' must hold '{name}', and nothing else in braces: `{type: 'trace_{name}', group: /channels}` gives trace_ch_a ... trace_ch_d for /channels/ch_a ... /channels/ch_d, and `{type: '{name}', group: /frames}` gives frame_0000 ... frame_0099 for /frames/frame_0000 ... /frames/frame_0099. The types must stay unique within an entity after this expansion, shared types included, and a member whose name makes a type that breaks the 'type' rule is an error that names it. A string dataset is a member too, and registration refuses a variable-length one (an artifact error): leave it out with 'members'. A group that is absent, or that holds no dataset matching 'members', is an error unless 'optional'. Each member becomes an array node of its own, so thousands of per-step datasets register slowly and read back one step at a time: stack them into one array, or into a 'batch' file, before onboarding. |
| `members` | str | no | `*` | With 'group' only: an fnmatch pattern that a member's name must match, case-sensitive. '\*' takes every dataset in the group; 'frame_00[0-4]?' takes frame_0000 ... frame_0049. |
| `optional` | bool | no | `False` | True if some entities lack this array (with 'group': the group, or every member that matches); it is skipped for them. Otherwise a missing array is an error. |

## `shared`

Arrays identical for every entity, registered once as array children of the dataset
container and announced on its metadata as `shared_dataset_<type>`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | str | **yes** |  | Name of the array; becomes its key under the dataset container. The characters allowed are those of an artifact 'type'. |
| `dataset` | str | **yes** |  | Absolute HDF5 path of an array identical for all entities. The entry names one copy; `tilewright manifest` records that one and checks every copy the source holds against it -- by shape and value, so two copies that differ only in dtype agree and the row keeps the named copy's -- refusing the dataset when two differ. NaN counts as equal to NaN in the same place, and the copy the run meets first decides that -- under 'groups' not always the recorded one: the values are compared as floating-point ones only when that first copy is itself floating-point, so an integer copy compared with a floating-point one holding NaN differs and is refused, as it should be -- no integer array holds NaN, so the two are not the same axis. Under 'files', 'batch' and 'table' the copies are that path in each file. Under 'groups' a path inside an entity group (`/scan/point_01/energy`) is one copy per entity group, in every file, so one file holding four entity groups holds four copies and all four are compared; a path beside the entity groups -- or inside a group 'exclude_groups' leaves out, which is then no entity group -- is one copy per file, as under the other tags. Finding the copies costs one extra open of every matched file, and two under 'groups', where the entity groups of every file are read before the first copy is compared; a source that declares no shared array pays neither. A place that does not hold the path at all is passed over silently, a file or one entity group of one alike, so one entry cannot reach values kept under a path that carries the entity's own name ('/<sample>/energy_grid'), however identical: those belong in the dataset 'metadata', and an entity whose group lacks the copy is served the recorded one. Nothing else is claimed about the values: an axis that repeats or runs backwards is a valid shared axis as long as every copy agrees. A shared entry names one array: the 'group' form of 'artifacts' is not available here. |

## Migration from the `data:` / `parameters:` contract

| Before | Now |
|---|---|
| `data.layout: per_entity` | `source.files:` |
| `data.layout: batched` | `source.batch:` |
| `data.layout: grouped` | `source.groups:` |
| `data.directory`, `data.file_pattern`, `data.server_base_dir` | same names inside the tag; `file_pattern` is `pattern` |
| `parameters.location: root_scalars` | `params: {group: /}` (the default) |
| `parameters.location: root_attributes` | `params: {group: /, from: attrs}` |
| `parameters.location: group` + `group:` | `params: {group: ...}` |
| `parameters.location: group_scalars` + `entity_group:` | `groups.entity_group` + `params` relative to each entity group |
| `parameters.groups` / `recursive` / `exclude` | same names inside `params` |
| `provenance:` block | its fields directly under `metadata` |
| `extra_metadata` | `params.groups` |
| `tilewright stamp-key` | `tilewright manifest` writes `key` |

A YAML in the old shape gets one error naming this table.
