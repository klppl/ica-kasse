# ica-handla

Unofficial Python client **and** CLI for ICA Handla (Sweden): shopping lists,
recipes, offers, stores, products and loyalty bonus. Reverse-engineered from the
`se.ica.handla` Android app (4.79.1). **JSON-first** output for scripting and agents.

> Unofficial and **not affiliated with or endorsed by ICA**. "ICA" and related
> marks belong to their owners. You are responsible for complying with ICA's
> terms. Endpoints and secrets are baked into the app and may change or be
> revoked at any time. Use only with your own account.

## Two things in this repo

| | What | Use it when |
|---|------|-------------|
| **`ica_handla/`** | Full installable package + `ica` CLI (this README) | You want the complete tool |
| **`API.md`** | Endpoint and auth reference (from the app + live checks) | You are extending or debugging the client |
| **`ica_client.py`** | Single-file minimal client (lists + add/edit/remove) | You want one file to drop in |

## How it works

ICA authenticates through **Curity** (OAuth2/OIDC) at `ims.icagruppen.se` using
PKCE and **Dynamic Client Registration** — no device attestation, which is what
makes a pure-Python client possible:

1. **Bootstrap** `POST /oauth/v2/token` (`client_credentials`, scope `dcr`) with the
   app's embedded DCR client → one-off registration token.
2. **Register** `POST /register` (`Bearer`, `{"software_id": "dcr-ica-app-template"}`)
   → an ephemeral `client_id`/`secret` for this "device".
3. **Authorize** `GET /oauth/v2/authorize` (PKCE S256, `acr` = html-form password)
   → submit personnummer + password → redirect `icacurity://app?code=…`.
4. **Token** `POST /oauth/v2/token` (`authorization_code` + `code_verifier`) →
   access + refresh token.

API calls go to `https://apimgw-pub.ica.se/sverige/digx/mobile/` with `Authorization: Bearer …`
plus `User-Agent`/`x-user-agent` and `X-Correlation-ID`/`X-Request-ID`. No gateway
subscription key is required.

## Install

```bash
pip install .            # from this directory
# or, for development + tests:
pip install -e ".[dev]"
```

This installs the `ica` command. Only hard dependency is `requests`. For
browser-based Handla login (`ica handla login --browser`), add the optional
extra:

```bash
pip install ".[browser]"
playwright install chromium
```

## Quickstart

```bash
export ICA_USER=ÅÅÅÅMMDDXXXX     # your personnummer
export ICA_PASS=...              # your password (or omit to be prompted)

ica login                        # register device + log in (stores tokens)
ica lists ls -f text             # your lists
ica item add "2 st mjölk"        # add to the first list
ica item add "Bröd" --list Hemma # add to a list by name
ica item check "Mjölk"           # strike through
ica item remove "Bröd"
ica product lookup 7310865004703 # look up a product by barcode (mobile API)
ica recipe search "köttbullar"

# Handla online shop (web storefront; needs a browser cookie)
ica handla login --browser --store-id 1004261           # auto-capture via Playwright
# ...or paste a cookie by hand:
ica handla login --cookie '<Cookie header from DevTools>' --store-id 1004261
ica product search "mjölk"       # anonymous, per store
ica cart add <productId> -d 2    # add 2 to the cart
ica cart show
ica cart remove <productId>      # decrease by 1
```

The `handla` / `cart` / `product search` commands use the **web storefront**
`handlaprivatkund.ica.se`, a separate backend (browser cookie + CSRF) from the
mobile API everything else uses. See [CLI.md](./CLI.md#handla-online-shop-cart--product-search).

See **[CLI.md](./CLI.md)** for the full command reference, output contract, exit
codes, and config paths.

## As a library

```python
from ica_handla import Authenticator, IcaApi, State

api = IcaApi(Authenticator(State.load()))
api.auth.login("ÅÅÅÅMMDDXXXX", "…")     # once; tokens persist
for sl in api.lists():
    print(sl["id"], sl["title"])
api.add_item(None, "1 l mellanmjölk")    # None = first list
```

## If automated login fails

Curity's hosted login page can add consent/OTP/BankID steps the scripted form-walk
doesn't handle. Capture a `refresh_token` (or `access_token`) from a real session
and import it instead:

```bash
ica token --refresh-token "<captured>"
ica refresh
ica lists ls
```

## MCP server (use it from Claude or other LLM clients)

The package ships an optional [Model Context Protocol](https://modelcontextprotocol.io)
server that exposes the operations above as **tools**, so an MCP client (Claude
Desktop, Claude Code, etc.) can manage your lists/cart in conversation.

```bash
pip install ".[mcp]"
ica login                 # authenticate once in a terminal (tools never see your password)
ica-handla-mcp            # starts the stdio server (usually launched by the client)
```

Register it with a client — e.g. Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ica-handla": { "command": "ica-handla-mcp" }
  }
}
```

Then ask things like *"add milk and bread to my shopping list"* or *"what are my
most purchased items?"*. Tools include `list_shopping_lists`, `show_list`,
`add_item`, `edit_item`, `check_item`, `remove_item`, `search_recipes`,
`store_offers`, `product_lookup`, and the Handla `handla_product_search` /
`handla_cart_*` family (run `ica login` and `ica handla login` first). The server
reads your saved session from `state.json` and **never handles your password** —
authentication stays in the CLI. Works with both v1 (`FastMCP`) and v2
(`MCPServer`) of the MCP Python SDK.

## Security

- Tokens live in `~/.config/ica-handla/state.json` (mode 600). The **password is
  never persisted** — only the resulting tokens.
- Don't commit `state.json` or share tokens/personnummer.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

[The Lagom License](./LICENSE) — not too much, not too little. Copyright (c) 2026
klppl. Keep the notice, include the license, keep it lagom.
