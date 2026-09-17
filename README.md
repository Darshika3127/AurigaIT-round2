# Pharmacy Inventory Management

This project contains inventory and FEFO dispensing logic for a pharmacy,
exposed through a small Flask web application. It uses an in-memory repository;
data is reset whenever the application restarts.

## Features

- Add and list medicine batches.
- Validate batch IDs, medicine names, dates, and quantities.
- Calculate sellable stock while excluding expired batches.
- Dispense using First-Expiry-First-Out (FEFO).
- Dispense across multiple batches atomically.
- Search medicine availability.
- Generate configurable expiry alerts.
- Use the browser interface or JSON API to manage inventory.

A batch expiring today is considered valid. A batch is expired only when its
expiry date is before today.

## Technology

- Python 3
- Python `dataclasses` and standard-library date handling
- Python built-in `unittest`
- Flask
- In-memory storage

## Installation

From the project root, create and activate a virtual environment, then install
the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start the application with:

```bash
python main.py
```

Open <http://127.0.0.1:5000> for the basic HTML interface.

## Tests

Run all core and Flask API tests with:

```bash
python -m unittest discover -s tests -v
```

## HTTP API

All request bodies are JSON. Dates use `YYYY-MM-DD`.

```bash
curl -X POST http://127.0.0.1:5000/batches \
	-H 'Content-Type: application/json' \
	-d '{"batch_id":"B-1","medicine_name":"Paracetamol","expiry_date":"2026-10-01","quantity":20}'

curl http://127.0.0.1:5000/batches
curl -X POST http://127.0.0.1:5000/dispense \
	-H 'Content-Type: application/json' \
	-d '{"medicine_name":"Paracetamol","quantity":5}'
curl http://127.0.0.1:5000/stock/Paracetamol
curl 'http://127.0.0.1:5000/search?name=paracetamol'
curl 'http://127.0.0.1:5000/alerts?days=7'
```

Successful batch creation returns `201`. Invalid input returns `400`, duplicate
batches and insufficient stock return `409`, and successful reads or dispensing
return `200`.

## Core API

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

## Assessment demonstration

1. Run `python main.py` and open the browser interface.
2. Add two batches of the same medicine with different expiry dates.
3. Dispense part of the stock and show that the earlier expiry batch is used first.
4. Use the stock and search controls to show remaining availability.
5. Add a batch near its expiry and use the alerts control.
6. Run `python -m unittest discover -s tests -v` to show that the original 12
	core tests and the Flask API tests pass.

## Known limitations

- Data is held in memory and is lost when the process exits.
- Authentication, users, and audit history are not included.