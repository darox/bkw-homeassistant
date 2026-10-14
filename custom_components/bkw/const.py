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
CONF_QUARTER_HOUR = "quarter_hour"

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

# The finest resolution of the BKW meter data. The extra sensor reads the
# energy of the newest 15 minute interval with this resolution.
QUARTER_HOUR_RESOLUTION = "PT15M"
QUARTER_HOUR = timedelta(minutes=15)

# The BKW meter data changes one time each day. A poll every 6 hours gives the
# same values as an hourly poll, with less load on the server.
SCAN_INTERVAL = timedelta(hours=6)

# The login server rotates the refresh token and gives it a short life. The
# response field `refresh_expires_in` holds that life, about 30 minutes. The
# data poll is every 6 hours, so the login must be renewed between the polls.
# Without the renewal, the login dies and Home Assistant asks for the password
# again at the next start.
LOGIN_RENEWAL_SHARE = 2  # renew the login after half of the remaining life
LOGIN_RENEWAL_MINIMUM = timedelta(minutes=1)
LOGIN_RENEWAL_MAXIMUM = timedelta(hours=6)
LOGIN_RENEWAL_FIRST = timedelta(minutes=5)
# A failed renewal. Try again soon, but not in a tight loop.
LOGIN_RENEWAL_RETRY = timedelta(minutes=5)
REFRESH_SKEW = timedelta(seconds=30)
GRANT_TIMEOUT = 20
REQUEST_TIMEOUT = 30
