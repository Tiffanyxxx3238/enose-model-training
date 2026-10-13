# Step 6A — Service port layout (applied)

## Final layout

| Service | Entry point (in release) | Formal port | Engineering (TEST) port | Default bind | Who connects |
|---|---|---|---|---|---|
| **gateway** — App API (Gateway v2, Step 5 accepted) | `app/pineapple_app_gateway/app_gateway_v2.py` | **5001** | 5101 | 127.0.0.1 | Consumer App (`EXPO_PUBLIC_PINENOSE_API_URL=http://<Pi LAN IP>:5001`) |
| **web** — odour ripeness page | `app/pineapple_final/app_local.py` (local execution mode) | **5000** | 5100 | 127.0.0.1 | Browser, directly or inside the unified page's iframe |
| **unified** — unified web (iframe container) | `app/unified_web/app.py` | **8000** | 8100 (disabled by default) | 127.0.0.1 | Browser |
| Gateway v1 (`app_gateway.py`) | **not in the release** | — | — | — | Retired. Never started by the scripts. |
| Photo / variety page | not in this repository's scope | (5002, external) | — | — | — |

## Why this layout

1. **5000 stays the web ripeness page.** The unified page's iframe has always pointed at `:5000` for the odour page.
2. **Gateway v2 moves from 5000 to 5001.** This removes the 5000 conflict with `app_local.py`. The Consumer App already lets the user enter the Gateway address, and the default now comes from deployment configuration.
3. **The unified web keeps 8000.** Gateway v1 also used 8000; v1 is retired and is not packaged.
4. **Engineering uses a separate port range (51xx/81xx).** A TEST profile can never collide with, or be mistaken for, formal services. It is also bound to loopback only.

## Rules enforced by `ops/pinenose_service.py` (tested)

| Rule | Test |
|---|---|
| Default bind is 127.0.0.1. The source defaults of `app_gateway_v2.py`, `app_local.py` and unified `app.py` were also changed from `0.0.0.0` to `127.0.0.1`. | S01, S14 |
| Non-loopback is allowed only with `"lan_access": true` **and** an explicit private IPv4 address. `0.0.0.0`, `::`, public IPs and host names are rejected. | S14 |
| Engineering profile: loopback only; `lan_access` is rejected. | E01 |
| No two services in a profile may share a port. | S14 |
| Before starting, every required port is checked. If any is in use, start fails with **exit 3 `PORT_IN_USE`** and **no service is started**. | S07 |
| The unified iframe URLs come from the profile (`smell_url`, `photo_url`). With `lan_access`, a `localhost`/`127.x` iframe URL is rejected, because a remote browser cannot reach the Pi that way. Unset URLs show "未設定" and embed nothing. | S14, F01 |
| The unified web runs with `debug=False`. Before this step it used `debug=True`, which exposes Werkzeug's interactive debugger. | code change; F01 page check |

## Configuration files changed (not just documentation)

- `pineapple_app_gateway/app_gateway_v2.py`, `pineapple_final/app_local.py` and `整合網頁/pineapple_unified_web/app.py`: host and port come from the environment set by the manager; the default is loopback.
- `整合網頁/pineapple_unified_web/templates/index.html`: an unconfigured iframe shows a notice.
- `整合網頁/start_pineapple_system.sh` and `stop_pineapple_system.sh`: now wrappers around the service manager.
- `pineapple_app_gateway/start_server.sh`: disabled. It previously opened an ngrok public tunnel.
- `pinenose_release/config/profile.*.template.json`: the layout above.
- Consumer App: `DEFAULT_API_URL` comes from `EXPO_PUBLIC_PINENOSE_API_URL`, and the settings placeholder shows `:5001`. Farmer App: default URL from the same variable.

## Not verified here

The Pi's real LAN address, firewall and Wi-Fi/hotspot topology, and phone↔Pi connectivity have **not** been checked; no Pi was accessed. Only loopback was used in tests. The explicit private-LAN profile was validated with `check` only and was never bound.
