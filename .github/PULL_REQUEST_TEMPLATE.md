<!--
Title: one sentence saying what the change does for the person using the tool.
  e.g. "Don't mistake parameters named path_* for artifact locators"
One concern per PR. Set labels, assignee and reviewers by hand after opening.
Rules: CONTRIBUTING.md, "Issues, pull requests, branches and commits".
-->

<!-- The problem, in two or three sentences: what broke and for whom. Name a real dataset if there is one. Everything else goes under Details. -->

**Fix:**
- 
- 

Closes #N.

<details><summary>Details</summary>

- Where the rule now lives:
- Docs rows and example YAMLs changed:
- Tests: N fail on `main` without this change.
- Ported from / cherry-picked from (if any), and what was left out:

</details>

<!-- Keep this section for a wide change; delete it for a one-fix PR. -->
## Verification

- `uv run --extra test pytest`: N passed (offline).
- `scripts/build_yaml_reference.py --check` and `mkdocs build --strict` pass.

## Checklist

- [ ] `uv run --extra test pytest` passes offline, and CI is green on 3.11, 3.12 and 3.13.
- [ ] The new test fails on `main` without the change, and the body says how many.
- [ ] Every fact added or changed has one home in the docs; other pages link to it.
- [ ] Contract change: `contract.py` edited, `scripts/build_yaml_reference.py` rerun, the concept-budget test updated, an ADR written.
- [ ] Example YAMLs and the onboarding skill updated if an author would need to know.
- [ ] `Closes #N` present.
- [ ] Labels, assignee and reviewers set.

<!-- If an agent helped write this PR, end with the same line its commits carry: -->
<!-- Assisted-by: <harness>:<model> -->
