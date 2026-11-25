from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "ev_charge_log"
URL = "http://evcc:7070"

SESSIONS = [
    {"id": 1, "created": "2026-09-05T13:00:36.553983143+02:00", "finished": "2026-09-05T14:00:00+02:00",
     "loadpoint": "Carport", "vehicle": "Elroq", "odometer": 1000, "chargedEnergy": 20.0,
     "chargeDuration": 3600000000000, "solarPercentage": 50.0, "price": 4.0},
    {"id": 2, "created": "2026-10-05T13:00:36+02:00", "finished": "0001-01-01T00:00:00Z",
     "loadpoint": "Carport", "vehicle": "Elroq", "odometer": 1500, "chargedEnergy": 10.0,
     "chargeDuration": None, "solarPercentage": None, "price": None},
]
STATE = {"loadpoints": [{"vehicleOdometer": 2000}]}


def mock_evcc(aioclient_mock):
    aioclient_mock.get(f"{URL}/api/sessions", json=SESSIONS)
    aioclient_mock.get(f"{URL}/api/state", json=STATE)


async def test_config_flow(hass: HomeAssistant, aioclient_mock):
    mock_evcc(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "url": URL + "/", "fuel_consumption": 6.0, "fuel_price": 1.8, "start_odometer": 0, "scan_interval": 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": URL}
    assert result["options"]["fuel_price"] == 1.8


async def test_setup_and_services(hass: HomeAssistant, aioclient_mock, hass_client):
    hass.config.currency = "EUR"
    mock_evcc(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, title="EV Ladebuch", data={"url": URL}, options={
        "fuel_consumption": 6.0, "fuel_price": 1.8, "start_odometer": 0, "scan_interval": 5})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    def val(name):
        st = hass.states.get(f"sensor.ev_ladebuch_{name}")
        assert st is not None, (name, sorted(hass.states.async_entity_ids("sensor")))
        return st

    assert float(val("energy_total").state) == 30.0
    # cost: 4 + 10 kWh * 0.20 estimated
    assert float(val("cost_total").state) == 6.0
    assert val("cost_total").attributes["unit_of_measurement"] == "EUR"
    assert float(val("distance_driven").state) == 2000
    # fuel 2000km*6l*1.8 = 216
    assert float(val("fuel_car_cost_comparison").state) == 216.0
    assert float(val("savings_vs_fuel_car").state) == 210.0
    assert float(val("average_consumption").state) == 1.5

    resp = await hass.services.async_call(DOMAIN, "add_session", {
        "location": "Lidl", "energy": 23.44, "cost": 10.32, "date": "2026-10-10 12:00:00",
        "waiting_time": 5, "duration": 25, "charge_type": "DC", "odometer": 2000}, blocking=True, return_response=True)
    sid = resp["session"]["id"]
    assert resp["session"]["odometer"] == 2000
    await hass.async_block_till_done()
    assert float(val("energy_public").state) == 23.44
    assert float(val("charging_sessions").state) == 3
    assert float(val("waiting_time_public").state) == 5
    assert float(val("average_price_public").state) == round(10.32 / 23.44, 4)

    resp = await hass.services.async_call(DOMAIN, "list_sessions", {}, blocking=True, return_response=True)
    assert len(resp["sessions"]) == 3
    assert resp["odometer"] == 2000

    # back-dated session gets no odometer, a "now" session does
    from homeassistant.util import dt as dt_util
    r1 = await hass.services.async_call(DOMAIN, "add_session", {"location": "Old", "energy": 5, "cost": 2,
        "date": "2026-01-01 10:00:00"}, blocking=True, return_response=True)
    assert r1["session"]["odometer"] is None
    r2 = await hass.services.async_call(DOMAIN, "add_session", {"location": "Now", "energy": 5, "cost": 2,
        "date": dt_util.now().strftime("%Y-%m-%d %H:%M:%S")}, blocking=True, return_response=True)
    assert r2["session"]["odometer"] == 2000
    for r in (r1, r2):
        await hass.services.async_call(DOMAIN, "delete_session", {"session_id": r["session"]["id"]}, blocking=True)
    await hass.async_block_till_done()

    # card is served
    client = await hass_client()
    card = await client.get("/ev_charge_log/ev-charge-log-card.js")
    assert card.status == 200
    assert "ev-charge-log-card" in await card.text()
    months = {m["month"]: m for m in resp["monthly"]}
    assert months["2026-09"]["km"] == 1000
    assert months["2026-10"]["km"] == 1000  # 2000 (lidl reading) - 1000

    await hass.services.async_call(DOMAIN, "update_session", {"session_id": sid, "cost": 12.0}, blocking=True)
    await hass.async_block_till_done()
    assert float(val("cost_public").state) == 12.0

    await hass.services.async_call(DOMAIN, "delete_session", {"session_id": sid}, blocking=True)
    await hass.async_block_till_done()
    assert float(val("charging_sessions").state) == 2

    # persisted & reload ok
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(val("charging_sessions").state) == 2
    assert "sessions" in val("last_charging_session").attributes
