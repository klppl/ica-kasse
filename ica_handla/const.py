"""Constants recovered from the ICA Handla app (se.ica.handla 4.79.1, PROD).

Everything here was reverse-engineered from the shipped APK: the Curity OAuth
configuration, the dynamic-client-registration bootstrap credentials, and the
full set of Retrofit endpoint paths the app talks to.
"""
from __future__ import annotations

from typing import Final

APP_VERSION: Final = "4.79.1"
ANDROID_RELEASE: Final = "14"
USER_AGENT: Final = f"ICA Appen {APP_VERSION} (Android {ANDROID_RELEASE})"

# --- Identity / Curity (ims.icagruppen.se) ---------------------------------
IMS_BASE: Final = "https://ims.icagruppen.se/"
TOKEN_ENDPOINT: Final = "oauth/v2/token"
AUTHORIZE_ENDPOINT: Final = "oauth/v2/authorize"
REVOKE_ENDPOINT: Final = "oauth/v2/revoke"
REGISTER_ENDPOINT: Final = "register"

# Dynamic Client Registration bootstrap (NetworkModule)
DCR_CLIENT_ID: Final = "ica-app-dcr-registration"
DCR_CLIENT_SECRET: Final = "uxLHTBvZ-Z2fV-SbrHl1E-tz7vB3jQFrwAdSLlbVMMu1rxDdvJU0s8KGu9d1wLS4"
DCR_SOFTWARE_ID: Final = "dcr-ica-app-template"
DCR_SCOPE: Final = "dcr"
DCR_GRANT_TYPE: Final = "client_credentials"

# Authorization-code + PKCE flow (Curity.kt)
AUTH_SCOPE: Final = "icaappen openid ica_app_stammis2"
REDIRECT_URI: Final = "icacurity://app"
REDIRECT_SCHEME: Final = "icacurity"
TOKEN_GRANT_TYPE: Final = "authorization_code"
REFRESH_GRANT_TYPE: Final = "refresh_token"
TOKEN_RESPONSE_TYPE: Final = "token"

# acr values for the Curity authenticators (LoginMethod.kt)
ACR_PASSWORD: Final = "urn:se:curity:authentication:html-form:IcaCustomers"
ACR_BANKID: Final = "urn:se:curity:authentication:bankid:icase-bankid-qr"
ACR_EMAIL: Final = "urn:se:curity:authentication:email:icase-email"

# --- Application API (apimgw-pub.ica.se gateway) ----------------------------
# The app's old host handla.api.ica.se no longer resolves; the same service
# paths are served from the API gateway under /sverige/digx/mobile/.
API_BASE: Final = "https://apimgw-pub.ica.se/sverige/digx/mobile/"

# ServerDateFormat.kt
DATE_FMT: Final = "%Y-%m-%dT%H:%M:%SZ"

# parse_summary default (ICA article tree root)
DEFAULT_ARTICLE_GROUP_ID: Final = 12

# Units the app/line-parser understands.
UNITS: Final = ("st", "förp", "kg", "hg", "g", "l", "dl", "cl", "ml", "msk", "tsk", "krm")

# --- Endpoint paths (relative to API_BASE), grouped by service -------------
# shoppinglistservice/v1
EP_LISTS: Final = "shoppinglistservice/v1/shoppinglists"
EP_LIST_SYNC: Final = "shoppinglistservice/v1/shoppinglists/{id}/sync"
EP_LISTS_DELETE: Final = "shoppinglistservice/v1/shoppinglists/delete"
EP_COMMON: Final = "shoppinglistservice/v1/shoppinglists/common"
EP_LIST_COMMON: Final = "shoppinglistservice/v1/shoppinglists/{id}/common"
EP_MOST_PURCHASED: Final = "shoppinglistservice/v1/mostpurchaseditems"
EP_BASEITEMS: Final = "shoppinglistservice/v1/baseitems"
EP_ARTICLES: Final = "shoppinglistservice/v1/articles"
EP_ARTICLE_GROUPS: Final = "shoppinglistservice/v1/articles/articlegroups"
EP_STORE_ARTICLE_GROUPS: Final = "shoppinglistservice/v1/articles/storearticlegroups"
EP_STORE_ARTICLE_GROUPS_QUERY: Final = "shoppinglistservice/v1/articles/storearticlegroups/query"
EP_SUGGESTIONS: Final = "shoppinglistservice/v1/suggestions/lists"
EP_SMART_REMINDERS: Final = "shoppinglistservice/v1/smartreminders"

# recipeservice/v1
EP_RECIPE: Final = "recipeservice/v1/recipes/{id}"
EP_RECIPE_RANDOM: Final = "recipeservice/v1/recipes/random"
EP_RECIPE_CATEGORIES: Final = "recipeservice/v1/categories"
EP_RECIPE_SEARCH_FILTERS: Final = "recipeservice/v1/search/filters"
EP_RECIPE_SEARCH: Final = "recipeservice/v1/search/recipes/byfilter"
EP_RECIPE_SEARCH_BYIDS: Final = "recipeservice/v1/search/recipes/byids"
EP_RECIPE_FAVORITES: Final = "recipeservice/v1/favorites"
EP_RECIPE_FAVORITES_DELETE: Final = "recipeservice/v1/favorites/delete"
EP_RECIPE_FOLDERS: Final = "recipeservice/v1/folders/all"

# offerservice/v1
EP_OFFERS: Final = "offerservice/v1/offersdiscounts/{storeId}"
EP_OFFERS_SEARCH: Final = "offerservice/v1/offers/search"
EP_USER_DISCOUNTS: Final = "offerservice/v1/discounts"
EP_OFFERS_RECIPES: Final = "offerservice/v1/offers/{storeId}/recipes"

# storeservice/v1
EP_STORES: Final = "storeservice/v1/stores"
EP_STORE: Final = "storeservice/v1/stores/{id}"
EP_STORE_FAVORITES: Final = "storeservice/v1/favorites"
EP_STORE_OPENING_HOURS: Final = "storeservice/v1/stores/openinghours"

# productservice / bonusservice / customerservice
EP_PRODUCT: Final = "productservice/v1/product/{upc}"
EP_BONUS_CURRENT: Final = "bonusservice/v1/bonus/current"
EP_BONUS_TRANSACTIONS: Final = "bonusservice/v1/bonus/transactions"
EP_CUSTOMER: Final = "customerservice/v1/customer"
EP_CUSTOMER_PREFERENCES: Final = "customerservice/v1/customer/preferences"
EP_CONFIG_ANDROID: Final = "configservice/v1/config/android"
