"""Binary sensor for ha_traccar geofence."""
from __future__ import annotations

import re

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TraccarServerCoordinator
from .entity import TraccarServerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TraccarServerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device_entry in coordinator.data.values():
        device = device_entry["device"]
        device_id = re.sub(r"[^\w\s]", "", device["name"].lower()).replace(" ", "_")
        sensor = TraccarInGeofenceBinarySensor(coordinator, device)
        sensor.entity_id = f"binary_sensor.{device_id}_in_geofence"
        entities.append(sensor)

    async_add_entities(entities)


class TraccarInGeofenceBinarySensor(TraccarServerEntity, BinarySensorEntity):
    """是否在任意围栏内。"""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: TraccarServerCoordinator, device: dict) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_in_geofence"
        self._attr_name = f"{device['name']} 在围栏内"

    @property
    def entity_id(self) -> str:
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"binary_sensor.{device_id}_in_geofence"

    @entity_id.setter
    def entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id

    @property
    def is_on(self) -> bool:
        return len(self.traccar_geofences) > 0

    @property
    def extra_state_attributes(self):
        geofences = self.traccar_geofences
        return {
            "geofence": ", ".join(gf["name"] for gf in geofences) or "不在围栏",
            "geofence_list": [gf["name"] for gf in geofences],
            "geofence_count": len(geofences),
        }