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

## Change the password

When you change the password on the BKW portal, Home Assistant shows a repair
message. Select the message and enter the new password. The integration then
keeps a new refresh token.

## Change the metering point

1. Go to **Settings -> Devices & services**.
2. Open the BKW Energy entry.
3. Select **Reconfigure** and enter the metering point code.

## License

MIT. Refer to the file LICENSE.
