# ICA Handla mobile API — reference

Unofficial notes on the API used by the `se.ica.handla` Android app (4.79.1),
taken from the decompiled app (Retrofit interfaces) and checked against the live
service on 2026-10-24. **✔** = called successfully with a real account during
that check; **APK** = read from the app only, not exercised.

> For interoperability with your own account. Not affiliated with ICA.

## Hosts

| What | URL |
|------|-----|
| Auth (Curity) | `https://ims.icagruppen.se/` |
| App API (current) | `https://apimgw-pub.ica.se/sverige/digx/mobile/` (`EnvironmentV2.PROD`) |
| App API (retired) | `https://handla.api.ica.se/api/` — no longer resolves |
| Other envs in the app | `…/sverige/digx/vnext/mobile/`, `https://apimgw-pub-ver.ica.se/sverige/digx/mobile/` |
| Web shop (separate backend) | `https://handlaprivatkund.ica.se` — session cookie + CSRF, see `handla.py` |

All paths below are relative to the app API base.

## Authentication (OAuth2 / OIDC, PKCE, dynamic client registration)

1. `POST oauth/v2/token` with the app's bootstrap client, `grant_type=client_credentials`,
   `scope=dcr` → registration token.
2. `POST register` (`Bearer <registration token>`, `{"software_id": "dcr-ica-app-template"}`)
   → ephemeral `client_id` / `client_secret`.
3. `GET oauth/v2/authorize` (PKCE S256, `acr=urn:se:curity:authentication:html-form:IcaCustomers`)
   → HTML login form; POST `userName` (personnummer) + `password`.
   Success: 302 to `icacurity://app?code=…` (a custom scheme: do not auto-follow).
   Bad credentials: HTTP 400 with the form re-rendered ("Fel personnummer och/eller lösenord").
4. `POST oauth/v2/token` (`authorization_code` + `code_verifier`) → access + refresh token.
5. Refresh: `POST oauth/v2/token` (`refresh_token`). Revoke: `POST oauth/v2/revoke`.

Gotchas:
- The authorize/login requests must send an **HTML `Accept`** header. With
  `Accept: application/json` the authorize endpoint returns an empty `{}`.
- Never resubmit the login form after a 400; repeated attempts can lock the account.

## Request headers

`Authorization: Bearer <access token>`, `User-Agent` and `x-user-agent` =
`ICA Appen 4.79.1 (Android <release>)`, `X-Correlation-ID` and `X-Request-ID` = one
fresh UUID per request.

## Gateway quirks (all verified)

- **Lists are addressed by `offlineId`** (the UUID string), not the numeric `id`,
  in `…/{id}/sync` (numeric → HTTP 500) and in `shoppinglists/delete` (numeric → 400).
- **`recipeservice/v1/search/recipes/byfilter` is GET** with query params; POST → 405.
- **Many endpoints take `?api-version=2`.** For `offers/search` it changes the
  response shape (`{"storeOffers": [...]}` vs. a bare list), so always send it.
- 202 Accepted on search endpoints means "warming up": retry with backoff.
- Gateway errors are JSON `{"code","type","message","description"}`; backend
  errors are RFC 9110 problem JSON. A bare 451 `URI invalid` means the path matched no API context.

## Endpoints

### Customer — `customerservice/v1`
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `customer` | name, `customerId`, `personId` (national id!), consent flags |
| ✔ | GET | `customer/preferences` | |
| APK | GET | `customer/token` | validate customer token |
| APK | POST | `customer/session/start`, `customer/session/verify` | |
| APK | GET | `digitalid/qrcode` | |
| APK | POST/DELETE | `push/device`, `push/device/{muId}` | push registration |
| APK | POST | `deviceinfo`, `feedback` | |

### Shopping lists — `shoppinglistservice/v1`
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `shoppinglists` | `{"shoppingLists": [{id, offlineId, title, rows[]}]}` |
| ✔ | POST | `shoppinglists` | create: `{offlineId, title, commentText, sortingStore, rows: [], latestChange}` |
| ✔ | POST | `shoppinglists/{offlineId}/sync` | body below |
| ✔ | POST | `shoppinglists/delete` | body: `["<offlineId>"]` |
| ✔ | GET | `shoppinglists/common`, `shoppinglists/{id}/common` | common articles |
| ✔ | GET | `mostpurchaseditems`, `baseitems`, `suggestions/lists` | |
| APK | POST | `baseitems` | create favourites |
| APK | GET | `smartreminders` | |
| APK | GET | `articles`, `articles/articlegroups`, `articles/storearticlegroups` | cached 1 h in app |
| APK | POST | `articles/storearticlegroups/query` | |

