# Horse Tinder

Tinder, but for horses. Swipe right on a horse you like; if the horse likes you
back (some are pickier than others) it's a match, and you can chat. The horse
will reply. The replies aren't very good.

- **Backend:** Python, FastAPI, SQLite through the stdlib `sqlite3` module (`backend/horse_tinder`)
- **Frontend:** plain HTML, CSS and JS with no build step (`frontend/`), served by the backend
- **Toolchain:** Nix flake; `flake.lock` pins nixpkgs and with it Python and every dependency
- **CI:** GitHub Actions (`.github/workflows/ci.yml`); actions pinned to commit SHAs, Nix version and runner image pinned

## Running

```sh
nix run                      # http://127.0.0.1:8000
PORT=3000 HOST=0.0.0.0 nix run
```

The database is created at `data/horse-tinder.db` (override with `HORSE_TINDER_DB`)
and seeded from `backend/horse_tinder/horses.json` on startup.

## Development

```sh
nix develop
PYTHONPATH=backend python -m horse_tinder.app
pytest
ruff check . && ruff format --check .
nix flake check              # everything CI runs
```

## Dependency updates (Renovate)

`renovate.json` makes Renovate open PRs for:

- `flake.lock`: the `nixpkgs` input, plus weekly lock file maintenance
- GitHub Actions in `.github/workflows/`, kept pinned to commit SHAs
- the `ubuntu-24.04` runner image
- the Nix version CI installs (`releases.nixos.org/nix/nix-X.Y.Z/install`)

New versions must be at least a day old (`minimumReleaseAge`) before Renovate proposes them.

### Self-hosting

`nix run .#renovate` runs Renovate pinned by `flake.lock`, with `nix` and `git` on its
`PATH`, using the global config in `renovate/global.json` (GitHub, only repos that have
a `renovate.json`).

```sh
# try the config locally, no token, no branches: just lists the updates it would make
nix run .#renovate -- --platform=local

# real run: needs a GitHub token that can push branches and open PRs
export RENOVATE_TOKEN=github_pat_...
nix run .#renovate -- OWNER/horse-tinder

# validate the config files
nix shell --inputs-from . nixpkgs#renovate -c renovate-config-validator renovate.json
```

Another forge works too, e.g. `RENOVATE_PLATFORM=forgejo RENOVATE_ENDPOINT=https://git.example.com`. Point `RENOVATE_CONFIG_FILE` at your own file to replace the global config.
To run it regularly, put the same command in a systemd timer or cron job.

## API

Users are anonymous and identified by an `ht_session` cookie issued on first request.

| Method | Path | |
|---|---|---|
| GET | `/api/horses?limit=5` | Horses you haven't swiped yet |
| POST | `/api/swipes` | `{"horse_id": 1, "liked": true}` → `{"matched": bool, "horse": ...}` |
| GET | `/api/matches` | Your matches with the latest message |
| GET/POST | `/api/matches/{id}/messages` | Read or send (`{"body": "hi"}`) chat messages |
| GET | `/api/stats` | Swipe counts |
| POST | `/api/reset` | Forget your swipes and matches |

## Photos

All photos come from Wikimedia Commons featured pictures and are CC BY-SA licensed.
Author, license and source link for each are in `horses.json` and shown on every card.
`python3 scripts/fetch_photos.py` downloads them again and refreshes the attribution.
