"""The branch ledger (idea #74): work that lives only on unmerged branches.

Several sessions have left work on branches that never reached main, and more
than once a module was described as live when it only existed on one of them.
This lists every local and remote branch not merged into main, with its
commits that main doesn't have and the files that exist only there.

    .venv\\Scripts\\python.exe packaging\\branches.py

Read-only: it runs git log / ls-tree / diff, never checkout, merge or delete.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return done.stdout if done.returncode == 0 else ""


def unmerged(base: str = "main") -> list[str]:
    names = git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").split()
    merged = set(git("branch", "-a", "--format=%(refname:short)", "--merged", base).split())
    return [n for n in names if n not in merged and not n.endswith("/HEAD") and n not in (base, f"origin/{base}")]


def ledger(base: str = "main") -> list[dict]:
    base_files = set(git("ls-tree", "-r", "--name-only", base).split("\n"))
    out = []
    for branch in unmerged(base):
        commits = [line for line in git("log", "--oneline", f"{base}..{branch}").splitlines() if line]
        if not commits:
            continue
        files = set(git("ls-tree", "-r", "--name-only", branch).split("\n"))
        only = sorted(f for f in files - base_files if f)
        changed = [f for f in git("diff", "--name-only", f"{base}...{branch}").splitlines() if f]
        out.append({"branch": branch, "commits": commits, "only_here": only, "changed": changed})
    return out


def main() -> int:
    found = ledger()
    if not found:
        print("Every branch is merged into main.")
        return 0
    for b in found:
        print(f"{b['branch']}: {len(b['commits'])} commit(s) not on main, {len(b['changed'])} file(s) changed")
        for line in b["commits"][:5]:
            print(f"    {line}")
        if len(b["commits"]) > 5:
            print(f"    ... and {len(b['commits']) - 5} more")
        if b["only_here"]:
            print("  only on this branch: " + ", ".join(b["only_here"][:12])
                  + (f" and {len(b['only_here']) - 12} more" if len(b["only_here"]) > 12 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
