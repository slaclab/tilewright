---
hide:
  - navigation
  - toc
---

# TileWright

Register scientific HDF5 datasets in a [Tiled](https://blueskyproject.io/tiled/) catalog,
then find them by their physics and read them from anywhere. Your data keeps the names and
the files it already has.

Describe a dataset once, in one YAML, and publish it in two commands:

```bash
tilewright manifest .tilewright/datasets/MY_DATASET.yml     # validate, derive the key, scan the files
tilewright register .tilewright/datasets/MY_DATASET.yml     # publish into a running server
```

From then on anyone who can reach the server can query it by its physics and read an
array without knowing where the files live:

```python
c = from_uri(URL, api_key=KEY)
hits = c["MY_DATASET"].search(Key("sigma") >= 0.04)
hits.values().first()["rixs_spectrum"][:]     # (151, 40)
```

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **Start here**

    ---

    Install `tilewright` and point it at a server. Reading a catalog someone else built
    needs only the Tiled client.

    [:octicons-arrow-right-24: Install](install.md)

- :material-upload:{ .lg .middle } **Publish a dataset**

    ---

    Author the YAML (an agent can draft it), build the manifests, register, read it back.

    [:octicons-arrow-right-24: Publish](ONBOARDING.md)

- :material-lightbulb-on:{ .lg .middle } **Understand**

    ---

    What TileWright adds to Tiled, the data model it registers, and why the contract is
    shaped the way it is.

    [:octicons-arrow-right-24: Explanation](explanation/broker-and-tiled.md)

- :material-book-open-page-variant:{ .lg .middle } **Reference**

    ---

    The three commands, every dataset YAML field, the Parquet manifest columns, and every
    error by symptom.

    [:octicons-arrow-right-24: Reference](reference/cli.md)

</div>
