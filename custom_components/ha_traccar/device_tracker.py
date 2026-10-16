"""Support for ha_traccar device tracking."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_ADDRESS,
    ATTR_ALTITUDE,
    ATTR_CATEGORY,
    ATTR_GEOFENCE,
    ATTR_MOTION,
    ATTR_SPEED,
    ATTR_TRACCAR_ID,
    ATTR_TRACKER,
    DOMAIN,
)
from .coordinator import TraccarServerCoordinator
from .entity import TraccarServerEntity


# ============================================================
# WGS84 (GPS) -> GCJ02 (高德) 坐标转换
# ============================================================
_EARTH_RADIUS = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    if lng < 72.004 or lng > 137.8347:
        return True
    if lat < 0.8293 or lat > 55.8271:
        return True
    return False


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)
    ) * 2.0 / 3.0
    ret += (
        160.0 * math.sin(y / 12.0 * math.pi)
        + 320 * math.sin(y * math.pi / 30.0)
    ) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)
    ) * 2.0 / 3.0
    ret += (
        150.0 * math.sin(x / 12.0 * math.pi)
        + 300.0 * math.sin(x / 30.0 * math.pi)
    ) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """将 GPS 原始坐标 (WGS84) 转换为高德坐标 (GCJ02)。"""
    if _out_of_china(lng, lat):
        return lng, lat

    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)

    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / (
        (_EARTH_RADIUS * (1 - _EE)) / (magic * sqrtmagic) * math.pi
    )
    dlng = (dlng * 180.0) / (
        _EARTH_RADIUS / sqrtmagic * math.cos(radlat) * math.pi
    )

    return lng + dlng, lat + dlat


# ============================================================
# 时间处理
# ============================================================
_CST = timezone(timedelta(hours=8))


def _parse_time(value: Any) -> datetime | None:
    """把 Traccar 时间字符串解析成带时区的 datetime。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _format_time_cst(value: Any) -> str | None:
    """把 Traccar 时间字符串转换为中国时区字符串 YYYY-MM-DD HH:MM:SS。"""
    dt = _parse_time(value)
    if dt is None:
        return None
    return dt.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 平台初始化
# ============================================================
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker entities."""
    coordinator: TraccarServerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device_entry in coordinator.data.values():
        device = device_entry["device"]
        device_id = re.sub(r"[^\w\s]", "", device["name"].lower()).replace(" ", "_")

        tracker = TraccarServerDeviceTracker(coordinator, device)
        tracker.entity_id = f"device_tracker.{device_id}"
        entities.append(tracker)

    async_add_entities(entities)


# ============================================================
# 设备跟踪器实体
# ============================================================
class TraccarServerDeviceTracker(TraccarServerEntity, TrackerEntity):
    """Represent a tracked device."""

    _attr_force_update = True

    def __init__(self, coordinator: TraccarServerCoordinator, device: dict) -> None:
        super().__init__(coordinator, device)
        self._attr_name = device["name"]
        self._attr_unique_id = self._device_id

    @property
    def entity_id(self) -> str:
        device_id = re.sub(r"[^\w\s]", "", self._device_name.lower()).replace(" ", "_")
        return f"device_tracker.{device_id}"

    @entity_id.setter
    def entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific attributes."""
        pos = self.traccar_position
        attrs = pos["attributes"]

        # ---- 围栏处理：可能同时处于多个围栏 ----
        all_geofences = self.traccar_geofences
        geofence_names = [gf["name"] for gf in all_geofences]
        in_geofence = len(geofence_names) > 0
        # 显示：多个用逗号分隔；没有则显示"不在围栏"
        geofence_display = ", ".join(geofence_names) if geofence_names else "不在围栏"

        # WGS84 -> GCJ02
        gaode_lon, gaode_lat = wgs84_to_gcj02(pos["longitude"], pos["latitude"])

        # 最后位置时间
        last_time = (
            pos.get("fixTime")
            or pos.get("deviceTime")
            or pos.get("serverTime")
        )

        # 基于位置时间判断在线
        is_online = False
        last_dt = _parse_time(last_time)
        if last_dt is not None:
            is_online = (datetime.now(timezone.utc) - last_dt).total_seconds() < 300
        else:
            is_online = self.traccar_device["status"] == "online"

        # 里程：米 -> 公里
        total_distance_m = attrs.get("totalDistance", 0) or 0

        return {
            # --- 地址 ---
            ATTR_ADDRESS: pos.get("address")
            or self.coordinator.get_address_override(self.device_id),

            # --- 基础信息 ---
            ATTR_CATEGORY: self.traccar_device["category"],
            ATTR_MOTION: attrs.get("motion", False),
            ATTR_TRACCAR_ID: self.traccar_device["id"],
            ATTR_TRACKER: DOMAIN,

            # --- 围栏 ---
            ATTR_GEOFENCE: geofence_display,           # "围栏A, 围栏B" 或 "不在围栏"
            "in_geofence": in_geofence,                # 布尔：是否在任意围栏内
            "geofence_list": geofence_names,           # 列表：所有围栏名称
            "geofence_count": len(geofence_names),     # 数量

            # --- 网络状态 / 速度 / 海拔 / 里程 ---
            "online": is_online,
            ATTR_SPEED: round(pos["speed"] * 3.6, 1),
            ATTR_ALTITUDE: round(pos["altitude"], 1),
            "total_distance": round(total_distance_m / 1000, 2),

            # --- 高德坐标 & 最后位置时间 ---
            "gaode_lat": gaode_lat,
            "gaode_lon": gaode_lon,
            "time": _format_time_cst(last_time),
        }

    @property
    def latitude(self) -> float:
        return self.traccar_position["latitude"]

    @property
    def longitude(self) -> float:
        return self.traccar_position["longitude"]

    @property
    def location_accuracy(self) -> float:
        return self.traccar_position["accuracy"]

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS