# ica — command reference

Unofficial CLI for ICA Handla. **JSON-first**: successful commands print one
JSON object on **stdout** as `{"ok": true, "data": <payload>}`. Failures print
one JSON object on **stderr** (`error`, `code`, optional `http_status`/`details`)
and exit non-zero.

Entry point after install: `ica` (`pyproject.toml` → `[project.scripts]`), or run
the module directly with `python -m ica_handla`.

## Global options

| Option | Effect |
|--------|--------|
| `-v`, `--verbose` | debug logging on stderr (safe for JSON stdout) |
| `-f`, `--format` | `json` (default) or `text` where a text renderer exists |

Both may be given before the command or after it (`ica -f text lists ls` or
`ica lists ls -f text`).

## Environment variables

| Variable | Role |
|----------|------|
| `ICA_USER` | personnummer for `login` (else prompted) |
| `ICA_PASS` | password for `login` (else prompted, no echo) |
| `ICA_HANDLA_CONFIG_DIR` | config dir (default `~/.config/ica-handla`, honours `XDG_CONFIG_HOME`) |
| `ICA_HANDLA_STATE_PATH` | full path to `state.json` |

`state.json` holds the DCR client + access/refresh tokens (mode 600). The
password is never written.

## Authentication

| Command | Description |
|---------|-------------|
| `ica login [-u USER] [-p PASS]` | register device (DCR) + log in (html-form password flow) |
| `ica register` | DCR only; prints the ephemeral `client_id` |
| `ica refresh` | refresh the access token |
| `ica token [--access-token T] [--refresh-token R]` | import a captured token, skip login |
| `ica logout` | revoke + clear `state.json` |
| `ica whoami` | signed-in customer (`customerservice/v1/customer`) |

## Shopping lists

| Command | Description |
|---------|-------------|
| `ica lists ls` | all lists (`text`: `id  title  (N rows)`) |
| `ica lists show [LIST]` | one list + rows (`LIST` = id or title; default first) |
| `ica lists create TITLE` | create a list |
| `ica lists delete LIST` | delete a list |

## Items

`LIST` is an id or title (default: first list). An item is matched by `offlineId`,
then exact name, then substring; ambiguous matches error with candidates.

| Command | Description |
|---------|-------------|
| `ica item add LINE [--list LIST]` | add; `LINE` e.g. `2 st mjölk`, `1,5 l mellanmjölk` |
| `ica item edit ITEM [--list LIST] [--name N] [--qty Q] [--unit U] [--check\|--uncheck]` | change fields |
| `ica item check ITEM [--list LIST]` | mark bought (strikethrough) |
| `ica item uncheck ITEM [--list LIST]` | unmark |
| `ica item remove ITEM [--list LIST]` | delete the row |

Mutations go through the app's offline-sync endpoint
`shoppinglistservice/v1/shoppinglists/{id}/sync` (`createdRows` / `changedRows` /
`deletedRows` keyed by `offlineId`).

## Suggestions

| Command | Description |
|---------|-------------|
| `ica suggest common [--list LIST]` | common articles (per-list if given) |
| `ica suggest most-purchased` | most purchased items |
| `ica suggest lists` | suggested lists |

## Recipes

| Command | Description |
|---------|-------------|
| `ica recipe get ID` | one recipe |
| `ica recipe random` | random recipes |
| `ica recipe categories` | categories |
| `ica recipe favorites` | favorite recipes |
| `ica recipe search QUERY` | free-text search (handles `202` warm-up with backoff) |

## Stores / offers / bonus

| Command | Description |
|---------|-------------|
| `ica stores ls` | all stores |
| `ica stores get ID` | store detail |
| `ica stores favorites` | favorite stores |
| `ica offers STORE_ID` | discounts for a store |
| `ica bonus current` | current loyalty bonus |
| `ica bonus transactions` | bonus transactions |

## Handla online shop (cart + product search)

These talk to the **web storefront** `handlaprivatkund.ica.se` — a different
backend from everything above. Product **search** is anonymous (needs only a
store id); the **cart** needs a browser session cookie + CSRF token.

Store id resolution: `--store-id` → `ICA_HANDLA_STORE_ID` → saved (`handla login`).
Cookie resolution: `ICA_HANDLA_COOKIE` → saved (`handla login`).

| Command | Description |
|---------|-------------|
| `ica handla login --cookie 'H' [--store-id N]` | save a Cookie header (from browser DevTools) + default store |
| `ica handla login --browser [--store-id N]` | open a browser, log in, auto-capture the cookie (needs `pip install '.[browser]'` + `playwright install chromium`) |
| `ica handla status` | show whether a cookie/store/csrf is saved |
| `ica handla logout` | clear saved Handla cookie/store/csrf |
| `ica product search QUERY [--store-id N] [--raw]` | anonymous search; compact `{name, productId, unitOfMeasure?}` unless `--raw` |
| `ica product lookup UPC` | barcode lookup via the **mobile** API (needs `ica login`) |
| `ica cart show [--store-id N]` | the active cart |
| `ica cart add PRODUCT_ID [-d N] [--store-id N]` | add / increase by delta (default +1) |
| `ica cart remove PRODUCT_ID [-d N] [--store-id N]` | decrease by N (default 1); line drops at 0 |

**Getting the cookie:** either let the CLI do it —
`ica handla login --browser --store-id <id>` opens a headed browser (Playwright;
`pip install '.[browser]' && playwright install chromium`), you log in, and the
Handla cookies are captured automatically — or do it by hand: sign in to
`handlaprivatkund.ica.se`, open DevTools → Network → any request to that host →
copy the full `Cookie` request header, then
`ica handla login --cookie '<paste>' --store-id <id>`. The CLI
scrapes the CSRF token from the store page automatically and caches it (refreshing
on a 403). Cart mutations send `productId` + a signed `quantity` **delta** to
`.../api/cart/v1/carts/active/apply-quantity`.

`code` values specific to Handla: `missing_handla_store_id` (usage),
`missing_handla_web_session` (auth), `handla_csrf_failed` (upstream).

## Output & exit codes

Success (stdout): `{"ok": true, "data": <payload>}`
Failure (stderr): `{"error": "...", "code": "...", "http_status"?: int, "details"?: {...}}`

| Exit | Meaning | Example `code` |
|------|---------|----------------|
| 0 | success | — |
| 1 | usage | `usage`, `ambiguous_list`, `ambiguous_row` |
| 2 | auth | `missing_credentials`, `auth_failed` |
| 3 | upstream | `upstream_http`, `not_found`, `list_not_found`, `row_not_found` |
| 4 | network | `network_error` |

## MCP server

`ica-handla-mcp` (or `python -m ica_handla.mcp_server`) runs a Model Context
Protocol server over stdio, exposing the operations above as tools for LLM
clients. Install with `pip install '.[mcp]'`; authenticate out-of-band with
`ica login` (and `ica handla login` for cart tools). See the README for client
config. The server reads `state.json` and never handles your password.

## Source map

| Area | Module |
|------|--------|
| constants / endpoints (from APK) | `ica_handla/const.py` |
| Curity auth (DCR, login, refresh) | `ica_handla/auth.py`, `ica_handla/pkce.py` |
| HTTP + error mapping | `ica_handla/http.py`, `ica_handla/errors.py` |
| API services | `ica_handla/api.py` |
| line parsing / resolution | `ica_handla/models.py` |
| CLI wiring | `ica_handla/cli.py` |
| config / state | `ica_handla/config.py` |
