"""Sensors for ha_traccar."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
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

        geofence = TraccarGeofenceSensor(coordinator, device)
        geofence.entity_id = f"sensor.{device_id}_geofence"
        entities.append(geofence)

        total_distance = TraccarTotalDistanceSensor(coordinator, device)
        total_distance.entity_id = f"sensor.{device_id}_total_distance"
        entities.append(total_distance)

        trip_distance = TraccarTripDistanceSensor(coordinator, device)
        trip_distance.entity_id = f"sensor.{device_id}_trip_distance"
        entities.append(trip_distance)

        altitude = TraccarAltitudeSensor(coordinator, device)
        altitude.entity_id = f"sensor.{device_id}_altitude"
        entities.append(altitude)

        address = TraccarAddressSensor(coordinator, device)
        address.entity_id = f"sensor.{device_id}_address"
        entities.append(address)

    async_add_entities(entities)


class TraccarGeofenceSensor(TraccarServerEntity, SensorEntity):
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_geofence"
        self._attr_name = f"{device['name']} 围栏"

    @property
    def entity_id(self):
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"sensor.{device_id}_geofence"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        geofences = self.traccar_geofences
        if not geofences:
            return "不在围栏"
        return ", ".join(gf["name"] for gf in geofences)

    @property
    def extra_state_attributes(self):
        geofences = self.traccar_geofences
        return {
            "geofence_list": [gf["name"] for gf in geofences],
            "geofence_count": len(geofences),
            "in_geofence": len(geofences) > 0,
        }


class TraccarTotalDistanceSensor(TraccarServerEntity, SensorEntity):
    """车机总里程 (km)。"""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_total_distance"
        self._attr_name = f"{device['name']} 车机里程"

    @property
    def entity_id(self):
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"sensor.{device_id}_total_distance"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        attrs = self.traccar_position["attributes"]
        total_m = attrs.get("totalDistance", 0) or 0
        return round(total_m / 1000, 2)


class TraccarTripDistanceSensor(TraccarServerEntity, SensorEntity):
    """本次里程 (km)。"""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:map-marker-distance"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_trip_distance"
        self._attr_name = f"{device['name']} 本次里程"

    @property
    def entity_id(self):
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"sensor.{device_id}_trip_distance"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        attrs = self.traccar_position["attributes"]
        trip_m = attrs.get("distance", 0) or 0
        return round(trip_m / 1000, 2)


class TraccarAltitudeSensor(TraccarServerEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_icon = "mdi:altimeter"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_altitude"
        self._attr_name = f"{device['name']} 海拔"

    @property
    def entity_id(self):
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"sensor.{device_id}_altitude"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        return round(self.traccar_position["altitude"], 1)


class TraccarAddressSensor(TraccarServerEntity, SensorEntity):
    _attr_icon = "mdi:map-marker-outline"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_address"
        self._attr_name = f"{device['name']} 地址"

    @property
    def entity_id(self):
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"sensor.{device_id}_address"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        pos = self.traccar_position
        return (
            pos.get("address")
            or self.coordinator.get_address_override(self.device_id)
        )