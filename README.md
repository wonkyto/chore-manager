# Chore Manager

![Chore Manager](docs/homescreen-icon.png)

A household chore tracker for families. Each person gets a column showing their tasks for the day. Tap a chore to mark it done; it turns green and earns Chorecoins. Kids redeem Chorecoins for rewards (screen time, pocket money, etc.) which queue for a parent to approve or deny via PIN.

## Features

- Today view with one column per family member
- Flexible chore scheduling: daily, weekly, fortnightly, monthly, annual, or every N days
- Chorecoins awarded per chore, tallied live without a page refresh
- Streak counter when a chore is completed on consecutive scheduled occurrences
- Reward redemption with parent approval - Chorecoins are held until approved or denied
- Parental PIN lock - historical edits and redemption approvals require a PIN, with a short unlock window (configurable, default 60 seconds)
- Navigate back and forward through days to review history or preview upcoming chores
- Per-device "viewing as" mode via cookie - set it on a personal device to see only your column
- App and family config live in YAML files; changes are picked up on the next page load with no restart
- Ad-hoc tasks - parents can add one-off tasks with custom Chorecoins; the name field suggests all previously used task names and auto-fills the value for known chores
- Manual Chorecoin adjustments - parents can add or deduct Chorecoins (preset buttons or a custom amount, with an optional reason) for bonuses, corrections, or penalties outside the chore system
- Per-day chore reassignment - parents can move a chore from one person's column to another for a single day (the YAML stays the source of truth); the new person earns the Chorecoins when they tick it off
- Per-person stats page (`/stats/<person_key>`) showing streak, 30-day completion rate, all-time Chorecoins, weekly trend, a 4-week chart, and a per-chore breakdown
- Holiday mode - parents can mark a date range as a holiday (per person or family-wide); chores are hidden on those days and streaks aren't broken
- Family-wide chores - mark a chore `claim_first: true` to show it in every eligible column; the first person to tap claims the Chorecoins and the chore disappears from everyone else's column
- Configurable day rollover - set `day_rollover_hour` in `app.yaml` so late-night taps (e.g. before 4am) still land on the previous day
- Per-person activity timeline at `/audit/<person_key>` showing completions, ad-hoc tasks, adjustments, redemptions, reassignments and skips. Audit events also stream to stdout, and to `log/audit.log` when `CHORE_AUDIT_LOG` is set
- Achievements - bronze/silver/gold badges shown on the stats page for milestones (first chore, 100/500/1000 Chorecoins, 3/7/14-day streaks, perfect day, perfect Monday, perfect week, first reward); progress bars show how close locked badges are

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
day_rollover_hour: 0         # hour (0-23) when "today" rolls. e.g. 4 means 0-4am still counts as the previous day
penalty_start_date: "2026-01-01"  # penalties never applied before this date; set to your go-live date
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

The `points` field sets how many Chorecoins the chore is worth. Add `penalty` to deduct Chorecoins the following morning if the chore wasn't completed:

```yaml
  - key: school_bag
    name: Put away school bag
    points: 0
    penalty: 50
    frequency: weekly
    days: [fri]
    assigned_to: [bob]
```

Add `start_date` to any chore to prevent it appearing or incurring penalties before that date. Useful when adding a new chore mid-deployment:

```yaml
  - key: homework
    name: Do homework
    points: 0
    penalty: 50
    frequency: weekly
    days: [mon, tue, wed, thu]
    start_date: "2026-05-07"
    assigned_to: [bob]
```

Add `claim_first: true` to make a chore family-wide. It shows in every column listed in `assigned_to`; the first eligible person to tap it earns the Chorecoins and it disappears from everyone else's column.

```yaml
chores:
  - key: bins
    name: Take out the bins
    points: 8
    frequency: weekly
    days: [tue]
    claim_first: true
    assigned_to: [alice, bob]
```

#### Frequencies

| frequency      | required fields                                  | example                   |
| -------------- | ------------------------------------------------ | ------------------------- |
| `daily`        | -                                                | every day                 |
| `weekly`       | `days` (list of `mon`...`sun`)                   | mon/wed/fri               |
| `fortnightly`  | `days`, `anchor_date` (ISO date in an "on" week) | bins every other Tuesday  |
| `monthly`      | `day_of_month` (1-31)                            | rent on the 1st           |
| `annual`       | `month` (1-12), `day_of_month` (1-31)            | smoke alarms on 1 April   |
| `every_n_days` | `every_days` (>= 2), `anchor_date`               | water plants every 3 days |

