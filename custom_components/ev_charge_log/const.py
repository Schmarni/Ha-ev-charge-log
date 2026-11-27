"""Constants for EV Charge Log."""

from __future__ import annotations

DOMAIN = "ev_charge_log"

CONF_URL = "url"
CONF_USE_EVCC = "use_evcc"
CONF_NAME = "name"
CONF_VEHICLES = "vehicles"
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_WLTP_CONSUMPTION = "wltp_consumption"
CONF_ODOMETER_ENTITY = "odometer_entity"
CONF_FUEL_TYPE = "fuel_type"
CONF_FUEL_CONSUMPTION = "fuel_consumption"
CONF_FUEL_PRICE = "fuel_price"
CONF_FUEL_PRICE_ENTITY = "fuel_price_entity"
CONF_GRID_CO2 = "grid_co2"
CONF_START_ODOMETER = "start_odometer"
CONF_SCAN_INTERVAL = "scan_interval"
# legacy (v1): comma separated vehicle name parts
CONF_VEHICLE_FILTER = "vehicle_filter"

DEFAULT_URL = "http://49686a9f-evcc:7070"
DEFAULT_NAME = "EV Ladebuch"
DEFAULT_FUEL_TYPE = "diesel"
DEFAULT_FUEL_CONSUMPTION = 6.0  # l/100 km
DEFAULT_FUEL_PRICE = 1.80  # currency per litre
DEFAULT_GRID_CO2 = 380  # g CO2 / kWh, German grid mix (approx.)
DEFAULT_START_ODOMETER = 0
DEFAULT_SCAN_INTERVAL = 5  # minutes

FUEL_TYPES = ["diesel", "petrol"]
# kg CO2 per litre burned (tank-to-wheel)
FUEL_CO2_KG_PER_L = {"diesel": 2.65, "petrol": 2.37}

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}"

SOURCE_EVCC = "evcc"
SOURCE_MANUAL = "manual"

SERVICE_ADD_SESSION = "add_session"
SERVICE_UPDATE_SESSION = "update_session"
SERVICE_DELETE_SESSION = "delete_session"
SERVICE_LIST_SESSIONS = "list_sessions"
SERVICE_START_TIMER = "start_timer"
SERVICE_STOP_TIMER = "stop_timer"
SERVICE_CANCEL_TIMER = "cancel_timer"

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
