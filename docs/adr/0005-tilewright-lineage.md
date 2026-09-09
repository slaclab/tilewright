# TileWright is the successor of two repositories

**Status:** accepted, 2026-09-09.

`slaclab/TileWright` continues the git history of
[`carbonscott/tiled-catalog-broker`](https://github.com/carbonscott/tiled-catalog-broker)
(CLI `tcb`; last commit carried over: `068670e`, 2026-08-25). Every commit before this ADR
is that project's history, so `git log --follow` and `git blame` still reach the original
authors of every line.

The design of the successor also draws on
[`carbonscott/tilewright`](https://github.com/carbonscott/tilewright) at `203acbe`
(2026-08-21), a deliberately minimal rebuild whose history is **not** merged here. What was
taken from it, by decision rather than by copy:

- the tagged-union dataset contract (`source: files | batch | groups | table`), which makes
  illegal layout-and-parameter combinations unrepresentable instead of validated away;
- domain-language contract errors, every error collected before exit;
- the `.tilewright/` layout: a dataset's YAML and manifests live in its data root;
- the provenance-hash entity identity, as an explicit override;
- a concept-budget test that pins the contract's top-level keys and source tags.

What was kept from `tiled-catalog-broker` against the minimal rebuild's cuts, because the
2026-08-24 workshop used it: the `--upload` transport, shared axes as array children,
nested parameter groups with attribute capture, the soft vocabulary, `delete`, the docs
site, and the conversational onboarding skill.

Removed in the transition: the `.env` loader (`--url`/`--api-key` or the environment),
the PyTorch cache client, the `stamp-key` command (the key is now derived by `manifest`),
and the AmSC connector, which moved to
[`slaclab/amsc-catalog-publisher`](https://github.com/slaclab/amsc-catalog-publisher)
with its own history.
