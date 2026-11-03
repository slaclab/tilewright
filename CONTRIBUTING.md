# Contributing

## Layout

| Path | What |
|---|---|
| `src/tilewright/contract.py` | the dataset YAML contract (pydantic). The single source of truth for every field; the reference page is generated from it |
| `src/tilewright/vocabulary.yml` | canonical ids and aliases for the facets; grows by pull request |
| `src/tilewright/manifest.py` | YAML → Parquet manifests; key stamping; identity and collisions |
| `src/tilewright/register.py` | manifests → Tiled over HTTP; both transports; fingerprint cases; verify |
| `src/tilewright/delete.py`, `client.py`, `adapter.py` | deletion; same-filesystem reads; the server-side array adapter |
| `examples/datasets/` | one annotated YAML per source tag; tests assert they validate with zero warnings |
| `tests/` | offline by default; `-m integration` needs `TILED_URL`/`TILED_API_KEY` and a server with data |
| `docs/` | the site; `docs/adr/` is internal and unpublished |
| `scripts/` | maintainer tools, not installed, not on the CLI |
| `.claude/skills/` | `onboarding` for producers, `vocab-review` for maintainers |

## Running things

```bash
uv run tilewright --help
uv run --extra test pytest                 # offline suite
uv run --extra test pytest -m integration  # against a live server
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
uv run --with 'mkdocs-material>=9,<10' mkdocs serve
```

## Issues, pull requests, branches and commits

The shape of an issue or a PR is in the templates under `.github/`; GitHub fills them in
when you open one. The rules the templates cannot enforce:

**Branches.** `main` is the only long-lived branch, the only one CI runs on, and releases
are tags on it. Every change is a short-lived branch off `main`, named
`<kind>/<what-it-does>` in lowercase with hyphens:

| Prefix | Use for |
|---|---|
| `feature/` | new behavior an author or reader can use |
| `bug/` | a defect filed as an issue, which the PR closes |
| `fix/` | a small correction with no issue: a typo, a flaky test, a CI pin |
| `optimization/` | the same behavior, faster or lighter |
| `docs/` | documentation only |
| `<custom>/` | an area of the repo when none of the above fits, e.g. `contract/` |

One branch per concern, matching one PR. A branch that depends on another is based on it
and its PR opens with **Stacked on #N**. A long-running experiment branch such as
`tilewright-bench` may exist, but nothing ships from it: changes reach `main` by a PR per
concern that says where it was ported from. Delete the branch after its PR merges.

**Issues.** One defect or one decision per issue, titled as a plain sentence naming the
behavior. A bug carries a network-free reproduction script whose exit code is 1 while the
defect is present, 0 once fixed, 2 if inconclusive. A docs gap carries none. Link related
work with `Part of #N`.

**Pull requests.** One concern per PR, titled as what the change does for the person
using the tool. Every behavior change ships with a test that fails without it and the docs
rows that describe it, in the same PR. If a design choice the issue left open was made,
say why in the body. CI must be green before review. Merge with a merge commit.

**Commits.** The subject is one imperative sentence, capitalized, describing the behavior
that changed, with no `fix:`/`feat:` prefix; an area word with a colon is fine on a wide
commit (`CI: pin actions to commit SHAs`). Each commit stands on its own and passes the
offline tests. A review round is a new commit, not a force-push. Generated files travel
with their source.

**AI assistance.** A commit, PR or issue an agent helped write ends with
`Assisted-by: <harness>:<model>`, the convention the [Scientific Python development
guide](https://learn.scientific-python.org/development/guides/ai/) recommends; in this
repo today that is `Assisted-by: Claude Code:claude-fable-5-1`. Never `Co-authored-by`
for an AI tool, and an agent never adds `Signed-off-by`.

**By hand.** Labels (`bug`, `documentation`, `enhancement`), assignee and reviewers are set
in GitHub after filing or opening. The templates do not set them and an agent should not
guess them.

## Changing the contract

1. Edit the models in `contract.py`. Every field carries a `description`; write it for
   the person authoring a YAML.
2. `uv run --python 3.12 scripts/build_yaml_reference.py` regenerates `docs/reference/dataset-yaml.md`.
   Commit both; the docs workflow fails if they disagree.
3. `tests/test_contract.py::test_concept_budget` pins the top-level keys and the source
   tags. Adding a key or a tag means editing that test in the same PR, and writing an ADR
   in `docs/adr/`: contract growth is deliberate.
4. Update the example YAMLs and the onboarding skill's Step 2 if authors need to know.

## Adding a vocabulary term

Only `src/tilewright/vocabulary.yml` changes. Run `scripts/vocab_report.py` against a
server to see what authors are actually writing; the `vocab-review` skill walks through
deciding alias versus new id. Do not add a facet there; facets are contract fields.

## Documentation: one fact, one home

Every fact lives on exactly one page, and other pages link to it:

| Fact | Home |
|---|---|
| what a field means | `reference/dataset-yaml.md` (generated) |
| the count formulas | `reference/errors.md`, "Expected counts" |
| the read-back snippet | `ONBOARDING.md` step 5 |
| how local and server paths agree | `ONBOARDING.md` step 3 |
| the server config lines | `host-a-server.md` |
| connecting (`TILED_URL`, the check) | `includes/connect.md`, transcluded with `--8<--` |
| why a decision was made | `docs/adr/` (unpublished) or an explanation page |

Guides say how, explanation pages say why, reference pages list. A how-to that needs a
"why" links to the explanation rather than repeating it. Retired terms: "Mode A/B",
"layout", "stamp-key", "generate", "broker" as the product name.

## Scripts

| Script | Who runs it | When |
|---|---|---|
| `scripts/build_yaml_reference.py` | anyone changing `contract.py`; CI checks | after editing the models |
| `scripts/vocab_report.py` | a maintainer | before a release, after a workshop |
| `scripts/mint_api_keys.py` | a server operator | to issue per-person keys with expiry |
