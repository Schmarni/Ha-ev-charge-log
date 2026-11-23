# EV Charge Log (EV-Ladebuch) for Home Assistant

Combines the charging sessions **evcc** records at home with the sessions you charge
**elsewhere** (public chargers, supermarket, work …) and turns them into statistics:
cost, average price per kWh, consumption, and a comparison against a combustion car.

## Features

- Reads all sessions from the evcc REST API (`/api/sessions`): energy, price, odometer, solar share
- Takes the odometer from evcc (`/api/state`) – no car integration needed
- Action `ev_charge_log.add_session` to log public charging (location, kWh, price, date,
  odometer, charge time, waiting time, AC/DC, note); stored in Home Assistant
- Actions to update, delete and list sessions (`list_sessions` returns all sessions + monthly overview)
- 30 sensors, e.g.
  - energy total / at home / public / this month / this year
  - cost total / at home / public / this month / this year
  - average price per kWh (total / home / public)
  - distance, odometer, consumption kWh/100 km
  - cost of a comparable fuel car, savings (total / month / year), cost per 100 km
  - solar share at home, waiting and charging time on public chargers
  - last session (attribute `sessions`: last 25 sessions) and monthly overview (attribute `months`)
- Fuel price either fixed or from any sensor (e.g. Tankerkönig)

Sessions where evcc has no price are costed with the average home price.

## Installation

### HACS
1. HACS → ⋮ → Custom repositories → add this repository as type *Integration*
2. Install **EV Charge Log**, restart Home Assistant

### Manual
Copy `custom_components/ev_charge_log` into your `config/custom_components` folder and restart.

## Setup

Settings → Devices & services → Add integration → **EV Charge Log**

| Option | Meaning |
|---|---|
| evcc URL | e.g. `http://49686a9f-evcc:7070` for the evcc add-on, or `http://<ip>:7070` |
| Fuel car consumption | l/100 km of the car you compare against |
| Fuel price / fuel price sensor | fixed €/l, or a sensor with the current price |
| Odometer at start | distance is counted from this value (0 = from new) |
| Vehicle filter | optional, comma separated parts of evcc vehicle names |

## Logging a public charging session

```yaml
action: ev_charge_log.add_session
data:
  location: Lidl Pirna
  energy: 23.44
  cost: 10.32
  duration: 25
  waiting_time: 5
  charge_type: DC
```

Without `date` the session is logged *now* and gets the last odometer evcc reported.
Tip: wrap the action in a script with fields – the script's more-info dialog is then a
ready-made input form for your dashboard.
