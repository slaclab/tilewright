# Skills for dataset producers

Claude Code skills for people publishing data with TileWright. They ship inside the
`tilewright` package, so a skill always describes the `tilewright` you have installed.
Maintainer skills live in `.claude/skills/` and load only in a session opened in this
repository.

| Skill | What it does |
|---|---|
| `onboarding` | Drafts the dataset YAML from your HDF5 files, asks what the files cannot say, then runs `tilewright manifest` and `tilewright register` and reads the result back |

Each skill is self-contained: `onboarding/reference/` holds everything it needs to know,
and `onboarding/examples/` one annotated YAML per source tag. To onboard by hand, start
at [the walkthrough](onboarding/reference/walkthrough.md).

## Install once

```bash
tilewright skills install
```

This symlinks each skill into `~/.claude/skills/`. The link follows the package, so
upgrading `tilewright` upgrades the skill. In a checkout the link points at this directory,
and a session opened in the checkout offers `/onboarding` without installing.

## Run it

Open Claude Code in your **data root**, the directory the dataset YAML will live under,
and type:

```
/onboarding
```
