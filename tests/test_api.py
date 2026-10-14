"""Contract tests for the integration client against a synthetic BKW API."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.bkw import auth, const
from custom_components.bkw import api
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

    async def test_wrong_password_raises_auth_rejected(self) -> None:
        bad = auth.BkwSession(self.session, fixture_server.USERNAME, "wrong")
        with self.assertRaises(auth.BkwAuthRejected) as caught:
            await api.fetch_metering_points(self.session, bad)
        self.assertEqual(caught.exception.code, "invalid_grant")

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


if __name__ == "__main__":
    unittest.main()
