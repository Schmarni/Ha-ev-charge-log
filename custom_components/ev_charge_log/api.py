"""Minimal evcc REST client."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class EvccApiError(Exception):
    """Raised when evcc cannot be reached or returns garbage."""


class EvccApi:
    """Read charging sessions and state from evcc."""

    def __init__(self, session: aiohttp.ClientSession, url: str) -> None:
        self._session = session
        self._url = url.rstrip("/")

    async def _get(self, path: str) -> Any:
        try:
            async with asyncio.timeout(20):
                resp = await self._session.get(f"{self._url}{path}")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EvccApiError(f"{path}: {err}") from err
        # older evcc versions wrap payloads in {"result": ...}
        if isinstance(data, dict) and "result" in data and len(data) == 1:
            data = data["result"]
        return data

    async def sessions(self) -> list[dict[str, Any]]:
        data = await self._get("/api/sessions")
        if not isinstance(data, list):
            raise EvccApiError("unexpected /api/sessions payload")
        return data

    async def state(self) -> dict[str, Any]:
        data = await self._get("/api/state")
        if not isinstance(data, dict):
            raise EvccApiError("unexpected /api/state payload")
        return data

    async def vehicles(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Return (configured vehicles, vehicle titles seen in sessions)."""
        state = await self.state()
        configured = [
            {"name": key, "title": v.get("title") or key, "capacity": v.get("capacity")}
            for key, v in (state.get("vehicles") or {}).items()
            if isinstance(v, dict)
        ]
        seen: list[str] = []
        for s in await self.sessions():
            title = s.get("vehicle")
            if title and title not in seen:
                seen.append(title)
        return configured, seen

    async def odometers(self) -> list[tuple[str | None, float]]:
        """(vehicle title, odometer) of every loadpoint with a car that reports one."""
        state = await self.state()
        return [
            (lp.get("vehicleTitle"), float(lp["vehicleOdometer"]))
            for lp in state.get("loadpoints") or []
            if isinstance(lp.get("vehicleOdometer"), (int, float)) and lp["vehicleOdometer"] > 0
        ]
