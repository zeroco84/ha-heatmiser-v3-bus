# Heatmiser V3 Bus for Home Assistant

Local control of a wired **Heatmiser V3 RS-485 thermostat network** (the Touchpad-era network, e.g. PRT-E thermostats) from Home Assistant, through a cheap RS485-to-Ethernet converter.

It is built to sit **alongside an existing Heatmiser Touchpad** without upsetting it:

- **Reading is passive.** The Touchpad already polls every thermostat every few seconds. This integration decodes that traffic instead of polling, so it adds nothing to the bus just to read temperatures.
- **Changes are slipped into the gaps.** When you change something in Home Assistant, the command is sent in the quiet moment after a thermostat answers the Touchpad, then confirmed and retried if needed.
- **No Touchpad?** If the bus has been silent for 30 seconds, the integration polls the thermostats itself, slowly. This mode is untested; see [Tested hardware](#tested-hardware).

> **Not affiliated with Heatmiser.** "Heatmiser" is a trademark of Heatmiser UK Ltd and is used here only to say what this works with. This software controls heating equipment and you use it at your own risk (see the [licence](LICENSE)).

---

## Contents

- [What you get](#what-you-get)
- [Tested hardware](#tested-hardware)
- [What you need](#what-you-need)
- [Wiring](#wiring)
- [Setting up the converter](#setting-up-the-converter)
- [Check the wiring before Home Assistant](#check-the-wiring-before-home-assistant)
- [Installing](#installing)
- [Adding it to Home Assistant](#adding-it-to-home-assistant)
- [How it behaves](#how-it-behaves)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Credits](#credits)

---

## What you get

**One device per thermostat, each with these entities:**

| Entity | What it does |
|---|---|
| `climate.<room>` | Current temperature, set temperature (+/−), and **Heat / Off** mode. **Off puts the thermostat in Frost mode**, so frost protection stays on. It never powers the thermostat down. |
| `sensor.<room>_temperature` | Room temperature, kept in long-term statistics for history graphs. |
| `sensor.<room>_floor_temperature` | Only created for thermostats that have a floor probe. |
| `binary_sensor.<room>_heating` | On while that thermostat is calling for heat. |

The climate entity also carries these attributes:
- `status`: Heating, Idle, Frost or Thermostat off
- frost temperature, sensor in use and program mode
- the weekday and weekend program (comfort levels)
- holiday hours and hold minutes
- key lock, error code and bus address

**One "Heatmiser Network" device for the whole bus, with:**

| Entity | What it does |
|---|---|
| `switch.heatmiser_network_heating_away` | **Away.** Puts every room into Frost. Turning it off puts back only the rooms that were on Heat. It remembers which rooms those were across restarts. |
| `sensor.heatmiser_network_rooms_heating` | How many rooms are calling for heat. The `rooms` attribute lists them. |
| `button.heatmiser_network_sync_thermostat_clocks` | Sets every thermostat clock to Home Assistant's time. |
| `binary_sensor.heatmiser_network_bus` | Connected / disconnected, plus traffic counters (diagnostic). |

**Thermostat clocks** are checked every night at 03:30. Any that are more than 90 seconds out are corrected, which also takes care of the summer/winter clock changes. There's a service too: `heatmiser_bus.sync_clocks` (optional `force: true`).

## Tested hardware

This has been tested on one installation, as follows. Other setups should work but haven't been verified. Issues and reports are welcome.

| Part | Tested |
|---|---|
| Master | Heatmiser **Touchpad** (V3 network, 12 V DC) |
| Thermostats | 20 × **PRT-E** (model code 3) and 1 × **PRT** (model code 2), all in 5/2-day program mode, °C |
| Converter | **Waveshare RS485 TO POE ETH (B)**, firmware V1.523 |
| Home Assistant | 2026.9.4 on Home Assistant Green |

**Not supported:**
- PRT-HW hot water control
- TM1 timers
- Fahrenheit displays
- Heatmiser Neo / Wi-Fi models, which are a different system altogether

## What you need

1. **An RS485-to-Ethernet converter** that can run as a **transparent TCP server**: it passes raw bytes both ways and doesn't speak Modbus.
   - The Waveshare unit above is PoE-powered, which is handy in a comms cabinet.
   - Similar devices (other Waveshare models, USR IOT, Elfin and so on) should work but are untested.
2. **A short length of twisted pair,** such as one pair from a Cat5 offcut.
3. **A small flat screwdriver.**

## Wiring

The Heatmiser V3 network is a single RS-485 pair, daisy-chained from the Touchpad through every thermostat. **You connect the converter to that same pair at any one point.** The easiest point is the back of the Touchpad, because it's low voltage.

### At the Touchpad (recommended)

The Touchpad's rear terminal block is labelled **`B Y D C − +`**:

| Touchpad terminal | What it is | Connect to converter |
|---|---|---|
| **Y** | RS-485 **A** (+) | **A** (sometimes labelled 485A, A+, D+) |
| **B** | RS-485 **B** (−) | **B** (sometimes labelled 485B, B−, D−) |
| D, C | other functions | leave alone |
| −, + | 12 V DC supply | leave alone |

```
   Heatmiser Touchpad (rear)                 RS485-to-Ethernet converter
  ┌───────────────────────────┐             ┌─────────────────────────┐
  │  B   Y   D   C   −   +    │             │  A (485+)    B (485−)   │
  └──┬───┬────────────────────┘             └────┬───────────┬────────┘
     │   │                                       │           │
     │   └──────────── twisted pair ─────────────┘           │
     └───────────────────────────────────────────────────────┘
     │   │
     │   └─ existing bus wires to the thermostats stay in place
     └───── (share the same screw terminals)
```

**Steps**
1. Take the Touchpad off the wall. It lifts off its back box; check your model's instructions.
2. Loosen the **Y** and **B** screws. **Leave the existing wires in.** Add the new pair alongside them:
   - Y goes to the converter's **A**.
   - B goes to the converter's **B**.
3. Tighten both screws and tug-test every wire. Don't disturb **+ / −**, which power the Touchpad.
4. Refit the Touchpad.

**Notes**
- **Polarity:** if you swap A and B, you'll simply hear no valid traffic. Nothing is damaged. Swap the two wires at the converter and try again.
- **Ground and termination:** the tested install didn't connect a ground/shield wire and didn't change any termination resistors. If your bus already works, leave it as it is.
- **Cable length:** keep the new run short. The converter only needs to be near the Touchpad, and the PoE model can sit in the comms cabinet next to it.

### At a thermostat instead

You can tap the bus at any thermostat's comms terminals instead. Terminal labels differ between models, so check the installation manual for your thermostat.

> ⚠️ **Many Heatmiser thermostats are mains-powered.** Switch off and isolate the supply before opening one. If you're not comfortable working near 230 V, use the Touchpad or ask an electrician.

## Setting up the converter

Whatever converter you use, it needs these settings:

| Setting | Value |
|---|---|
| Serial: baud rate | **4800** |
| Serial: data / parity / stop | **8 / None / 1** (8N1) |
| Flow control | None |
| Work mode | **TCP Server** |
| Local port | e.g. **4196** (used in Waveshare's examples; any free port will do) |
| IP | DHCP with a **reservation** in your router, or a static IP |

**Waveshare RS485 TO POE ETH (B) tips** (firmware V1.523):
- Waveshare's [wiki page](https://www.waveshare.com/wiki/RS485_TO_POE_ETH_(B)) uses **192.168.1.200** as the example address for a new unit. Their *VirCom* tool can find and configure it. Alternatively, temporarily give your computer an address on 192.168.1.x and open its web page.
- The factory web page has no password set.
- **On the tested unit, settings only *saved* when logged in with a blank password.** Logging in with any other password let us view the settings but not change them.
- Click **Submit** to save, then let it restart. After that, find its new DHCP address in your router and reserve it.
- It accepts more than one TCP client at a time, which is handy for testing alongside Home Assistant.

## Check the wiring before Home Assistant

From any computer on the same network, connect to the converter and look for bytes. Nothing is sent to the bus.

```bash
nc <converter-ip> 4196 | xxd | head -20
```

**What to look for**
- **Wiring good:** a steady stream that includes frames starting `81 4b 00`. Those are thermostats answering the Touchpad.
- **Nothing at all:** check the converter's serial settings, and whether the Touchpad is actually polling.
- **Random-looking bytes and no `81 4b 00`:** swap A and B.

## Installing

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/zeroco84/ha-heatmiser-v3-bus` with type **Integration**.
3. Install **Heatmiser V3 Bus**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/heatmiser_bus` into your Home Assistant `config/custom_components/` folder, then restart Home Assistant.

## Adding it to Home Assistant

1. Go to **Settings → Devices & services → Add integration → Heatmiser V3 Bus**.
2. Enter the converter's **IP address** and **port**. Leave *Thermostats* empty.
3. Home Assistant **listens for 20 seconds** and lists every thermostat it hears, by bus address.
4. Give each one a room name.
   - The address is the network number set on the thermostat itself.
   - If your Touchpad shows room names, its stats page tells you which address is which room.
5. Assign each device to an area. Done.

If auto-discovery hears nothing, you can type the thermostats in instead, one `address=Room name` per line, for example:

```
3=Kitchen
4=Kitchen Ensuite
```

To add a thermostat later, remove the integration and add it again. Your entity IDs stay the same if you keep the same names.

## How it behaves

- **Off = Frost.** Choosing Off sets the thermostat to Frost mode, the same as its own Frost setting. It keeps protecting against frost at its frost temperature. The integration never switches a thermostat's power off. If a thermostat *was* powered off at its own keypad, choosing Heat switches it back on.
- **Set temperature** writes the thermostat's set temperature, the same as pressing +/− on the wall. The thermostat's own program then behaves as it normally does: Heatmiser thermostats typically follow the next programmed comfort level when its time comes. The thermostat keeps the set temperature while in Frost mode, and it applies again when you switch back to Heat.
- **Programs** are shown as attributes. Editing them from Home Assistant isn't supported yet.
- **Changes are confirmed.** A change is only applied in Home Assistant once the thermostat acknowledges it, normally in under half a second. If no acknowledgement arrives after several tries, Home Assistant shows an error and nothing changes.
- **Readings** update whenever the Touchpad polls each thermostat, typically every 10 seconds on a 20-thermostat network.
- A thermostat shows as **unavailable** if it hasn't been heard for 3 minutes.

## Limitations

- **Whole degrees only.** That's what the thermostats report.
- **One bus per Home Assistant instance.**
- Programs are decoded in **5/2-day** mode only. 7-day thermostats still work, but their program attribute is empty.
- **PRT-HW** hot water and **TM1** timers aren't supported.
- The integration uses master address **0x82** on the bus. The Touchpad uses 0x81. If something else on your bus already uses 0x82, open an issue.
- **Not tested without a Touchpad,** or with converters other than the Waveshare above.

## Troubleshooting

| Symptom | Things to check |
|---|---|
| "Could not connect to the converter" | The IP and port, that the converter is in **TCP Server** mode, and that nothing else is blocking the port. |
| "No thermostat replies were heard" | Polarity (swap A/B), 4800 8N1, and that the Touchpad is on and polling. Try the `nc` check above. |
| Thermostats go unavailable now and then | Look at `binary_sensor.heatmiser_network_bus`. If it disconnects, check the network and PoE. If it stays connected, check the wiring at the tap point. |
| A change shows an error | The bus was busy or the thermostat didn't answer. Try again. Check the `write_retries` / `write_failures` counters on the bus sensor. |
| Clocks are out by an hour | Check Home Assistant's time zone (Settings → System → General), then press **Sync thermostat clocks**. |

To see what the integration is doing, turn on debug logging:

```yaml
logger:
  logs:
    custom_components.heatmiser_bus: debug
```

## How it works

**Bus basics**
- Heatmiser V3 uses RS-485 at 4800 baud, 8N1.
- A master (the Touchpad, address `0x81`) sends each thermostat (addresses 1–32) a read request.
- The thermostat replies with its *DCB* (data control block): settings, temperatures, clock and program.
- Every frame ends with a CRC-16 (CCITT, initial value 0xFFFF, low byte first).
- Writes go to specific DCB addresses and are acknowledged with a 7-byte frame.

**What this integration does**
- It decodes both directions of the Touchpad's traffic and keeps the latest DCB for each thermostat.
- To write, it waits until a thermostat has finished answering the Touchpad, which leaves a quiet gap of roughly a quarter of a second. It then sends its own frame from master address `0x82` and waits for the acknowledgement.
- If the acknowledgement doesn't arrive, it backs off a random interval and retries, up to six times.
- `custom_components/heatmiser_bus/protocol.py` has the frame handling and is covered by tests in `tests/`, using frames captured from a real bus.

## Credits

- The DCB layout and write addresses follow the [heatmiserV3](https://pypi.org/project/heatmiserV3/) Python library and Heatmiser's published V3 protocol notes.
- One correction to the library: the air temperature is a 16-bit value, high byte first, rather than just the low byte.
