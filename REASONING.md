# Implementation Reasoning

## Authentication

Authentication was added at the Flask boundary so existing inventory business
rules remain unchanged. SQLite stores a unique username and Werkzeug password
hash. Flask's signed session stores only the user ID and username. Health,
landing, authentication, and read-only APIs remain public; mutations require a
session.

## Pagination and sorting

Pagination is implemented in SQLite queries with `LIMIT` and `OFFSET`, rather
than slicing a fully loaded Python list. Sort fields are allowlisted before
being interpolated into SQL, while values remain parameterized. Existing
response keys are retained and pagination metadata is added alongside them.

## Landing page

The existing operations dashboard remains available at `/dashboard`. The root
route is now a public product landing page with login/register controls and
three clearly labeled future features. This separates product introduction from
authenticated inventory work without removing the dashboard.

## Testing process

The existing service, importer, notification, persistence, and API tests were
preserved. New API tests cover registration, duplicate users, invalid and valid
login, logout, protected mutations, pagination, sorting, invalid parameters,
search metadata, and public landing/dashboard access.

## Bugs and compatibility decisions

- Existing API arrays such as `batches` remain in their original response
  locations; metadata was added rather than replacing them.
- Tests use `:memory:` SQLite databases so persistent production data cannot
  leak between test cases.
- FEFO selection remains exclusively inside `InventoryService`; pagination and
  display sorting do not alter dispensing order.