`tilewright` and the Python client both need the server URL and an API key with write
scopes. Export them once in the shell you work from, or pass `--url` and `--api-key` on
each command; nothing is read from a file.

```bash
export TILED_URL=<the server URL>
export TILED_API_KEY=<your key>
```

Check that both work:

```bash
python -c "
import os
from tiled.client import from_uri
print(list(from_uri(os.environ['TILED_URL'], api_key=os.environ['TILED_API_KEY'])))
"
```

A list of dataset keys means you are connected. `KeyError` means a variable is not
exported in this shell. `Connection refused` means the URL is wrong or the server is down.
`401` means the key is wrong or expired.

!!! tip "Pixi users"

    If that snippet fails with `SyntaxError: invalid syntax`, the quotes were stripped
    before Python saw them. Run `pixi shell` once, then run the `python -c ...` normally.
