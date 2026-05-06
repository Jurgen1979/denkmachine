"""Push alle lokale bestanden naar GitHub via de Git Data API.

Gebruik: python scripts/push_to_github.py [bericht]

Vereist: GITHUB_TOKEN env-var met write-rechten op de repo.
Werkt ook als de lokale en remote git-histories niet gedeeld zijn.
"""

import base64
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

REPO = "Jurgen1979/denkmachine"
BASE_URL = "https://api.github.com"

# mappen die nooit naar GitHub gepusht worden
IGNORE = {
    ".git", "__pycache__", "data", "logs", "projects",
    ".cache", ".pytest_cache", ".ruff_cache",
}


def gh(method: str, path: str, body=None) -> dict:
    """Stuur een GitHub API-request en geef de JSON-respons terug."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "User-Agent": "denkmachine",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def main() -> None:
    bericht = sys.argv[1] if len(sys.argv) > 1 else None

    # huidige remote ref ophalen
    ref = gh("GET", f"/repos/{REPO}/git/refs/heads/main")
    base_sha = ref["object"]["sha"]
    print(f"GitHub base: {base_sha[:8]}")

    base_commit = gh("GET", f"/repos/{REPO}/git/commits/{base_sha}")
    base_tree_sha = base_commit["tree"]["sha"]

    # lokale bestanden verzamelen en uploaden als blobs
    root = pathlib.Path(".")
    tree_items = []
    for f in sorted(root.rglob("*")):
        if f.is_file() and not any(p in IGNORE for p in f.parts):
            content = f.read_bytes()
            blob = gh(
                "POST", f"/repos/{REPO}/git/blobs",
                {"content": base64.b64encode(content).decode(), "encoding": "base64"},
            )
            tree_items.append(
                {"path": str(f), "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )

    print(f"{len(tree_items)} bestanden klaargezet")

    # nieuwe tree aanmaken
    new_tree = gh(
        "POST", f"/repos/{REPO}/git/trees",
        {"base_tree": base_tree_sha, "tree": tree_items},
    )

    # commit-bericht samenstellen
    if not bericht:
        last = subprocess.check_output(
            ["git", "--no-optional-locks", "log", "--oneline", "-1"]
        ).decode().strip()
        bericht = f"sync vanuit replit: {last}"

    # nieuwe commit aanmaken
    new_commit = gh(
        "POST", f"/repos/{REPO}/git/commits",
        {"message": bericht, "tree": new_tree["sha"], "parents": [base_sha]},
    )

    # ref bijwerken
    gh("PATCH", f"/repos/{REPO}/git/refs/heads/main",
       {"sha": new_commit["sha"], "force": True})

    print(f"GitHub main -> {new_commit['sha'][:8]}: {bericht}")


if __name__ == "__main__":
    main()
