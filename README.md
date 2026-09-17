# Pharmacy Inventory Management

This project is a small pharmacy inventory application. It combines a tested
Python domain service with a Flask JSON API and a vanilla HTML/CSS/JavaScript
dashboard. It uses SQLite persistence, so inventory and notification state
survive application restarts.

## Features

- Added and list medicine batches.
- Validate batch IDs, medicine names, dates, and quantities.
- Calculate sellable stock while excluding expired batches.
- Dispense using First-Expiry-First-Out (FEFO).
- Dispense across multiple batches atomically.
- Search medicine availability.
- Generate configurable expiry alerts.
- Use the browser interface or JSON API to manage inventory.
- Treat a batch expiring today as sellable.
- Run a deterministic daily clock that quarantines expired batches.
- Import messy batch records with row-level results.
- Generate deduplicated low-stock reorder notifications.
- Keep FEFO selection and all pharmacy rules inside `InventoryService`.

A batch expiring today is considered valid. A batch is expired only when its
expiry date is before today.

## Technology

- Python 3
- Python `dataclasses` and standard-library date handling
- Python built-in `unittest`
- Flask
- HTML, CSS, and vanilla JavaScript
- SQLite storage using Python's standard-library `sqlite3`

## Project structure

```text
.
├── app.py
├── main.py
├── requirements.txt
├── inventory/
│   ├── exceptions.py
│   ├── database.py
│   ├── importer.py
│   ├── models.py
│   ├── notifications.py
│   └── service.py
├── templates/
│   └── index.html
└── tests/
  ├── test_app.py
  ├── test_importer.py
  ├── test_inventory.py
  ├── test_persistence.py
  └── test_notifications.py
```

## Installation and setup

From the project root, create and activate a virtual environment, then install
the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

No additional database server or Python database package is required. The
application creates `inventory.db` and its tables automatically on first start.
The database file is ignored by git and should be backed up separately for a
production deployment.

## Run the application

```bash
python main.py
```

Open `http://127.0.0.1:5000` locally. In GitHub Codespaces, use the **Ports**
panel to find port `5000`, then click the globe/open-in-browser action for the
forwarded port.

## Tests

Run all core and Flask API tests with:

```bash
python -m unittest discover -s tests -v
```

## Persistence, FEFO, and expiry policy

`InventoryService` uses a SQLite repository underneath its existing public
methods. The default Flask application uses `inventory.db`; records are loaded
when the service starts. Tests and callers can pass `":memory:"` as the database
path for an isolated temporary database. Batch IDs are primary keys, and stock
updates, quarantine changes, imports, reorder thresholds, notification state,
and outbox records are committed to SQLite.

`InventoryService.dispense` filters to the requested medicine's batches whose
expiry date is today or later, sorts them by `(expiry_date, batch_id)`, and
consumes them in that order. It checks total sellable stock before changing any
batch, so an insufficient request leaves the inventory unchanged.

Expiry is inclusive: `expiry_date == today` is sellable, while
`expiry_date < today` is expired. Date-dependent service methods accept an
optional `today` argument for deterministic tests.

## HTTP API

All request bodies are JSON. Dates use `YYYY-MM-DD`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/` | Dashboard |
| GET | `/api/health` | Health check |
| POST | `/api/batches` | Add a batch |
| GET | `/api/batches` | List all batches |
| POST | `/api/dispense` | Dispense with FEFO |
| GET | `/api/stock/<medicine_name>` | Get sellable quantity |
| GET | `/api/search?name=paracetamol` | Search availability |
| GET | `/api/alerts?days=7` | Find upcoming expiry dates |
| POST | `/clock` | Quarantine expired batches and report seven-day alerts |
| POST | `/api/import` | Import a JSON array of messy batch records |
| POST | `/api/reorder-thresholds` | Configure a medicine reorder threshold |
| GET | `/outbox` | View generated reorder notifications |

Successful batch creation returns `201`; invalid input returns `400`; duplicate
batches and insufficient stock return `409`; successful reads and dispensing
return `200`. Unexpected API errors return JSON without a stack trace.

Example requests:

```bash
curl http://127.0.0.1:5000/api/health
curl -X POST http://127.0.0.1:5000/api/batches \
  -H 'Content-Type: application/json' \
  -d '{"batch_id":"P001","medicine_name":"Paracetamol","expiry_date":"2026-10-10","quantity":10}'