`day_of_month` is clamped to the actual length of the month, so `31` always means "last day of the month" (April lands on the 30th, February on the 28th or 29th). The same applies to annual chores - `month: 2, day_of_month: 29` fires on 28 Feb in non-leap years.

For `fortnightly`, `anchor_date` is any date that falls in an "on" week; the app works out which fortnights are due from there. For `every_n_days`, `anchor_date` is the first occurrence - the chore doesn't appear before that date.

```yaml
chores:
  - key: bins
    name: Put bins out
    points: 10
    frequency: fortnightly
    days: [tue]
    anchor_date: 2026-05-05
    assigned_to: [alice]

  - key: rent
    name: Pay rent
    points: 5
    frequency: monthly
    day_of_month: 1
    assigned_to: [alice]

  - key: filter
    name: Replace AC filter
    points: 15
    frequency: monthly
    day_of_month: 31         # always the last day of the month
    assigned_to: [alice]

  - key: smoke
    name: Test smoke alarms
    points: 20
    frequency: annual
    month: 4
    day_of_month: 1
    assigned_to: [alice]

  - key: water
    name: Water plants
    points: 3
    frequency: every_n_days
    every_days: 3
    anchor_date: 2026-04-30
    assigned_to: [bob]
```

#### Task templates

`task_templates` in `family.yaml` provide quick-select suggestions in the ad-hoc task form, with points pre-filled:

```yaml
task_templates:
  - name: Vacuum living room
    points: 15
  - name: Empty recycling bin
    points: 10
```

### Data storage

Chore completions and redemptions are stored in a SQLite database. The location is controlled by the `CHORE_DATA_DIR` environment variable (set in the compose files). Data persists across container restarts via a volume mount.

## Production deployment

Copy `docker-compose.prod.yml`, `config/family.yaml`, and `config/app.yaml` to the server, then create the required directories:

```bash
mkdir -p /data/docker/chore-manager/config
mkdir -p /data/docker/chore-manager/data
mkdir -p /data/docker/chore-manager/log
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

## Migrating to PostgreSQL

The app uses SQLAlchemy throughout, so switching from SQLite to PostgreSQL is a matter of pointing it at a different database URL. No query rewrites needed.

### What already works

The database URL is read from the `CHORE_DB_URL` environment variable. SQLite is used when it isn't set. Set it to a Postgres connection string and the ORM will use that instead:

```bash
CHORE_DB_URL=postgresql+psycopg2://user:password@host:5432/chore_manager
```

The SQLite-specific tuning (`WAL mode`, `BEGIN IMMEDIATE`, `busy_timeout`) is skipped automatically when the dialect isn't SQLite, so no code changes are needed there.

### What needs attention

**Driver dependency** - Add `psycopg2-binary` (or `psycopg[binary]` for the newer v3 driver) to `pyproject.toml`:

```toml
dependencies = [
    ...
    "psycopg2-binary>=2.9",
]
```

Rebuild the Docker image after changing this.

**Schema migrations** - The built-in `_migrate()` function uses SQLite `PRAGMA table_info()` to detect missing columns and add them. That won't run on Postgres. For SQLite this is fine because schema changes are rare and the migration list is short. For Postgres you'd want a proper migration tool. [Alembic](https://alembic.sqlalchemy.org/) is the standard choice with SQLAlchemy - it can autogenerate migration scripts from model changes and apply them in order. To get started:

```bash
uv add alembic
uv run alembic init alembic
# edit alembic/env.py to point at your models and CHORE_DB_URL
uv run alembic revision --autogenerate -m "initial"
uv run alembic upgrade head
```

**Concurrency** - SQLite serialises writes with `BEGIN IMMEDIATE` to prevent double-spend on redemptions. PostgreSQL handles concurrent writes natively via its own MVCC locking, so that protection is already covered without any extra configuration.

**`db.create_all()` on first run** - For a fresh Postgres database, `db.create_all()` still runs on startup and will create all tables correctly. After that, schema changes should go through Alembic rather than `create_all`.

### docker-compose.prod.yml changes

Add the URL and a Postgres service, or point at an external Postgres instance:

```yaml
services:
  chore-manager:
    environment:
      CHORE_DATA_DIR: /app/data
      CHORE_DB_URL: postgresql+psycopg2://chore:secret@db:5432/chore_manager
      CHORE_AUDIT_LOG: /app/log/audit.log

  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: chore_manager
      POSTGRES_USER: chore
      POSTGRES_PASSWORD: secret
    volumes:
      - ./pgdata:/var/lib/postgresql/data
```

Remove the `./data:/app/data` volume mount once the SQLite file is no longer needed. The `instance/` mount for the session secret key can stay.

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
