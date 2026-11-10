#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.error
import urllib.request

WATCH = [
    {"repo": "thexeondev/kafka", "branch": "master", "label": "kafka/kafka"},
    {"repo": "thexeondev/remielle", "branch": "0.1.x", "label": "remielle/remielle"},
]
SENSITIVE = re.compile(
    r"Storage\.zig|Player\.zig|Header|\.proto|rmctl|build\.zig|config\.zon|defaults/",
    re.I,
)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
PER_PAGE = 30
KEEP = 300


def gh_get(path):
    headers = {
        "User-Agent": "commit-watcher",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_commits(w):
    # Mas nuevo primero.
    return gh_get(f"/repos/{w['repo']}/commits?sha={w['branch']}&per_page={PER_PAGE}")


def commit_files(repo, sha):
    try:
        data = gh_get(f"/repos/{repo}/commits/{sha}")
        return [f["filename"] for f in data.get("files", [])]
    except Exception as e:  # noqa: BLE001
        print(f"  no pude leer el diff de {sha[:7]}: {e}", file=sys.stderr)
        return None


def notify(text):
    if os.environ.get("DRY_RUN") == "1":
        print("--- DISCORD (dry run) ---\n" + text + "\n-------------------------")
        return
    url = os.environ.get("DISCORD_WEBHOOK")
    if not url:
        raise RuntimeError("falta DISCORD_WEBHOOK")
    body = json.dumps({"content": text[:1900]}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "commit-watcher"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def describe(w, c):
    """Devuelve (linea, afecta) para un commit."""
    sha = c["sha"]
    title = (c.get("commit", {}).get("message") or "").splitlines()[0][:80]
    files = commit_files(w["repo"], sha)
    if files is None:
        return f"`{sha[:7]}` {title} - no pude leer el diff", True
    hits = [p for p in files if SENSITIVE.search(p)]
    extra = f" (sensibles: {', '.join(hits[:5])})" if hits else ""
    return f"`{sha[:7]}` {title} - {len(files)} archivos{extra}", bool(hits)


def main():
    state = load_state()
    failed = False

    for w in WATCH:
        key = f"{w['repo']}:{w['branch']}"
        try:
            commits = list_commits(w)
            shas = [c["sha"] for c in commits]

            if key not in state:
                state[key] = list(reversed(shas))
                save_state(state)
                print(f"{key}: estado inicial sembrado ({len(shas)} commits), sin avisar")
                continue

            seen = set(state[key])
            new = [c for c in reversed(commits) if c["sha"] not in seen]
            if not new:
                print(f"{key}: sin commits nuevos")
                continue

            lines, afecta = [], False
            for c in new:
                line, hit = describe(w, c)
                lines.append(line)
                afecta = afecta or hit

            head = "⚠️ Revisar antes de aplicar" if afecta else "Commit sin impacto aparente"
            notify(f"{head}: {w['label']} {w['branch']}\n" + "\n".join(lines))

            state[key] = (state[key] + [c["sha"] for c in new])[-KEEP:]
            save_state(state)
            print(f"{key}: avisados {len(new)} commits")
        except Exception as e:  # noqa: BLE001
            failed = True
            print(f"{key}: ERROR {e}", file=sys.stderr)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
