"""The ha_traccar integration."""
from __future__ import annotations

from aiohttp import CookieJar
from pytraccar import ApiClient
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN, LOGGER, SERVICE_UPDATE_ADDRESS
from .coordinator import TraccarServerCoordinator

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER]

SERVICE_UPDATE_ADDRESS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha_traccar from a config entry."""
    client_session = async_create_clientsession(
        hass,
        cookie_jar=CookieJar(
            unsafe=not entry.data[CONF_SSL] or not entry.data[CONF_VERIFY_SSL]
        ),
    )
    coordinator = TraccarServerCoordinator(
        hass=hass,
        client=ApiClient(
            client_session=client_session,
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            ssl=entry.data[CONF_SSL],
            verify_ssl=entry.data[CONF_VERIFY_SSL],
        ),
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        ssl=entry.data[CONF_SSL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ---------- 注册服务（只注册一次）----------
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE_ADDRESS):

        async def async_handle_update_address(call: ServiceCall) -> None:
            """自动化调用：请求一次逆地理编码并刷新实体。"""
            entity_id: str = call.data["entity_id"]

            entity_registry = er.async_get(hass)
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry is None:
                LOGGER.warning("Entity %s not found in registry", entity_id)
                return

            unique_id = entity_entry.unique_id

            for coord in hass.data.get(DOMAIN, {}).values():
                for dev_id, dev_data in coord.data.items():
                    if dev_data["device"]["uniqueId"] == unique_id:
                        await coord.async_request_address(dev_id)
                        return

            LOGGER.warning(
                "Device with unique_id %s not found in any coordinator", unique_id
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_ADDRESS,
            async_handle_update_address,
            schema=SERVICE_UPDATE_ADDRESS_SCHEMA,
        )

    entry.async_create_background_task(
        hass=hass,
        target=coordinator.subscribe(),
        name="ha_traccar subscription",
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE_ADDRESS)
    return unload_ok