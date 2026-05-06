# Folding@Home Control for Home Assistant

A Home Assistant custom integration that controls [Folding@Home](https://foldingathome.org/) v8 clients on your local network via their WebSocket API. Exposes switch entities (fold/pause) and state sensors for each configured FAH machine. Designed to be robust against machines being offline or shut down.

## Features

- Control multiple FAH v8 clients from Home Assistant
- Switch entity to start/pause folding
- Sensor entity showing current folding state
- Services for fold, pause, and finish commands with optional group targeting
- Graceful handling of offline machines (no log spam)
- Automatic recovery when machines come back online
- HACS compatible

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click **Integrations**
3. Click the three dots menu → **Custom repositories**
4. Add the repository URL, category: **Integration**
5. Search for "Folding@Home Control" and install
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/fah_control` directory to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Folding@Home Control**
3. Enter the host (IP/hostname), port (default `7396`), and a friendly name
4. The integration will validate the connection before adding

## Entities

### Switch: `switch.fah_<name>_folding`

| State         | Description              |
|---------------|--------------------------|
| **ON**        | Machine is folding       |
| **OFF**       | Machine is paused        |
| **Unavailable** | Machine is unreachable |

### Sensor: `sensor.fah_<name>_state`

| State        | Description                          |
|--------------|--------------------------------------|
| `folding`    | Actively folding work units          |
| `paused`     | Folding is paused                    |
| `finishing`  | Finishing current WU then will pause |
| `offline`    | Machine is unreachable               |

**Attributes:**

| Attribute | Description                        |
|-----------|------------------------------------|
| `groups`  | List of resource groups on the FAH client |
| `host`    | Configured host / IP address       |
| `port`    | Configured WebSocket API port      |

## Services

| Service              | Description                    | Fields                                          |
|----------------------|--------------------------------|-------------------------------------------------|
| `fah_control.fold`   | Start folding                  | `entity_id` (required), `group` (optional)      |
| `fah_control.pause`  | Pause folding                  | `entity_id` (required), `group` (optional)      |
| `fah_control.finish` | Finish current WU then pause   | `entity_id` (required), `group` (optional)      |

### Service Examples

**Start folding on a specific machine:**

```yaml
service: fah_control.fold
target:
  entity_id: switch.fah_desktop_folding
```

**Pause a specific resource group:**

```yaml
service: fah_control.pause
target:
  entity_id: switch.fah_desktop_folding
data:
  group: gpu-1
```

**Finish current work unit then pause:**

```yaml
service: fah_control.finish
target:
  entity_id: switch.fah_server_folding
```

## Options

| Option          | Description                                      | Default    |
|-----------------|--------------------------------------------------|------------|
| **Poll interval** | How often to check FAH client status (seconds) | 60 seconds |

Configure via the integration's **Options** flow:

1. Go to **Settings** → **Devices & Services**
2. Find the **Folding@Home Control** entry
3. Click **Configure**
4. Adjust the poll interval as needed

## Requirements

- **Folding@Home v8** client running on your network
- Default WebSocket API port is **7396**

## Notes on Robustness

This integration is designed for environments where FAH machines may be:

- **Desktop PCs** shut down at night
- **Laptops** that go to sleep
- **Servers** that occasionally reboot

The integration handles these cases gracefully:

- When a machine goes offline, the switch becomes **unavailable** and the sensor reports `offline` — no error-level log spam is produced.
- When a machine comes back online, the integration automatically reconnects on the next poll cycle and entities become available again.
- Connection timeouts and refused connections are handled quietly at the `DEBUG` log level.

## License

This project is licensed under the [MIT License](LICENSE).