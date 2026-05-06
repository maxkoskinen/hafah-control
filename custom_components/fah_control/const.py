DOMAIN = "fah_control"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_PORT = 7396
DEFAULT_POLL_INTERVAL = 60
DEFAULT_NAME = "Folding@Home"

WS_PATH = "/api/websocket"
WS_CONNECT_TIMEOUT = 5

# FAH states (as exposed by this integration)
STATE_FOLDING = "folding"
STATE_PAUSED = "paused"
STATE_FINISHING = "finishing"
STATE_OFFLINE = "offline"

# Commands sent to the FAH client
CMD_FOLD = "fold"
CMD_PAUSE = "pause"
CMD_FINISH = "finish"

# Select options — the order matters for the UI dropdown
SELECT_OPTIONS = [CMD_FOLD, CMD_PAUSE, CMD_FINISH]

# Map from our internal state to the select option value
STATE_TO_SELECT: dict[str, str] = {
    STATE_FOLDING: CMD_FOLD,
    STATE_PAUSED: CMD_PAUSE,
    STATE_FINISHING: CMD_FINISH,
}

# Platforms
PLATFORMS: list[str] = ["select", "sensor"]
