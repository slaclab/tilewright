# Entity identity is a choice; dataset identity is a fingerprint

**Status:** accepted, 2026-09-09.

## Decision

**Entity identity.** An entity's uid is a hash of its parameter values by default
(`identity: params`), so the same physics is the same entity across re-registration and
file moves. A source may say `identity: provenance` to hash the file path relative to the
directory plus its row or group instead; that mode is forced when `params: null`. A
`table` source's uid hashes its `id` column, or its columns when `id` is a list. `tilewright manifest` fails on duplicate uids, naming the colliding
entities and the parameters they share, with both fixes in the message.

**Dataset key.** `key = slug(label)`, written into the YAML by `tilewright manifest`. A key
that drifted from its label is an error, never a rewrite. The `stamp-key` command is gone.

**Fingerprint.** `manifest` hashes the facts that identify which data a YAML describes
(tag, server-visible directory, pattern or table path, params spec, identity mode, and a
table's `id` when it is a list), not
the label or metadata, into the Parquet schema; `register` stamps it on the container.
On an existing key: same fingerprint proceeds (and `--update` merge-patches metadata,
revisioned by Tiled); a different fingerprint is refused with both printed; no fingerprint
needs `--adopt`.

## Why

The 2026-08-24 workshop produced experimental datasets where repeated measurements share
every parameter (SEQUOIA runs at one incident energy, LCLS scans at one goniometer
setting). Under content addressing the second run silently collapses into the first and is
reported as "skipped". It also produced datasets with no parameters at all (TOPAZ raw
events) that fell back to a positional index. Neither should be silent. Provenance
addressing never collides but re-identifies every entity when a sweep is regenerated into
new files, which simulation producers do not want. So the default stays content, the
override is one word, and the collision is a decision the onboarding conversation makes.

The workshop also asked attendees to prefix labels with their surname to avoid landing on
each other's keys. A label convention is not a guarantee; the fingerprint is. It is cheap
(one hash, one metadata key), leaves keys readable, and turns "two people picked the same
name" from a silent merge into a refusal with both parties' descriptions shown.

`--update` closes a gap the survey found: with incremental registration, a corrected
description or a new contact never reached the catalog without a delete.

## Consequences

- Attribute labels (`Ei_units`) and dataset metadata are never hashed; correcting them
  never changes identity.
- Copying files to a new directory and re-registering under the old label is refused; the
  fix is a new label.
- Containers registered before this ADR carry no fingerprint and need `--adopt` once.