curl http://127.0.0.1:5000/api/batches
curl -X POST http://127.0.0.1:5000/api/dispense \
  -H 'Content-Type: application/json' \
  -d '{"medicine_name":"Paracetamol","quantity":7}'
curl http://127.0.0.1:5000/api/stock/Paracetamol
curl 'http://127.0.0.1:5000/api/search?name=paracetamol'
curl 'http://127.0.0.1:5000/api/alerts?days=7'
curl -X POST http://127.0.0.1:5000/clock \
  -H 'Content-Type: application/json' \
  -d '{"today":"2026-09-17"}'
curl -X POST http://127.0.0.1:5000/api/import \
  -H 'Content-Type: application/json' \
  -d '[{"batch_id":"P002","medicine_name":"Paracetamol","expiry_date":"25/09/2026","quantity":"10 units"}]'
curl -X POST http://127.0.0.1:5000/api/reorder-thresholds \
  -H 'Content-Type: application/json' \
  -d '{"medicine_name":"Paracetamol","threshold":10}'
curl http://127.0.0.1:5000/outbox
```

Successful batch creation returns `201`. Invalid input returns `400`, duplicate
batches and insufficient stock return `409`, and successful reads or dispensing
return `200`.

## Assessment demonstration

1. Start the server and open the dashboard.
2. Add P001 (`2026-10-10`, quantity `10`) and P002 (`2026-09-25`, quantity `5`).
3. Dispense `7` Paracetamol and show that P002 is reported first, followed by
	P001.
4. Add an expired batch and confirm it is excluded from stock and dispensing.
5. Add a batch expiring today and confirm it remains sellable.
6. Try to dispense more than available and show that quantities do not change.
7. Search for an unknown medicine and show its unavailable response.
8. Run the full test command and show the passing result.

## Twist rules and assumptions

### Daily clock and quarantine

`POST /clock` accepts an optional `today` value in `YYYY-MM-DD` format. If it
is omitted, the system date is used. It reports batches expiring from today
through seven days ahead, and marks batches with `expiry_date < today` as
quarantined. The operation is idempotent: a second run reports those batches as
already quarantined and does not count them again as newly quarantined.
Quarantined batches remain visible in `/api/batches` but are excluded from
sellable stock, search availability, and FEFO dispensing.

### Messy imports

`POST /api/import` accepts a JSON array. Quantities may be integers or strings
such as `"10"` and `"10 units"`; dates may be ISO (`YYYY-MM-DD`) or
`DD/MM/YYYY`. Each row is classified as `imported`, `deduped`, or `rejected`.
Repeated rows and existing batch IDs are deduped, never overwritten. Missing
fields and invalid values are rejected with row numbers and reasons. One bad row
does not prevent other valid rows from importing.

### Reorder notifications

`POST /api/reorder-thresholds` configures a non-negative integer threshold per
medicine. After successful dispensing, a notification is created when
`sellable_stock < threshold`. The same unchanged low-stock condition produces
only one pending notification. If stock reaches the threshold and later drops
below it again, a new notification may be created. Notifications are stored in
the SQLite outbox table and remain available after a restart. Low-stock state is
also persisted, preventing duplicates after a restart while the condition is
unchanged.

## Technical interview explanation

The Flask routes are an adapter: they validate request shape, call the service,
serialize dataclasses, and map expected exceptions to HTTP statuses. The
service owns validation, case-insensitive matching, expiry policy, FEFO sorting,
and atomic dispensing. This keeps the same rules usable from tests, the API, or
another interface.

## Core service API

`InventoryService` provides:

- `add_batch(batch_id, medicine_name, expiry_date, quantity)`
- `list_batches()`
- `dispense(medicine_name, quantity, today=None)`
- `sellable_stock(medicine_name, today=None)`
- `search_medicine(medicine_name, today=None)`
- `expiry_alerts(days, today=None)`

Dates may be supplied as `datetime.date` objects or ISO strings in
`YYYY-MM-DD` format. Date-dependent methods accept `today` so tests and
callers can use a deterministic current date.

## Known limitations and future improvements

- The default SQLite database is local to the application process and does not
  provide multi-instance deployment coordination.
- Authentication, users, and audit history are not included.
- A production version could add persistent storage, migrations, authorization,
  audit events, pagination, and deployment configuration.