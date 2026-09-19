# netCDF and CF

**Read this when** a file name ends in `.nc`, `.cdf` or `.grd`, or any HDF5 file carries
CF attributes — `NAME`, `scale_factor`, `_FillValue`, `grid_mapping` (Step 2). netCDF-4 is
HDF5 underneath and registers like any HDF5 file; these are the places it differs.

## Check the file signature first

A `.nc`, `.cdf` or `.grd` name is often netCDF-3 classic, which no HDF5 source can read.
Check before you plan anything: `head -c 8 <file> | od -c` prints `211 H D F` for HDF5
(netCDF-4 included) and `C D F 001` for netCDF-3. netCDF-3 has to be converted before it
can be registered, or described with a `table` source
([source and entity](source-and-entity.md#what-each-one-looks-like)).

## Placeholders and length-1 coordinates

A netCDF-4 dimension that has no coordinate variable is written as a placeholder dataset:
its `NAME` attribute begins `This is a netCDF dimension`, and its value is `0.0`. It looks
like a scalar parameter, and it is not one: `exclude` it, and leave it out of `shared:`
too, at any length, since a placeholder of 8 or 2 is identical in every file and would
otherwise pass for an axis.

A *real* coordinate variable of length 1 (its own `units`, a `NAME` that is just its
name) is the opposite case: a genuine scalar parameter. If it is identical in every file
it hands every entity the same identity — take what varies from the name with
[`params.location`](params-and-identity.md#parameters-from-the-location).

## Packed variables

A packed variable (`scale_factor` / `add_offset` on an int array) registers as the
**stored integers**: nothing unpacks, both factors ride along as artifact metadata, and a
reader who does not apply them sees counts. Say so in the `description`.

## Grid mappings

A grid-mapping variable (a 0-dim value such as `crs = 0` whose meaning is entirely in its
attributes) is broadcast to every entity as a meaningless parameter under `batch`:
`exclude` it and put the projection in the dataset `metadata`.

## Root attributes

A CF file's root attributes (`@title`, `@source`, `@institution`, `@history`) need copying
into the YAML by hand like any other file's
([nothing fills metadata from the files](metadata-and-vocabulary.md#nothing-fills-metadata-in-from-the-files)).
`@history` often names the post-processing chain; the `producer` rule in `contract.py`
says which code to name.
