# Contributing

## Layout

| Path | What |
|---|---|
| `src/tilewright/contract.py` | the dataset YAML contract (pydantic). The single source of truth for every field; the reference page is generated from it |
| `src/tilewright/vocabulary.yml` | canonical ids and aliases for the facets; grows by pull request |
| `src/tilewright/manifest.py` | YAML → Parquet manifests; key stamping; identity and collisions |
| `src/tilewright/register.py` | manifests → Tiled over HTTP; both transports; fingerprint cases; verify |
| `src/tilewright/delete.py`, `client.py`, `adapter.py` | deletion; same-filesystem reads; the server-side array adapter |
| `tests/` | offline by default; `-m integration` needs `TILED_URL`/`TILED_API_KEY` and a server with data |
| `docs/` | the site; `docs/adr/` is internal and unpublished |
| `scripts/` | maintainer tools, not installed, not on the CLI |
| `skills/onboarding/` | the producer skill, shipped in the wheel: `SKILL.md`, `reference/` (everything onboarding needs to know) and `examples/` (one annotated YAML per source tag; tests assert they validate with zero warnings). `tilewright skills install` links it into `~/.claude/skills/`; `.claude/skills/onboarding` is a symlink to it |
| `.claude/skills/` | Claude Code skills for maintainers (`vocab-review`); load only in a session opened here |

## Running things

```bash
uv run tilewright --help
uv run --extra test pytest                 # offline suite
uv run --extra test pytest -m integration  # against a live server
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
uv run --with 'mkdocs-material>=9,<10' mkdocs serve
```

## Changing the contract

1. Edit the models in `contract.py`. Every field carries a `description`; write it for
   the person authoring a YAML.
2. `uv run scripts/build_yaml_reference.py` regenerates `skills/onboarding/reference/dataset-yaml.md`.
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
| what a field means | `skills/onboarding/reference/dataset-yaml.md` (generated) |
| the count formulas | `skills/onboarding/reference/errors.md`, "Expected counts" |
| the read-back snippet | `skills/onboarding/reference/walkthrough.md` step 5 |
| how local and server paths agree | `skills/onboarding/reference/walkthrough.md` step 3 |
| that nothing fills `metadata` in from the files, root attributes included | `skills/onboarding/reference/walkthrough.md` step 1, the `metadata` bullet |
| what a checkout gives that a plain install does not | `docs/install.md`, "No checkout" |
| the server config lines | `skills/onboarding/reference/config-pointer.yml`, embedded in `docs/host-a-server.md` |
| connecting (`TILED_URL`, the check) | `includes/connect.md`, transcluded with `--8<--` |
| why a decision was made | `docs/adr/` (unpublished) or an explanation page |

Onboarding facts live in `skills/onboarding/`, which ships in the wheel; `docs/` holds what
operators and catalog readers need. Pages link across the two by GitHub URL.

Guides say how, explanation pages say why, reference pages list. A how-to that needs a
"why" links to the explanation rather than repeating it. Retired terms: "Mode A/B",
"layout", "stamp-key", "generate", "broker" as the product name.

## Scripts

| Script | Who runs it | When |
|---|---|---|
| `scripts/build_yaml_reference.py` | anyone changing `contract.py`; CI checks | after editing the models |
| `scripts/vocab_report.py` | a maintainer | before a release, after a workshop |
| `scripts/mint_api_keys.py` | a server operator | to issue per-person keys with expiry |
