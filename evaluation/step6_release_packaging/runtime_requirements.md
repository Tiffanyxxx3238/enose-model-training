# Step 6A — Runtime requirements and Raspberry Pi 3 compatibility (offline pre-check)

**Status: UNVERIFIED — REQUIRES TARGET ENVIRONMENT CHECK.** No Raspberry Pi was accessed. Every conclusion below comes either from published distribution metadata (PyPI, piwheels) or from x86_64 proxy measurements.

## 1. Python dependencies

`requirements/requirements_release.txt` in the package has two parts:

- **The Step 5 accepted pins, unchanged** (from `requirements_rpi.txt`): joblib 1.5.3, numpy 2.4.3, pandas 3.0.1, pyserial 3.5, python-dateutil 2.9.0.post0, scikit-learn 1.8.0, scipy 1.17.1, six 1.17.0, threadpoolctl 3.6.0.
- **Added: the web stack**, which `requirements_rpi.txt` omitted even though all three services import Flask. Versions are copied unchanged from `pineapple_app_gateway/requirements_gateway.txt`: Flask 3.1.3, Werkzeug 3.1.8, Jinja2 3.1.6, MarkupSafe 3.0.3, itsdangerous 2.2.0, click 8.3.3, blinker 1.9.0.

No existing pin was downgraded or changed.

Not required at runtime:
- paramiko: only for `app_local.py`'s legacy SSH mode; its import is now lazy.
- openpyxl: only for xlsx demo mode; demo data is not shipped.
- requests: only for Gateway v1, which is not shipped.

**Tested here** with an isolated venv containing exactly these versions: Python 3.12.7 (x86_64, Windows). Python 3.11, the Bookworm version, was **not** available to test.

## 2. Pi 3 architecture and OS (from `rpi3_compatibility_matrix.csv`)

| Target | Python ABI | Result for the 16 pinned packages | Assessment |
|---|---|---|---|
| Raspberry Pi OS **Bookworm 64-bit** (aarch64, glibc 2.36) | cp311 | 16/16 PyPI manylinux aarch64 / pure wheels | **Recommended target** — wheels exist; install and run **UNVERIFIED** |
| Raspberry Pi OS Trixie 64-bit | cp313 | 16/16 wheels | Wheels exist; UNVERIFIED |
| Raspberry Pi OS Bookworm 32-bit (armv7l) | cp311 | 16/16 via **piwheels** (community builds) | Possible but riskier. **The model pickle was created on 64-bit; loading it on 32-bit is unverified.** |
| Raspberry Pi OS Trixie 32-bit | cp313 | numpy and scipy have **no wheel** (source build needed) | Not recommended: compiling scipy on a 1 GB Pi 3 is impractical. UNVERIFIED |
| Raspberry Pi OS Bullseye (32/64-bit) | cp39 | numpy, pandas, scikit-learn and scipy need **Python ≥ 3.11** | **BLOCKER** (from `requires_python` metadata) |

The Pi 3 has a Cortex-A53 (ARMv8) and can run either 64-bit or 32-bit Raspberry Pi OS. **Which OS and architecture the Pi actually runs is unknown.** `ops/rpi3_preflight.py` reports it, read-only, when run on the Pi.

## 3. Resources (x86_64 proxy — NOT a Pi measurement)

| Item | x86_64 measurement | Pi 3 implication |
|---|---|---|
| Model file | 6.14 MB; ExtraTrees with 400 trees and 65,676 nodes | — |
| Gateway process (numpy + pandas + sklearn + Flask + model loaded) | working set ≈ 165–168 MB | Pi 3 has 1 GB RAM. The web service's CLI child loads the model again during a web scan (another ~165 MB). Peak ≈ 2 × 170 MB plus the OS. Recommend ≥ 350 MB available. |
| Committed memory **without** BLAS thread limits | ≈ 1,386 MB (OpenBLAS per-thread buffers) | Risky on a 1 GB Pi |
| Committed memory with `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1` | ≈ 164 MB | **The service manager now sets these.** Tree inference does not use BLAS, so results are unchanged (Step 6A replay identical). |
| Single-row `predict_proba`, `n_jobs=1` | ≈ 47 ms | On a Pi 3, expect several times slower; it is still a small part of the 30 s acquisition. UNVERIFIED |
| Model load | ≈ 0.5 s | Expect several seconds on a Pi 3; startup waits up to 90 s for health |
| Package on disk | 93 KB (tar.gz) | Data folder ≥ 500 MB recommended for logs and history |

## 4. Model serialisation

The model was pickled with scikit-learn 1.8.0, which matches the release pin; it loads with no version warning under 1.8.0. Cross-architecture pickle loading (64→32-bit) is **unverified**.

## 5. Serial and OS permissions

- The Arduino appears as `/dev/ttyACM*` or `/dev/ttyUSB*`, or is set via the profile's `serial_port`. The Gateway and both CLIs now use the same rule.
- The service user needs `dialout` group membership. The preflight reports this but does not change it.
- pyserial 3.5 is a pure-Python wheel.
- A cross-process sensor lock (`<data_root>/.device.lock`, using `fcntl.flock` on Linux) keeps the web CLI and the Gateway from reading the Arduino at the same time. It was tested on Windows (`msvcrt`); **the Linux `flock` path was not executed.**

## 6. Running the services together

All three services were started together, tested, and stopped from an extracted package on the test host (x86_64 Windows). **Running them together on a Pi 3 (memory, CPU, startup time) is UNVERIFIED.**

## 7. Read-only preflight

`ops/rpi3_preflight.py` checks:
- OS, architecture, board model and glibc;
- Python version;
- every pinned package version;
- available memory and disk;
- release integrity (SHA256SUMS);
- profile and runtime configuration;
- port availability;
- serial device listing and `dialout` membership.

It does not install, modify, open serial ports, use the network or SSH, or print secrets. On this Windows host it ran as a smoke test only (see `logs/rpi3_preflight_smoke.txt`); its Pi-specific branches (`/proc`, `/etc/os-release`, `grp`) were not exercised.
