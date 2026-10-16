"""Data update coordinator for ha_traccar."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, TypedDict

import aiohttp
from pytraccar import (
    ApiClient,
    DeviceModel,
    GeofenceModel,
    PositionModel,
    SubscriptionData,
    TraccarException,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER
from .helpers import get_device, get_first_geofence, get_geofences


class TraccarServerCoordinatorDataDevice(TypedDict):
    """ha_traccar coordinator data."""

    device: DeviceModel
    geofence: GeofenceModel | None
    geofences: list[GeofenceModel]
    position: PositionModel


TraccarServerCoordinatorData = dict[int, TraccarServerCoordinatorDataDevice]


class TraccarServerCoordinator(DataUpdateCoordinator[TraccarServerCoordinatorData]):
    """Class to manage fetching ha_traccar data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ApiClient,
        *,
        host: str,
        port: str,
        ssl: bool,
        username: str,
        password: str,
    ) -> None:
        """Initialize global ha_traccar data updater."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client
        self._host = host
        self._port = port
        self._ssl = ssl
        self._username = username
        self._password = password
        self._geofences: list[GeofenceModel] = []
        self._should_log_subscription_error: bool = True
        self._address_overrides: dict[int, str] = {}

    async def _async_update_data(self) -> TraccarServerCoordinatorData:
        """Fetch data from ha_traccar."""
        LOGGER.debug("Updating device data")
        data: TraccarServerCoordinatorData = {}
        try:
            devices, positions, geofences = await asyncio.gather(
                self.client.get_devices(),
                self.client.get_positions(),
                self.client.get_geofences(),
            )
        except TraccarException as ex:
            raise UpdateFailed(f"Error while updating device data: {ex}") from ex

        if TYPE_CHECKING:
            assert isinstance(devices, list)
            assert isinstance(positions, list)
            assert isinstance(geofences, list)

        self._geofences = geofences

        for position in positions:
            if (device := get_device(position["deviceId"], devices)) is None:
                continue

            device_geofences = get_geofences(
                geofences,
                position["geofenceIds"] or [],
            )

            data[device["id"]] = {
                "device": device,
                "geofence": device_geofences[0] if device_geofences else None,
                "geofences": device_geofences,
                "position": position,
            }

        return data

    async def handle_subscription_data(self, data: SubscriptionData) -> None:
        """Handle subscription data."""
        self.logger.debug("Received subscription data: %s", data)
        self._should_log_subscription_error = True
        update_devices = set()

        for device in data.get("devices") or []:
            device_id = device["id"]
            if device_id not in self.data:
                continue
            self.data[device_id]["device"] = device
            update_devices.add(device_id)

        for position in data.get("positions") or []:
            device_id = position["deviceId"]
            if device_id not in self.data:
                continue
            device_geofences = get_geofences(
                self._geofences,
                position["geofenceIds"] or [],
            )
            self.data[device_id]["position"] = position
            self.data[device_id]["geofence"] = (
                device_geofences[0] if device_geofences else None
            )
            self.data[device_id]["geofences"] = device_geofences
            update_devices.add(device_id)

        for device_id in update_devices:
            async_dispatcher_send(self.hass, f"{DOMAIN}_{device_id}")

    async def subscribe(self) -> None:
        """Subscribe to events."""
        try:
            await self.client.subscribe(self.handle_subscription_data)
        except TraccarException as ex:
            if self._should_log_subscription_error:
                self._should_log_subscription_error = False
                LOGGER.error("Error while subscribing to Traccar: %s", ex)
            await asyncio.sleep(10)
            await self.subscribe()

    # ------------------------------------------------------------------
    # 按需更新地址
    # ------------------------------------------------------------------
    def get_address_override(self, device_id: int) -> str | None:
        """返回手动请求得到的地址（如有）。"""
        return self._address_overrides.get(device_id)

    async def async_request_address(self, device_id: int) -> None:
        """主动向 Traccar 请求一次逆地理编码。"""
        if device_id not in self.data:
            LOGGER.warning("Device %s not in coordinator data", device_id)
            return

        pos = self.data[device_id]["position"]
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None or lon is None:
            LOGGER.warning("Device %s has no coordinates", device_id)
            return

        protocol = "https" if self._ssl else "http"
        url = f"{protocol}://{self._host}:{self._port}/api/server/geocode"
        params = {"latitude": str(lat), "longitude": str(lon)}

        session = async_get_clientsession(self.hass)
        auth = aiohttp.BasicAuth(self._username, self._password)

        LOGGER.debug("Requesting geocode: GET %s params=%s", url, params)

        try:
            async with session.get(
                url,
                params=params,
                auth=auth,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.text()
                LOGGER.debug(
                    "Geocode response status=%s body=%s",
                    resp.status, body[:500],
                )

                if resp.status == 204:
                    LOGGER.warning(
                        "Traccar geocode returned 204 (no address) for device %s",
                        device_id,
                    )
                    return
                if resp.status != 200:
                    LOGGER.error(
                        "Geocode API returned %s for device %s: %s",
                        resp.status, device_id, body[:200],
                    )
                    return

                address: str | None = None
                content_type = resp.headers.get("Content-Type", "")
                if "json" in content_type:
                    try:
                        data = json.loads(body)
                        if isinstance(data, dict):
                            address = data.get("address")
                        elif isinstance(data, str):
                            address = data
                    except json.JSONDecodeError:
                        address = body.strip() or None
                else:
                    address = body.strip() or None

        except asyncio.TimeoutError:
            LOGGER.error("Timeout requesting address for device %s", device_id)
            return
        except aiohttp.ClientError as ex:
            LOGGER.error(
                "Failed to request address for device %s: %s", device_id, ex
            )
            return

        if not address:
            LOGGER.warning("Empty address returned for device %s", device_id)
            return

        self._address_overrides[device_id] = address
        async_dispatcher_send(self.hass, f"{DOMAIN}_{device_id}")
        LOGGER.debug("Address updated for device %s: %s", device_id, address)