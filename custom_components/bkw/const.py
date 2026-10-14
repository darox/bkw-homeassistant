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
# The login server accepts the scope `offline_access`. An offline refresh
# token has no short life, so a restart and a long downtime of Home Assistant
# do not ask for the password again. An account without the `offline_access`
# role gets the plain scope instead.
SCOPE = "openid offline_access"
SCOPE_PLAIN = "openid"

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

# The BKW meter data of a day arrives about one day late. The integration
# writes the 15 minute records into the statistics of Home Assistant, so the
# Energy dashboard shows that day as if it were yesterday. Each poll reads a
# window of some days again, so a correction of the meter data and a downtime
# of Home Assistant do not lose data.
STATISTICS_WINDOW = timedelta(days=3)

# The BKW meter data changes one time each day. A poll every 6 hours gives the
# same values as an hourly poll, with less load on the server.
SCAN_INTERVAL = timedelta(hours=6)

# The login server rotates the refresh token at each renewal. The response
# field `refresh_expires_in` holds the life of the token: about 30 minutes
# for a plain login, and 0 (no stated life) for an offline login. The data
# poll is every 6 hours, so a plain login must be renewed between the polls.
# Without the renewal, the login dies and Home Assistant asks for the
# password again at the next start.
LOGIN_RENEWAL_SHARE = 2  # renew the login after half of the remaining life
LOGIN_RENEWAL_MINIMUM = timedelta(minutes=1)
LOGIN_RENEWAL_MAXIMUM = timedelta(hours=6)
LOGIN_RENEWAL_FIRST = timedelta(minutes=5)
# A failed renewal. Try again soon, but not in a tight loop.
LOGIN_RENEWAL_RETRY = timedelta(minutes=5)
REFRESH_SKEW = timedelta(seconds=30)
GRANT_TIMEOUT = 20
REQUEST_TIMEOUT = 30
