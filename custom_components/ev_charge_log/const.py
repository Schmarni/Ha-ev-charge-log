"""Constants for EV Charge Log."""

from __future__ import annotations

DOMAIN = "ev_charge_log"

CONF_URL = "url"
CONF_FUEL_CONSUMPTION = "fuel_consumption"
CONF_FUEL_PRICE = "fuel_price"
CONF_FUEL_PRICE_ENTITY = "fuel_price_entity"
CONF_START_ODOMETER = "start_odometer"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_VEHICLE_FILTER = "vehicle_filter"

DEFAULT_URL = "http://49686a9f-evcc:7070"
DEFAULT_FUEL_CONSUMPTION = 6.0  # l/100 km
DEFAULT_FUEL_PRICE = 1.80  # currency per litre
DEFAULT_START_ODOMETER = 0
DEFAULT_SCAN_INTERVAL = 5  # minutes

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}"

SOURCE_EVCC = "evcc"
SOURCE_MANUAL = "manual"

SERVICE_ADD_SESSION = "add_session"
SERVICE_UPDATE_SESSION = "update_session"
SERVICE_DELETE_SESSION = "delete_session"
SERVICE_LIST_SESSIONS = "list_sessions"

ATTR_ENTRY_ID = "config_entry_id"
ATTR_SESSION_ID = "session_id"
ATTR_DATE = "date"
ATTR_LOCATION = "location"
ATTR_ENERGY = "energy"
ATTR_COST = "cost"
ATTR_ODOMETER = "odometer"
ATTR_DURATION = "duration"
ATTR_WAITING_TIME = "waiting_time"
ATTR_CHARGE_TYPE = "charge_type"
ATTR_NOTE = "note"

RECENT_SESSIONS = 25
