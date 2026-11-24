#!/usr/bin/env python3
"""
update_profile.py — mantiene vivo el perfil s7mu/s7mu (solo stdlib, sin dependencias).

Qué actualiza:
  1. README.md           -> tabla HI-SCORES (entre <!-- HISCORES:START --> y <!-- HISCORES:END -->)
  2. assets/room.svg     -> últimos commits de la "terminal" y el HI-SCORE del HUD
  3. assets/card-*.svg   -> estrellas (★) de cada tarjeta de PROJECTS

Uso:
  python3 scripts/update_profile.py             # escribe los cambios
  python3 scripts/update_profile.py --dry-run   # solo muestra lo que haría
  GH_USER=s7mu GITHUB_TOKEN=ghp_xxx python3 scripts/update_profile.py
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ── CONFIGURACIÓN ───────────────────────────────────────────────────────────
USER = os.environ.get("GH_USER", "s7mu")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ROOM_SVG = ROOT / "assets" / "room.svg"
CARDS = {  # repo -> SVG con marcadores <!--STARS:<repo>:START-->…<!--STARS:<repo>:END-->
    "s7ghost": ROOT / "assets" / "card-s7ghost.svg",
    "dockerlabs-writeups": ROOT / "assets" / "card-dockerlabs.svg",
}

TOP_N = 3                          # filas de la tabla HI-SCORES
SKIP_REPOS = {USER.lower()}        # el repo del perfil (s7mu/s7mu) no compite
COMMITS_SHOWN = 4                  # líneas de `git log` en la terminal del banner
COMMIT_MSG_MAX = 26                # caracteres del mensaje (cabe en la pantalla CRT)

# Etiqueta "CLASS" por repo (si falta: lenguaje + primer topic del repo)
CLASS_LABEL = {
    "s7ghost": "Cybersecurity",
    "dockerlabs-writeups": "Linux",
    "asir-wiki": "Systems",
}
# Descripciones fijas (si no, se usa la descripción del repo en GitHub)
DESC_OVERRIDE: dict[str, str] = {}

RANK = ["1ST", "2ND", "3RD", "4TH", "5TH"]
MEDAL = ["🥇", "🥈", "🥉"]


# ── GITHUB API ──────────────────────────────────────────────────────────────
def gh(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{USER}-profile-updater",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urlopen(Request(f"https://api.github.com{path}", headers=headers), timeout=20) as r:
        return json.load(r)


def fetch_repos() -> list[dict]:
    repos = gh(f"/users/{USER}/repos?type=owner&per_page=100&sort=pushed")
    return [r for r in repos if not r["fork"] and r["name"].lower() not in SKIP_REPOS]


def rank_repos(repos: list[dict]) -> list[dict]:
    # más estrellas primero; a igualdad, el más recientemente actualizado
    return sorted(repos, key=lambda r: (r["stargazers_count"], r.get("pushed_at") or ""), reverse=True)


def fetch_commits(repos: list[dict]) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    recent = sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)[:5]
    for r in recent:
        try:
            for c in gh(f"/repos/{USER}/{r['name']}/commits?per_page=3&author={USER}"):
                items.append((c["commit"]["author"]["date"], c["sha"][:7], c["commit"]["message"].splitlines()[0]))
        except HTTPError as e:
            if e.code != 409:  # 409 = repositorio vacío
                raise
    items.sort(reverse=True)  # ISO-8601 UTC ordena bien como texto
    return items[:COMMITS_SHOWN]


# ── RENDER ──────────────────────────────────────────────────────────────────
def md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def hiscores_md(ranked: list[dict]) -> str:
    rows = [
        "| RANK | PLAYER | CLASS | SCORE | MISSION LOG |",
        "|:----:|:-------|:------|------:|:------------|",
    ]
    for i, r in enumerate(ranked[:TOP_N]):
        name = r["name"]
        topic = (r.get("topics") or [""])[0].replace("-", " ").title()
        label = CLASS_LABEL.get(name) or topic
        klass = " · ".join(f"`{x}`" for x in (r.get("language") or "—", label) if x)
        desc = md_cell(DESC_OVERRIDE.get(name) or r.get("description") or "—")
        medal = MEDAL[i] if i < len(MEDAL) else "▪️"
        rows.append(
            f"| {medal} `{RANK[i]}` | [**{name.upper()}**]({r['html_url']}) | {klass} "
            f"| `{r['stargazers_count']:04d}` 🌟 | {desc} |"
        )
    return "\n".join(rows)


def commits_svg(commits: list[tuple[str, str, str]], y0: int = 134, step: int = 22) -> str:
    out = []
    for i, (_, sha, msg) in enumerate(commits):
        short = msg if len(msg) <= COMMIT_MSG_MAX else msg[: COMMIT_MSG_MAX - 1] + "…"
        out.append(
            f'<text x="434" y="{y0 + i * step}" font-size="14">'
            f'<tspan fill="#58a6ff">{sha}</tspan> '
            f'<tspan fill="#3fb950">{html.escape(short, quote=False)}</tspan></text>'
        )
    return "".join(out)


# ── UTILIDADES ──────────────────────────────────────────────────────────────
def replace_between(text: str, tag: str, new: str) -> str:
    pat = re.compile(
        rf"(<!--\s*{re.escape(tag)}:START\s*-->)(.*?)(<!--\s*{re.escape(tag)}:END\s*-->)", re.S
    )
    if not pat.search(text):
        raise ValueError(f"No encuentro los marcadores {tag}:START / {tag}:END")
    return pat.sub(lambda m: m.group(1) + new + m.group(3), text, count=1)


def save(path: Path, new: str, dry: bool) -> None:
    rel = path.relative_to(ROOT)
    if new == path.read_text(encoding="utf-8"):
        print(f"=  {rel}: sin cambios")
    elif dry:
        print(f"~  {rel}: cambiaría (dry-run)")
    else:
        path.write_text(new, encoding="utf-8")
        print(f"✓  {rel}: actualizado")


# ── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no escribe nada, solo muestra el resultado")
    args = ap.parse_args()

    try:
        repos = fetch_repos()
        commits = fetch_commits(repos)
    except (HTTPError, URLError) as e:
        print(f"[x] Error consultando la API de GitHub: {e}", file=sys.stderr)
        return 1
    if not repos:
        print(f"[!] {USER} no tiene repos públicos propios que listar", file=sys.stderr)
        return 1

    ranked = rank_repos(repos)
    table = hiscores_md(ranked)
    if args.dry_run:
        print(table, end="\n\n")
        for _, sha, msg in commits:
            print(f"   {sha} {msg}")
        print()

    try:
        # 1) README: tabla HI-SCORES
        save(README, replace_between(README.read_text(encoding="utf-8"), "HISCORES", f"\n\n{table}\n\n"), args.dry_run)

        # 2) Banner: commits + HI-SCORE del HUD
        room = ROOM_SVG.read_text(encoding="utf-8")
        room = replace_between(room, "HISCORE", f"{ranked[0]['stargazers_count']:04d}")
        if commits:  # si no hay commits visibles, se conserva lo que ya estaba
            room = replace_between(room, "COMMITS", commits_svg(commits))
        save(ROOM_SVG, room, args.dry_run)

        # 3) Tarjetas: estrellas
        by_name = {r["name"].lower(): r for r in repos}
        for repo, path in CARDS.items():
            r = by_name.get(repo.lower())
            if r is None:
                print(f"[!] {repo}: no aparece en tu cuenta, tarjeta sin tocar")
                continue
            save(path, replace_between(path.read_text(encoding="utf-8"), f"STARS:{repo}", str(r["stargazers_count"])), args.dry_run)
    except ValueError as e:
        print(f"[x] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