Sync body:
```json
{
  "changedShoppingListProperties": {"sortingStore": null, "title": null,
                                    "commentText": null, "latestChange": "2026-10-24T06:30:10Z"},
  "createdRows": [{"offlineId": "<uuid>", "productName": "mjölk", "quantity": 2.0, "unit": "st",
                   "isStrikedOver": false, "internalOrder": 0, "articleGroupId": 12,
                   "latestChange": "2026-10-24T06:30:10Z"}],
  "changedRows": [], "deletedRows": ["<row offlineId>"]
}
```
Timestamps use `%Y-%m-%dT%H:%M:%SZ`. Editing or striking over a row = same row `offlineId` in `changedRows`.

### Offers — `offerservice/v1`
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `offersdiscounts/{storeId}` | `{"discounts": [], "offers": [...]}`; `?api-version=2` also fine |
| ✔ | POST | `offers/search?api-version=2` | body `{"offerIds": ["2006022026"], "storeIds": [1066]}` → `{"storeOffers": [{"storeId", "offers": [...]}]}` |
| ✔ | POST | `discounts?api-version=2` | body `{"storeIds": [1066]}` → `{"stores": [...]}` (personal discounts) |
| APK | GET | `offers/{storeId}/recipe/{recipeId}` | offers for a recipe |
| APK | POST | `offers/{storeId}/recipes` | body: recipe ids |
| APK | GET/POST | `stampcard/rewards/{id}`, `stampcards/{accountNumber}`, `…/{id}/activate/{acct}`, `…/{id}/optout/{acct}` | stamp cards |

### Recipes — `recipeservice/v1` (all `?api-version=2`)
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `search/recipes/byfilter` | query: `phrase`, `recordsPerPage`, `pageNumber`, `filters`, `sorting` — the term must be in `phrase`; `freeText` is silently ignored and returns all recipes |
| ✔ | GET | `search/filters`, `categories`, `recipes/random`, `favorites` | |
| APK | GET | `recipes/{id}`, `recipes/{id}/comments`, `recipes/ratings` | |
| APK | POST | `recipes/{id}/comments`, `recipes/{id}/rating`, `favorites`, `favorites/delete`, `search/recipes/byids` | |
| APK | GET/POST/PUT/DELETE | `folders`, `folders/all`, `folders/{id}`, `folders/{id}/items`, `…/recipes/{rid}`, `folders/{id}/share` | recipe folders |

### Stores — `storeservice/v1`
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `stores`, `stores/{id}` | |
| ✔ | GET | `favorites` | `{"favoriteStores": [1066, …], "visitedStores": [...]}` (ids, not objects) |
| APK | PUT/DELETE | `favorites`, `favorites/{storeId}` | |
| APK | GET | `stores/openinghours`, `filters`, `onboarding`, `stores/{id}/map`, `stores/{id}/map/settings` | |

### Bonus, product, cards, content
| | Method | Path | Notes |
|--|--|--|--|
| ✔ | GET | `bonusservice/v1/bonus/current`, `bonus/transactions` | |
| APK | GET | `bonus/sixmonthshistory`, `bonus/purchase-summary`, `bonus/compensationcheck/{storeId}` | |
| ✔ | GET | `productservice/v1/product/{upc}` | barcode lookup |
| APK | GET/POST | `cardservice/v1/card/cardaccounts`, `payment/{pay,approve,cancel,status,ticket}`, `swish/{initialize,status/{id}}` | payments, `?api-version=2` — not implemented, deliberately |
| APK | GET | `configservice/v1/config/android` | feature flags |
| APK | GET | `contentservice/v1/content/{advertbanners,campaign-cards,loyalty-cards,partneroffers/all,partneroffers/carousel,systemmessages/android}` | |
| APK | GET | `contentservice/v1/public-content/{forced-logout-messages,recallbanners,systemmessages/android}` | no login |
| APK | GET | `e11/public-access-token` | anonymous token |
