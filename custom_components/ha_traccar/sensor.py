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

from .const import DOMAIN, LOGGER
from .coordinator import TraccarServerCoordinator
from .entity import TraccarServerEntity


# ============================================================
# 默认启用的常用 attribute（可根据自己设备补充/删减）
# ============================================================
DEFAULT_ENABLED_ATTRIBUTES: set[str] = {
    # Traccar 通用
    "motion", "ignition", "blocked", "alarm", "status",
    "sat", "satellites", "hdop", "pdop", "course",
    # 里程 / 计数
    "totalDistance", "distance", "odometer", "hours",
    # 电源 / 电池 / 油量
    "batteryLevel", "battery", "power", "charge",
    "fuel", "fuelLevel",
    # 传感器
    "rpm", "temp", "temperature", "adc1", "adc2",
    # IO
    "in1", "in2", "in3", "in4", "out1", "out2", "out3", "out4",
}


def _safe_slug(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).replace(" ", "_")


# ============================================================
# 平台初始化：固定实体 + 动态属性实体
# ============================================================
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TraccarServerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # 每个设备已发现过的 attribute key，避免重复创建
    tracked_attributes: dict[int, set[str]] = {}

    # ---------- 1. 固定实体 ----------
    entities: list = []
    for device_entry in coordinator.data.values():
        device = device_entry["device"]
        device_id = _safe_slug(device["name"])

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

    # ---------- 2. 动态属性发现 ----------
    def _discover_new_attributes() -> None:
        """扫描 position.attributes，为新出现的 key 创建实体。"""
        new_entities: list[TraccarAttributeSensor] = []
        for dev_data in coordinator.data.values():
            device = dev_data["device"]
            dev_pk = device["id"]
            attrs = (dev_data.get("position") or {}).get("attributes") or {}
            known = tracked_attributes.setdefault(dev_pk, set())
            for key in attrs.keys():
                if key in known:
                    continue
                known.add(key)
                sensor = TraccarAttributeSensor(coordinator, device, key)
                sensor.entity_id = (
                    f"sensor.{_safe_slug(device['name'])}_attr_{_safe_slug(key)}"
                )
                new_entities.append(sensor)

        if new_entities:
            LOGGER.info(
                "Discovered %d new attribute(s): %s",
                len(new_entities),
                [e._attribute_key for e in new_entities],
            )
            async_add_entities(new_entities)

    # 首次运行立即发现一遍
    _discover_new_attributes()

    # 之后每次 coordinator 推送都检查（新属性 → 新实体）
    entry.async_on_unload(
        coordinator.async_add_listener(_discover_new_attributes)
    )


# ============================================================
# 通用动态属性传感器
# ============================================================
class TraccarAttributeSensor(TraccarServerEntity, SensorEntity):
    """把 position.attributes 里的任意字段映射成一个传感器。"""

    _attr_icon = "mdi:tag-outline"

    def __init__(
        self,
        coordinator: TraccarServerCoordinator,
        device: dict,
        attribute_key: str,
    ) -> None:
        super().__init__(coordinator, device)
        self._attribute_key = attribute_key
        self._attr_unique_id = f"{self._device_id}_attr_{attribute_key}"
        self._attr_name = f"{device['name']} {attribute_key}"
        self._attr_entity_registry_enabled_default = (
            attribute_key in DEFAULT_ENABLED_ATTRIBUTES
        )

    @property
    def entity_id(self) -> str:
        return (
            f"sensor.{_safe_slug(self._device_name)}"
            f"_attr_{_safe_slug(self._attribute_key)}"
        )

    @entity_id.setter
    def entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id

    @property
    def native_value(self) -> Any:
        attrs = self.traccar_position.get("attributes") or {}
        value = attrs.get(self._attribute_key)
        # dict / list 不适合作为 state，放 attributes 里
        if isinstance(value, (dict, list)):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self.traccar_position.get("attributes") or {}
        value = attrs.get(self._attribute_key)
        result: dict[str, Any] = {"attribute_key": self._attribute_key}
        if isinstance(value, (dict, list)):
            result["raw_value"] = value
        return result


# ============================================================
# 以下为原有实体，保持不变
# ============================================================
class TraccarGeofenceSensor(TraccarServerEntity, SensorEntity):
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{self._device_id}_geofence"
        self._attr_name = f"{device['name']} 围栏"

    @property
    def entity_id(self):
        return f"sensor.{_safe_slug(self._device_name)}_geofence"

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
        return f"sensor.{_safe_slug(self._device_name)}_total_distance"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        attrs = self.traccar_position["attributes"]
        return round((attrs.get("totalDistance", 0) or 0) / 1000, 2)


class TraccarTripDistanceSensor(TraccarServerEntity, SensorEntity):
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
        return f"sensor.{_safe_slug(self._device_name)}_trip_distance"

    @entity_id.setter
    def entity_id(self, entity_id):
        self._entity_id = entity_id

    @property
    def native_value(self):
        attrs = self.traccar_position["attributes"]
        return round((attrs.get("distance", 0) or 0) / 1000, 2)


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
        return f"sensor.{_safe_slug(self._device_name)}_altitude"

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
        return f"sensor.{_safe_slug(self._device_name)}_address"

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