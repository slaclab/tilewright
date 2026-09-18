# The onboarding skill is self-contained and ships in the package

**Status:** accepted, 2026-09-18. Settles
[#46](https://github.com/slaclab/TileWright/issues/46); the first half of
[#48](https://github.com/slaclab/TileWright/issues/48). Changes no field of the contract;
moves where onboarding is documented, and how the skill reaches a user.

## Decision

**`skills/onboarding/` holds everything onboarding needs, and it ships in the wheel.**
The walkthrough, the source, identity, vocabulary and NeXus guides, the manifest and
dataset YAML references, the `tilewright manifest` errors and the example YAMLs moved there
from `docs/` and `examples/datasets/`, text unchanged apart from links. The generated
YAML reference is written there by `scripts/build_yaml_reference.py`. Hatch force-includes
`skills/` as `tilewright/skills`, and `tilewright skills install` symlinks each skill into
`~/.claude/skills/`. `.claude/skills/onboarding` is a symlink to it, so a clone still
offers `/onboarding`.

**Pages are split by reader.** `docs/` keeps what operators and catalog readers need:
installing, hosting a server, reading the catalog, the data model, the command line, and
the errors of `register`, `delete` and reads. `docs/ONBOARDING.md` is a pointer page that
keeps the anchors older links use. Pages link across the two by GitHub URL.

**The skill finds the package from its own real path.** Installed, it sits at
`<pkg>/skills/onboarding`, so `<pkg>` holds `contract.py` and `vocabulary.yml`; in a
checkout the same two levels up is the repository root, and `<pkg>` is `src/tilewright`.
It does not import `tilewright`, which a `uv tool install` keeps out of the user's Python.

`.claude/skills/` holds maintainer skills only. `CLAUDE.md` opens by saying it is for
working on TileWright.

## Why

`.claude/skills/` and `CLAUDE.md` load in every session opened in a checkout, so the old
layout told a producer to onboard *in the repository*, while the YAML and the `manifest`
and `register` commands belong in the data root.

Most people will onboard through an agent, and a person who wants to do it by hand can read
the same pages. So the pages an agent reads are the skill's, and one home serves both.

Shipping in the package, not as a Claude Code plugin, keeps the skill and the CLI at one
version. A plugin updates on its own schedule, and a skill describing a flag the installed
`tilewright` lacks, or missing one it has, is the failure the blind onboarding runs were
built to catch: every run recorded the SHA whose surface the worker read beside the one it
ran.

An earlier draft of this ADR had the skill read the docs from a checkout it located by
path. It was dropped before merging: it needed a checkout, and the docs site that could
have replaced one is not published.

## Consequences

- The site no longer renders the onboarding pages; GitHub does. A diagram is a plain image
  link, since `--8<--` snippets render only under mkdocs.
- mkdocs no longer checks links inside the skill, so `tests/test_skills.py` does.
- The move and the rewrite are separate pull requests, each followed by a blind onboarding
  run, so a regression traces to one of them. The rewrite (#48, ADR-0019) splits
  `reference/` by the decision the agent faces and turns Step 2 into a routing checklist.
- A new producer skill goes in `skills/`; a new maintainer skill in `.claude/skills/`.
