"""Constants for the ha_traccar integration."""
from logging import getLogger

DOMAIN = "ha_traccar"
LOGGER = getLogger(__package__)

ATTR_ADDRESS = "address"
ATTR_ALTITUDE = "altitude"
ATTR_CATEGORY = "category"
ATTR_GEOFENCE = "geofence"
ATTR_MOTION = "motion"
ATTR_SPEED = "speed"
ATTR_STATUS = "status"
ATTR_TRACKER = "tracker"
ATTR_TRACCAR_ID = "traccar_id"

SERVICE_UPDATE_ADDRESS = "update_address"