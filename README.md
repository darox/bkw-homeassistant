# BKW Energy

A small Home Assistant integration for the BKW energy API. It makes one energy
sensor for each metering point, in kWh. BKW delays the meter data by about one
day. Thus the sensor gives the energy of the last complete day.

## Requirements

- Home Assistant version 2024.11.0 or later.
- A BKW account with a metering point.

## Install

1. In HACS, open the menu (the three dots) and select **Custom repositories**.
2. Add `https://github.com/darox/bkw-homeassistant`. Select the type
   **Integration**.
3. Download **BKW Energy**. Restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration** and select
   **BKW Energy**.
5. Enter the user name and the password of your BKW account.
6. If the account has more than one metering point, enter one metering point code.

## Security

The integration does not keep your password. After the first login it keeps an
OAuth refresh token in the config entry file. The file
`.storage/core.config_entries` contains this token. Protect that file in the
same way as `secrets.yaml`.

The integration asks the BKW login server for an offline login. An offline
refresh token has no short life. Thus a restart of Home Assistant and a long
downtime of Home Assistant do not ask for the password again. The integration
renews the login in the background, and each renewal holds the login session
open. The login server rotates the token at each renewal, and the integration
keeps the newest token.

An account without the right for an offline login gets a plain login token
instead. That token has a short life, about 30 minutes. The integration renews
it in the background. If Home Assistant stays off longer than the life of the
token, the integration asks for the password one time.

## Change the password

When you change the password on the BKW portal, Home Assistant shows a repair
message. Select the message and enter the new password. The integration then
keeps a new refresh token.

## Change the metering point

1. Go to **Settings -> Devices & services**.
2. Open the BKW Energy entry.
3. Select **Reconfigure** and enter the metering point code.

## 15 minute data

You can add the energy of the last complete day to the Energy dashboard.

1. Go to **Settings -> Devices & services**.
2. Open the BKW Energy entry.
3. Select **Reconfigure**.
4. Enable **Import the last complete day into the Energy dashboard and add a
   15 minute sensor**.
5. Select **Submit**.
6. Go to the Energy dashboard and add the new energy source of the account.

BKW sends the meter data of a day about one day late. The integration reads
the 15 minute records again at each poll and writes them into the statistics
of Home Assistant. Thus the Energy dashboard shows that day as if it were
yesterday. A poll reads a window of some days again, so a correction of the
meter data and a downtime of Home Assistant do not lose data.

Home Assistant keeps the long-term statistics of an external source as hour
values. Thus the resolution in the Energy dashboard is one hour, not 15
minutes.

The option also adds a sensor with the energy of the newest 15 minute
interval. Use that sensor for an automation. Do not add it to the Energy
dashboard: its values arrive with a delay of about one day.

## License

MIT. Refer to the file LICENSE.
