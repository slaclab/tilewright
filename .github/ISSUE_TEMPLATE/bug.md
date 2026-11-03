---
name: Bug
about: Something the tool does that it should not, or fails to do
title: ""
---

<!--
Title: one plain sentence saying what is wrong. Name the behavior, not the file.
  e.g. "a params dataset named uid silently replaces the manifest's identity column"
One defect per issue. Set the label and assignee by hand after filing.
Rules: CONTRIBUTING.md, "Issues, pull requests, branches and commits".
-->

## Summary

<!-- What happens, what should happen, who it hurts. Two or three short paragraphs at most. -->

## Evidence

<!-- Where in the code it happens, at a named commit. Link to lines on GitHub. -->

## Reproduction

<!--
A script that needs no server or network.
Exit 1 = defect present, 0 = fixed, 2 = inconclusive. State the commit you ran it at.
Put the script itself in the <details> block at the end.
-->

```bash
python repro_<name>.py; echo "exit=$?"
```

- **Exit codes:** 1 means ..., 0 means ..., 2 is inconclusive.
- **Observed:** exit 1 at `<commit>`.

## What a fix has to do

<!-- The options, and which one you lean to. -->

Part of #N. <!-- or delete -->

<details><summary>repro_<name>.py</summary>

```python
```

</details>

<!-- If an agent wrote this issue, end with the same line a commit carries: -->
<!-- Assisted-by: <harness>:<model> -->
