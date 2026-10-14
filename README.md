# BKW Energy

A minimal Home Assistant integration for the BKW energy API. It makes one energy
sensor for each metering point, in kWh. BKW delays the meter data by about one day.

## Install

1. In HACS, open the menu (the three dots) and select **Custom repositories**.
2. Add `https://github.com/darox/bkw-homeassistant`. Select the type
   **Integration**.
3. Download **BKW Energy**. Restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration** and select
   **BKW Energy**. Enter the user name and the password of your BKW account. If
   the account has more than one metering point, enter one metering point code.

## Warning

Home Assistant keeps your password in the config entry file in clear text.
Protect that file in the same way as `secrets.yaml`.
