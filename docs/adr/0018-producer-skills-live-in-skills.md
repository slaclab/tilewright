# Producer skills live in `skills/`, and run from the data root

**Status:** accepted, 2026-09-18. Settles
[#46](https://github.com/slaclab/TileWright/issues/46). Changes no field of the contract;
moves where the onboarding skill lives and where it runs.

## Decision

**`skills/` is the one home of the Claude Code skills a producer uses, and
`.claude/skills/` holds the maintainers'.** `skills/onboarding/` is installed once, by
symlink into `~/.claude/skills/`, and run in a session opened in the data root: the
directory the dataset YAML and its manifests live under. `.claude/skills/onboarding` is a
symlink to `skills/onboarding`, so a session opened in a clone still offers `/onboarding`.

**The skill finds the contract surface from its own real path.** Its checkout is two
directories above `readlink -f` of the skill's base directory, which holds for a symlinked
install and for a clone alike. Every `docs/`, `src/` and `examples/` path the skill names
is under that checkout, not under the working directory. `tilewright` comes from `PATH`,
or else from `uv run --project <checkout>`.

`knowledge-capture`, a personal notes skill, leaves the repository. `CLAUDE.md` opens by
saying it is for working on TileWright, and points producers at the skill.

## Why

`.claude/skills/` and `CLAUDE.md` load in every session opened in a checkout. So the old
layout told a producer to onboard *in the repository*. The YAML and the `manifest` and
`register` commands belong in the data root, so the session's working directory and the
data it worked on were in different places. The same session also loaded contributor
rules meant for someone changing TileWright.

A docs URL would have let the skill run with no checkout at all. It was not chosen because
the repository is internal and the docs site is not published, so neither the site nor a
raw GitHub URL resolves for an agent. Resolving the checkout from the skill's path keeps
every fact in its one home and needs nothing the producer does not already have.

## Consequences

- An install without a checkout still has no skill; `docs/install.md` says so.
- Moving or deleting the checkout breaks an installed skill; `skills/README.md` says so.
- A new producer skill goes in `skills/`, and a new maintainer skill in `.claude/skills/`.
