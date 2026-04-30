# Chore Manager

A household chore tracker for families. Each person gets a column showing their tasks for the day. Tap a chore to mark it done; it turns green and earns points. Kids redeem points for rewards (screen time, pocket money, etc.) which queue for a parent to approve or deny via PIN.

## Features

- Today view with one column per family member
- Daily and weekly chores (with specific days of the week)
- Points awarded per chore, tallied live without a page refresh
- Streak counter when a chore is completed on consecutive scheduled days
- Reward redemption with parent approval - points are held until approved or denied
- Parental PIN lock - historical edits and redemption approvals require a PIN, with a short unlock window (configurable, default 60 seconds)
- Navigate back and forward through days to review history or preview upcoming chores
- Per-device "viewing as" mode via cookie - set it on a personal device to see only your column
- App and family config live in YAML files; changes are picked up on the next page load with no restart
- Ad-hoc tasks - parents can add one-off tasks with custom points; the name field suggests all previously used task names and auto-fills points for known chores
- Per-person stats page (`/stats/<person_key>`) showing streak, 30-day completion rate, all-time points, weekly trend, a 4-week points bar chart, and a per-chore breakdown

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Docker.

Copy the example configs and fill in your details:

```bash
cp config/family.example.yaml config/family.yaml
cp config/app.example.yaml config/app.yaml
```

Then run:

```bash
make run
```

The app is available at http://localhost:5000.

## Configuration

### app.yaml

App-level settings:

```yaml
app_name: My Chore Manager
timezone: Australia/Sydney
parent_pin: "1234"           # plain PIN, omit to disable PIN entirely
# parent_pin_hash: "scrypt:..."  # preferred: hash via werkzeug.security.generate_password_hash
pin_timeout_seconds: 60      # how long the PIN unlock lasts
```

`parent_pin_hash` takes precedence over `parent_pin` if both are present. To generate a hash:

```bash
uv run python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-pin'))"
```

### family.yaml

People, chores, and rewards:

```yaml
people:
  - key: alice
    name: Alice
    role: parent      # parent or child
    colour: "#4f46e5" # column header colour (hex)

chores:
  - key: dishes
    name: Empty dishwasher
    points: 5
    frequency: daily
    assigned_to: [alice]

  - key: piano
    name: Piano practice
    points: 10
    frequency: weekly
    days: [mon, wed, fri]
    assigned_to: [alice]

rewards:
  - key: screen_30
    name: 30 minutes screen time
    cost: 20
```

Valid frequencies are `daily` and `weekly`. Weekly chores take a `days` list using `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`.

### Data storage

Chore completions and redemptions are stored in a SQLite database. The location is controlled by the `CHORE_DATA_DIR` environment variable (set in the compose files). Data persists across container restarts via a volume mount.

## Production deployment

Copy `docker-compose.prod.yml`, `config/family.yaml`, and `config/app.yaml` to the server, then create the required directories:

```bash
mkdir -p /data/docker/chore-manager/config
mkdir -p /data/docker/chore-manager/data
```

Start it:

```bash
docker compose -f docker-compose.prod.yml up -d
```

The compose file binds to a specific IP (`192.168.1.1:5000`) and mounts config and data from the host. Update the image version in `docker-compose.prod.yml` and run `docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d` to upgrade.

The session secret key is generated once and persisted under the container's `instance/` directory, so PIN unlocks and the viewer cookie survive restarts. To override, set `SECRET_KEY` in `docker-compose.prod.yml`.

The container runs `waitress` (production WSGI server), as a non-root `chore` user, with a `HEALTHCHECK` that hits `/`. SQLite is opened in WAL mode and writes are serialised so concurrent redemption requests can't double-spend.

## Building and publishing

```bash
make css         # rebuild Tailwind CSS from the templates (run after template edits)
make build-all   # build for linux/amd64 + linux/arm64 and push to Docker Hub
make build-pi    # arm64 only
```

Version is set at the top of the Makefile. Both the versioned tag and `latest` are pushed.

Static assets (Tailwind CSS, htmx, canvas-confetti) are vendored under `src/chore_manager/static/` so the app has no runtime CDN dependency. `make css` downloads the standalone Tailwind CLI on first run and writes `static/app.css` from the templates.

## iOS home screen

In Safari, tap Share -> Add to Home Screen. The app uses `apple-touch-icon.png` as the icon and the `app_name` from `app.yaml` as the label. When launched from the home screen it runs without the Safari browser chrome.

## Development

```bash
make install   # install dependencies via uv
make test      # run the test suite
make lint      # check code style
make format    # auto-fix code style
```

To run locally without Docker:

```bash
uv run python -m chore_manager
```
