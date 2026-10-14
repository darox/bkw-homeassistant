"""Contract tests for the integration client against a synthetic BKW API."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import aiohttp

from custom_components.bkw import api, auth, const
from tests import fixture_server


class ApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = fixture_server.FixtureService()
        base = await self.service.start()
        self.patches = [
            patch.object(const, "API_BASE", base),
            patch.object(const, "TOKEN_URL", base + "/token"),
        ]
        for item in self.patches:
            item.start()
        self.session = aiohttp.ClientSession()
        self.auth = auth.BkwSession(
            self.session, fixture_server.USERNAME, fixture_server.PASSWORD
        )

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.service.stop()
        for item in self.patches:
            item.stop()

    async def test_timestamp_is_utc_milliseconds(self) -> None:
        value = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(api.timestamp(value), "2026-10-14T13:00:00.000Z")

    async def test_metering_points(self) -> None:
        self.assertEqual(
            await api.fetch_metering_points(self.session, self.auth), ["CH0001"]
        )

    async def test_consumption_returns_records_and_latest_value(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        stop = start + timedelta(days=1)
        records = await api.fetch_consumption(
            self.session, self.auth, start, stop, "CH0001"
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(api.latest_value(records), 2.5)

    async def test_empty_result_is_none_not_zero(self) -> None:
        self.assertIsNone(api.latest_value([]))

    async def test_quarter_hour_returns_one_record_each_interval(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        records = await api.fetch_consumption(
            self.session,
            self.auth,
            start,
            start + timedelta(hours=1),
            "CH0001",
            "PT15M",
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(api.latest_value(records), 1.0)

    async def test_latest_value_compares_real_timestamps(self) -> None:
        # Text order would pick the second record, but its real time is earlier.
        records = [
            ("2026-10-13T23:00:00.000Z", 1.0),
            ("2026-10-14T00:30:00.000+02:00", 2.0),
        ]
        self.assertEqual(api.latest_value(records), 1.0)

    async def test_latest_record_returns_the_newest_pair(self) -> None:
        records = [
            ("2026-10-13T23:00:00.000Z", 1.0),
            ("2026-10-14T00:30:00.000+02:00", 2.0),
        ]
        self.assertEqual(api.latest_record(records), records[0])
        self.assertIsNone(api.latest_record([]))

    async def test_wrong_password_raises_auth_rejected(self) -> None:
        bad = auth.BkwSession(self.session, fixture_server.USERNAME, "wrong")
        with self.assertRaises(auth.BkwAuthRejected) as caught:
            await api.fetch_metering_points(self.session, bad)
        self.assertEqual(caught.exception.code, "invalid_grant")

    async def test_session_from_a_refresh_token_does_not_send_the_password(
        self,
    ) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        self.assertEqual(
            await api.fetch_metering_points(self.session, stored), ["CH0001"]
        )
        self.assertEqual(self.service.password_grants, 0)
        self.assertEqual(self.service.issued, 1)

    async def test_dead_refresh_token_without_a_password_is_rejected(self) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        self.service.reject_refresh = True
        with self.assertRaises(auth.BkwAuthRejected):
            await api.fetch_metering_points(self.session, stored)

    async def test_dead_refresh_token_falls_back_to_the_password(self) -> None:
        both = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            fixture_server.PASSWORD,
            fixture_server.REFRESH_TOKEN,
        )
        self.service.reject_refresh = True
        self.assertEqual(
            await api.fetch_metering_points(self.session, both), ["CH0001"]
        )
        self.assertEqual(self.service.password_grants, 1)

    async def test_expired_access_token_is_renewed_with_the_refresh_token(
        self,
    ) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        self.service.access_ttl = 5.0
        # The 30 second skew refreshes an access token that lives 5 seconds.
        await api.fetch_metering_points(self.session, stored)
        await api.fetch_metering_points(self.session, stored)
        self.assertEqual(self.service.issued, 2)
        self.assertEqual(self.service.password_grants, 0)

    async def test_concurrent_calls_share_one_grant(self) -> None:
        fresh = auth.BkwSession(
            self.session, fixture_server.USERNAME, fixture_server.PASSWORD
        )
        tokens = await asyncio.gather(*(fresh.token() for _ in range(3)))
        self.assertEqual(len(set(tokens)), 1)
        self.assertEqual(self.service.password_grants, 1)

    async def test_rejected_access_token_is_renewed_one_time(self) -> None:
        await api.fetch_metering_points(self.session, self.auth)
        self.service.reject_next_access = True
        self.assertEqual(
            await api.fetch_metering_points(self.session, self.auth), ["CH0001"]
        )
        self.assertEqual(self.service.issued, 2)

    async def test_upstream_failure_raises_cannot_connect(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        with self.assertRaises(api.BkwCannotConnect) as caught:
            await api.fetch_consumption(
                self.session, self.auth, start, start + timedelta(days=1), "BOOM"
            )
        self.assertEqual(caught.exception.status, 502)

    async def test_bad_json_body_is_an_invalid_response(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        with self.assertRaises(api.BkwInvalidResponse):
            await api.fetch_consumption(
                self.session, self.auth, start, start + timedelta(days=1), "BADJSON"
            )

    async def test_redirect_is_not_followed(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        with self.assertRaises(api.BkwCannotConnect) as caught:
            await api.fetch_consumption(
                self.session, self.auth, start, start + timedelta(days=1), "REDIRECT"
            )
        self.assertEqual(caught.exception.status, 302)

    async def test_reversed_bounds_are_rejected_locally(self) -> None:
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        with self.assertRaises(api.BkwInvalidResponse):
            await api.fetch_consumption(
                self.session, self.auth, start, start, "CH0001"
            )

    async def test_unreachable_api_raises_cannot_connect(self) -> None:
        with patch.object(const, "API_BASE", "http://127.0.0.1:1"):
            with self.assertRaises(api.BkwCannotConnect) as caught:
                await api.fetch_metering_points(self.session, self.auth)
        self.assertIsNone(caught.exception.status)

    async def test_unreachable_token_server_is_transient(self) -> None:
        with patch.object(const, "TOKEN_URL", "http://127.0.0.1:1/token"):
            with self.assertRaises(auth.BkwAuthTransient):
                await api.fetch_metering_points(self.session, self.auth)

    async def test_unknown_status_is_transient_not_rejected(self) -> None:
        # A 404 of the token endpoint must not look like a wrong password.
        with patch.object(const, "TOKEN_URL", self.service.base + "/missing"):
            with self.assertRaises(auth.BkwAuthTransient):
                await api.fetch_metering_points(self.session, self.auth)

    async def test_a_rotated_refresh_token_is_reported(self) -> None:
        seen: list[str] = []
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
            on_refresh_token=seen.append,
        )
        await api.fetch_metering_points(self.session, stored)
        self.assertEqual(seen, ["refresh-2"])
        self.assertEqual(stored.refresh_token, "refresh-2")

    async def test_an_unchanged_refresh_token_is_not_reported(self) -> None:
        self.service.rotate_refresh = False
        seen: list[str] = []
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
            on_refresh_token=seen.append,
        )
        await api.fetch_metering_points(self.session, stored)
        self.assertEqual(seen, [])

    async def test_the_old_refresh_token_dies_after_a_rotation(self) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        await api.fetch_metering_points(self.session, stored)
        # A new start with the token of the config entry. The server rotated
        # the token, so the old one is dead.
        restart = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        with self.assertRaises(auth.BkwAuthRejected):
            await api.fetch_metering_points(self.session, restart)
        # A new start with the newest token works.
        newest = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=stored.refresh_token,
        )
        self.assertEqual(
            await api.fetch_metering_points(self.session, newest), ["CH0001"]
        )

    async def test_an_idle_refresh_token_dies(self) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        await api.fetch_metering_points(self.session, stored)
        self.service.expire_refresh()
        restart = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=stored.refresh_token,
        )
        with self.assertRaises(auth.BkwAuthRejected):
            await api.fetch_metering_points(self.session, restart)

    async def test_a_forced_call_renews_the_login(self) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        first = await stored.token()
        self.assertEqual(await stored.token(), first)
        self.assertEqual(self.service.issued, 1)
        self.assertNotEqual(await stored.token(force=True), first)
        self.assertEqual(self.service.issued, 2)

    async def test_the_newest_refresh_token_is_kept_after_a_renewal(self) -> None:
        stored = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=fixture_server.REFRESH_TOKEN,
        )
        self.service.access_ttl = 1.0
        await stored.token()
        first = stored.refresh_token
        await stored.token()
        self.assertNotEqual(stored.refresh_token, first)
        self.assertEqual(stored.refresh_token, self.service.refresh_token)

    async def test_the_login_asks_for_an_offline_token(self) -> None:
        await self.auth.token()
        self.assertEqual(self.service.password_scope, const.SCOPE)
        # An offline token has no stated end of life.
        self.assertIsNone(self.auth.refresh_expires_at)

    async def test_the_offline_login_keeps_its_long_life_at_a_renewal(self) -> None:
        await self.auth.token()
        await self.auth.token(force=True)
        self.assertEqual(self.auth.refresh_token, "refresh-2")
        self.assertIsNone(self.auth.refresh_expires_at)

    async def test_the_login_uses_the_plain_scope_without_the_role(self) -> None:
        self.service.allow_offline = False
        await self.auth.token()
        # The server refused the offline scope, and the code asked again with
        # the plain scope.
        self.assertEqual(self.service.password_grants, 2)
        self.assertEqual(self.service.password_scope, const.SCOPE_PLAIN)
        self.assertIsNotNone(self.auth.refresh_expires_at)

    async def test_a_wrong_password_does_not_ask_again_with_another_scope(
        self,
    ) -> None:
        wrong = auth.BkwSession(self.session, fixture_server.USERNAME, "wrong")
        with self.assertRaises(auth.BkwAuthRejected):
            await wrong.token()
        self.assertEqual(self.service.password_grants, 1)

    async def test_an_offline_login_survives_a_long_downtime(self) -> None:
        await self.auth.token()
        first = self.auth.refresh_token
        # A downtime of the client. The idle life of the offline token is
        # much longer than the idle life of a plain token.
        self.service.downtime(timedelta(days=1))
        restart = auth.BkwSession(
            self.session,
            fixture_server.USERNAME,
            refresh_token=first,
        )
        self.assertEqual(
            await api.fetch_metering_points(self.session, restart), ["CH0001"]
        )


if __name__ == "__main__":
    unittest.main()
