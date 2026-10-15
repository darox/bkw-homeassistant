# BKW Energy

A small Home Assistant integration for the BKW energy API. It makes one energy
sensor for the metering point that you select. The sensor shows the energy of
the last complete day in kWh. BKW sends this data about one day late.

## Energy dashboard

The integration writes each complete day into the statistics of Home Assistant
with the timestamp of that day. Add the statistic `<name> consumption` (id
`bkw:<metering point code>`) as the grid consumption of the Energy dashboard.

The sensor changes its state when the BKW data of the completed day arrives.
That is about one day after the day of the data.

## Requirements

- Home Assistant version 2024.11.0 or later.
- A BKW account with a metering point.

## Install

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/darox/bkw-homeassistant` and select the type
   **Integration**.
3. Download **BKW Energy**. Restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration** and select
   **BKW Energy**.
5. Enter the user name and the password of your BKW account.
6. If your account has more than one metering point, enter one metering point
   code.

## Security

The integration does not keep your password. It keeps an OAuth refresh token in
the config entry file. Protect `.storage/core.config_entries` in the same way
as `secrets.yaml`.

The integration asks the BKW login server for an offline login. It renews the
login in the background and keeps the newest token. A restart of Home
Assistant does not ask for the password again.

If BKW does not give an offline login, the integration uses a short-lived
token. If Home Assistant stays off longer than the life of that token, the
integration asks for the password one time.

## Change the password

If you change the password on the BKW portal, Home Assistant shows a repair
message. Select the message and enter the new password.

## Change the metering point

1. Go to **Settings -> Devices & services**.
2. Open the BKW Energy entry.
3. Select **Reconfigure** and enter the metering point code.

## License

MIT. Refer to the file LICENSE.
