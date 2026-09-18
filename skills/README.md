# Skills for dataset producers

Claude Code skills for people publishing data with TileWright. Maintainer skills live in
`.claude/skills/` and load only in a session opened in this repository.

| Skill | What it does |
|---|---|
| `onboarding` | Drafts the dataset YAML from your HDF5 files, asks what the files cannot say, then runs `tilewright manifest` and `tilewright register` and reads the result back |

## Install once

From your TileWright checkout:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/onboarding" ~/.claude/skills/onboarding
```

The symlink keeps the skill in step with the checkout: `git pull` updates it. The skill
reads the contract from this checkout, so keep the checkout where it is.

## Run it

Open Claude Code in your **data root**, the directory the dataset YAML will live under,
and type:

```
/onboarding
```

A session opened in the checkout itself also offers `/onboarding`. The walkthrough the
skill follows is [How to publish a dataset](../docs/ONBOARDING.md).
