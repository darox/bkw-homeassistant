# BKW Energy: a minimal Home Assistant integration

This directory holds a small Home Assistant integration for the BKW energy API
at `https://api-energy-monitoring.bkw.ch`. The integration speaks to the BKW
API directly. The Go project
[bkw-backend](https://github.com/darox/bkw-backend) gives the API contract.
That project is not released, so this integration holds all the logic. The
integration does not use MCP. The integration does not use Prometheus.

## What the integration does

The integration sends three requests:

1. A password grant to the BKW login server. The login server is the Keycloak
   realm `oneportal`.
2. `GET /api/meteringpoint` returns the metering points of the account.
3. `GET /api/metering-data` returns the energy records for a time range.

The integration makes one sensor for each metering point. The sensor gives the
energy that the meter measured since local midnight. The unit is kWh.

## Files

```text
custom_components/bkw/
  __init__.py       config entry setup and unload
  api.py            BKW REST client, no Home Assistant imports
  auth.py           OAuth password grant and token renewal, no Home Assistant imports
  config_flow.py    one-step user config flow
  const.py          domain, endpoints, and defaults
  manifest.json     integration metadata
  sensor.py         the sensor platform
  strings.json      English text for the config flow
  translations/en.json
tests/
  fixture_server.py   a synthetic BKW API for the documented contract
  test_api.py         client tests against the synthetic API
  test_integration.py integration tests inside a real Home Assistant
```

## Install

The repository is private. HACS cannot install a private repository. Copy the
code into your Home Assistant configuration directory.

```sh
git clone https://github.com/darox/bkw-homeassistant.git /tmp/bkw
cp -r /tmp/bkw/custom_components/bkw <config>/custom_components/
```

Then do these steps:

1. Restart Home Assistant.
2. Go to **Settings -> Devices & services -> Add integration**.
3. Select **BKW Energy**.
4. Enter the user name and the password of your BKW account.
5. If the account has more than one metering point, enter one metering point
   code. If the account has one metering point, leave the field empty.

For an update, run `git pull` in the clone and copy the directory again.

## Credentials

The integration needs the user name and the password of your BKW account. Home
Assistant keeps the password in the config entry file. That file is not
encrypted. Protect the Home Assistant configuration directory.

## Entity

The integration makes one sensor for each metering point.

| Property | Value |
| --- | --- |
| Device class | `energy` |
| State class | `total` |
| Unit of measurement | `kWh` |
| Value | Energy since local midnight |
| Update interval | 1 hour |

The `last_reset` attribute is local midnight. An empty answer gives the state
`unknown`, not `0`. Use the sensor in the Energy dashboard.

## Why this is the minimum

Home Assistant gives three levels for this task.

**Level 0: no custom code.** The built-in `rest` integration reads one JSON
endpoint. But the BKW API needs an OAuth token, and the `rest` integration
cannot renew a token. A manual token expires, so the level 0 sensor stops. Thus
level 0 cannot work without attention for a long time.

**Level 1: one component.** This directory. Nine small files give a device, a
config flow, and one sensor for each metering point. The component does the
OAuth password grant and the token renewal. This level is the minimum for
unattended use.

**Level 2: a full integration.** Add a data update coordinator, config options,
a reauth flow, diagnostics, and more translations.

`config_flow.py` and `sensor.py` use the same `api.py` and `auth.py` modules.
Those two modules have no Home Assistant imports, so a plain test can use them.

## Tests

The tests use a synthetic BKW API. The tests never use real BKW credentials.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install "homeassistant==2026.10.1" \
  pytest-homeassistant-custom-component
./verify.sh
```

`test_api.py` starts a loopback API and sends real HTTP requests to it. The
tests cover the password grant, the token renewal after HTTP 401, the wrong
password, and the empty answer. `test_integration.py` loads the integration in
a real Home Assistant instance:

- The config flow makes one entry for a one-point account.
- The config flow asks for a code when the account has two points.
- The sensor gives the newest consumption value.
- A full config entry reads the synthetic API and gives the state `2.5`.

The tests need loopback sockets. The sandbox of an agent must permit them.

## Limits

- The integration reads one account. It has one config entry per account.
- The sensor shows a daily value. It is not a lifetime total.
- The integration renews the token after HTTP 401 one time. It has no other
  retry and no backoff. A failed request makes the sensor unavailable until the
  next interval.
- The integration has no reauth flow. Change the password in the config entry
  after a password change.
- The API is not public. BKW can change it at any time.
