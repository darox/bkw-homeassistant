"""Constants for the BKW Energy integration.

The values here come from the BKW web application, which uses the Keycloak
realm `oneportal` and the public OAuth client `mybkw-webapp`.
"""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "bkw"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_METERING_POINT = "metering_point"

TOKEN_URL = (
    "https://login.portal-services.ch/auth/realms/oneportal"
    "/protocol/openid-connect/token"
)
CLIENT_ID = "mybkw-webapp"
SCOPE = "openid"

API_BASE = "https://api-energy-monitoring.bkw.ch"
METERING_POINTS_PATH = "/api/meteringpoint"
METERING_DATA_PATH = "/api/metering-data"
DATA_TYPE = "PRODUCTION_BKW"

RESOLUTIONS = ("PT15M", "P1D", "P1M", "P1Y")
DEFAULT_RESOLUTION = "P1D"

# The BKW meter data changes one time each day. A poll every 6 hours gives the
# same values as an hourly poll, with fewer logins and less load on the server.
SCAN_INTERVAL = timedelta(hours=6)
REFRESH_SKEW = timedelta(seconds=30)
GRANT_TIMEOUT = 20
REQUEST_TIMEOUT = 30
