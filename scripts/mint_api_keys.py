"""Mint one or many Tiled API keys.

Interactive (prompts for username/password):
    python scripts/mint_api_keys.py --count 40 --out keys.csv

Non-interactive (for running from an agent / CI):
    export TILED_USERNAME=...
    export TILED_PASSWORD=...
    python scripts/mint_api_keys.py --count 40 --out keys.csv

All keys are issued under the logged-in user's identity; each row of the
output CSV is ``index,note,expiration_time,secret``. Secrets are shown ONCE.
"""
import argparse
import csv
import os
import sys

# We authenticate with username/password; a lingering API key in the
# environment (e.g. from `source .env.test`) makes tiled refuse to login.
os.environ.pop("TILED_API_KEY", None)
os.environ.pop("TILED_KEY", None)

from tiled.client.context import Context, password_grant  # noqa: E402

parser = argparse.ArgumentParser(description="Mint Tiled API keys.")
parser.add_argument(
    "--url",
    default="https://lcls-data-portal.slac.stanford.edu/tiled-test",
    help="Tiled server URL",
)
parser.add_argument(
    "--expires",
    default="14d",
    help="Key lifetime, e.g. 14d, 7d, 3600 (seconds). Default: 14d",
)
parser.add_argument(
    "--note",
    default="minted via mint_api_keys.py",
    help="Note prefix stored with each key (index is appended when --count > 1)",
)
parser.add_argument("--count", type=int, default=1, help="Number of keys to mint")
parser.add_argument(
    "--notes-file",
    default=None,
    help="File with one note per line (e.g. 'Name <email>'); key i gets line i's note. "
    "Keys beyond the file's length fall back to --note + index.",
)
parser.add_argument(
    "--out",
    default=None,
    help="Write keys to this CSV file (index,note,expiration_time,secret). "
    "Default: print to stdout only.",
)
args = parser.parse_args()

expires = int(args.expires) if args.expires.isdigit() else args.expires

# Build a bare Context (no auto-login) so we control how we authenticate.
ctx, _ = Context.from_any_uri(args.url)

username = os.environ.get("TILED_USERNAME")
password = os.environ.get("TILED_PASSWORD")
if username and password:
    # Non-interactive login: same password grant that ctx.login() performs,
    # minus the terminal prompts. Tokens are kept in memory only.
    providers = ctx.server_info.authentication.providers
    spec = next((p for p in providers if p.mode in ("internal", "password")), None)
    if spec is None:
        sys.exit("Server has no username/password provider; unset TILED_USERNAME and login interactively.")
    tokens = password_grant(
        ctx.http_client, spec.links["auth_endpoint"], spec.provider, username, password
    )
    ctx.configure_auth(tokens, remember_me=False)
else:
    ctx.login()  # prompts for username/password

assigned = []
if args.notes_file:
    with open(args.notes_file) as f:
        assigned = [ln.strip() for ln in f if ln.strip()]
    if len(assigned) > args.count:
        sys.exit(f"--notes-file has {len(assigned)} lines but --count is {args.count}")

rows = []
for i in range(1, args.count + 1):
    if i <= len(assigned):
        note = f"{args.note}: {assigned[i - 1]}"
    else:
        note = args.note if args.count == 1 else f"{args.note} #{i:02d}"
    info = ctx.create_api_key(expires_in=expires, note=note)
    rows.append((i, note, info.get("expiration_time", args.expires), info["secret"]))
    print(f"[{i}/{args.count}] minted: {note}", file=sys.stderr)

if args.out:
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "note", "expiration_time", "secret"])
        w.writerows(rows)
    os.chmod(args.out, 0o600)
    print(f"\nWrote {len(rows)} key(s) to {args.out} (mode 0600). Secrets are shown ONCE.")
else:
    print()
    print("=" * 60)
    print("New API key(s) (shown ONCE — copy now):")
    for i, note, exp, secret in rows:
        print(f"  {i:>3}  {secret}   expires {exp}")
    print("=" * 60)

print()
print("To use a key:")
print(f"  export TILED_URL={args.url}")
print("  export TILED_API_KEY=<secret>")
