"""Constants for the Heatmiser V3 bus integration."""

DOMAIN = "heatmiser_bus"

CONF_THERMOSTATS = "thermostats"

DEFAULT_PORT = 4196

# Master address HA uses on the bus. The Touchpad uses 0x81.
HA_MASTER = 0x82
TOUCHPAD_MASTER = 0x81

SIGNAL_UPDATE = DOMAIN + "_update_{}"
SIGNAL_STATUS = DOMAIN + "_status"

# A thermostat is unavailable if not heard for this long (seconds)
STALE_AFTER = 180

# DCB indexes (V3 protocol, PRT / PRT-E)
DCB_MODEL = 4
DCB_TEMP_FORMAT = 5
DCB_SENSOR = 13
DCB_PROGRAM_MODE = 16
DCB_FROST_TEMP = 17
DCB_SET_TEMP = 18
DCB_ON_OFF = 21
DCB_KEY_LOCK = 22
DCB_RUN_MODE = 23
DCB_HOLIDAY = 24
DCB_HOLD = 26
DCB_REMOTE_AIR = 28
DCB_FLOOR = 30
DCB_AIR = 32
DCB_ERROR = 34
DCB_HEATING = 35
DCB_DOW = 36
DCB_WEEKDAY = 40
DCB_WEEKEND = 52

# Write addresses
REG_FROST_TEMP = 17
REG_SET_TEMP = 18
REG_ON_OFF = 21
REG_RUN_MODE = 23
REG_TIME = 43

MODELS = {0: "DT", 1: "DT-E", 2: "PRT", 3: "PRT-E", 4: "PRT-HW", 5: "TM1"}
