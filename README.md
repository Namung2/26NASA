# BingoTime

A map-based decision companion for astronauts walking on Mars.
Built for the NASA Space Apps Challenge 2026 (Seoul), challenge "Interplanetary Survival Guide: Martian Map".

An EVA plan is made on Earth, but the moment that matters comes in the field: a rock that was not in the plan,
a radio link that drops behind a ridge, dust that starts to rise. At that moment BingoTime raises one decision card
with a few options and shows what each option costs on the same ruler — walking time, margin before the latest safe
departure, and science value (a relative index). The tool only proposes. The plan changes when the astronaut chooses.

## What is in this repository

| Folder | What it is | Language |
|---|---|---|
| `core/` | The decision core: route search, walking time, return time and latest safe departure, science-value map, decision cards. One C header (`core/include/btcore.h`), no memory allocation after start-up, bounded loops, same output for the same input | C++17 |
| `pipeline/` | Ground pipeline. Turns source data for one area into a read-only bundle: slope, roughness, shadows by time of day, radio-link map, geologic units, mineral classes, sun table, weather replay, map tiles | Python |
| `host/` | Shared shell code: the binding to the core, bundle loader, message models, screen texts | Python |
| `device/` | The program on the suit (5 m grid). Works alone when the link to the rover is lost | Python |
| `rover/` | The program on the rover (2 m grid). Adds alternatives and keeps the science-value map | Python |
| `sim/` | Simulator: scenario files, a headless runner with pass/fail checks, and a live server for the screens | Python |
| `screen/` | Field screen, rover console and start page | TypeScript, React, Leaflet, three.js |
| `config/` | Parameters with the source of every value (`params.yaml`), area definitions, the starting table for science value | YAML |
| `tests/` | Tests of the core through the Python binding and of the scenarios | Python |
| `scripts/` | Helpers: check a bundle, place scenario points, generate TypeScript types | Python |

## Requirements

- macOS (this is where it was built and tested; a Linux build has not been verified)
- A C++17 compiler
- Python 3.12 or newer
- Node.js 20 or newer

## Build

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/cmake --preset native
.venv/bin/cmake --build --preset native
./build/native/bt_selftest

cd screen && npm install && npm run build && cd ..
```

## Data bundle

The simulator and the screens need a data bundle in `data/bundles/jezero_west_v1/`.
Bundles and source data are not stored in this repository because of their size (the source elevation mosaic alone is 1.8 GB).

To rebuild the bundle, download the source products listed under [Data](#data), place them under `자료/` at the paths
written in `config/site.yaml`, and run:

```bash
.venv/bin/python -m pipeline.build --site config/site.yaml --out data/bundles/jezero_west_v1
```

Two more areas inside Jezero crater are defined in `config/sites/` (`jezero_floor`, `jezero_inlet`).

## Run

Live server with the screens (start page at `http://localhost:8000/`, also `/field.html` and `/console.html`):

```bash
.venv/bin/python -m sim.live --scenario D1_demo --speed 10
```

Scenarios without a screen (writes a report for each scenario to `reports/`):

```bash
.venv/bin/python -m sim.runner sim/scenarios/*.yaml
```

Tests:

```bash
.venv/bin/python -m pytest -q
```

## Scenarios

| File | What happens |
|---|---|
| `V1_apollo17_station4.yaml` | Validation. Replays the order of events of Apollo 17 EVA-2 Station 4: arrival, an unexpected find, a hypothesis, a choice, the departure limit, and return |
| `V2_link_loss.yaml` | Validation. Same terrain and start as V1, with the rover link down for part of the walk |
| `D1_demo.yaml` | Demonstration. Starts 4 h 40 min into the EVA: an unexpected find, a hypothesis, link loss and recovery, the departure limit, return to the rover |
| `D2_from_rover.yaml` | Demonstration. Starts at the rover at EVA 0 and walks P1 → P2 → P3, then returns |

## Data

### NASA and USGS

| Product | Used for | Reference |
|---|---|---|
| Mars 2020 Terrain Relative Navigation HiRISE DTM Mosaic, 1 m (USGS Astrogeology) | Elevation: slope, roughness, shadows, radio line of sight | https://doi.org/10.5066/P9REJ9JN |
| Mars 2020 Terrain Relative Navigation CTX Orthomosaic, 6 m (USGS Astrogeology) | Base image; reference for registering the other layers | https://doi.org/10.5066/P9GV1ND3 |
| USGS SIM 3464, Geologic Map of Jezero Crater and the Nili Planum Region, Mars (Sun & Stack 2020) | Geologic units | https://doi.org/10.3133/sim3464 |
| Mars 2020 MEDA calibrated data, sol 313 (NASA PDS Atmospheres Node) | Air temperature for the weather replay | https://doi.org/10.17189/1522849 |
| MRO CRISM MTRDR scene HRL000040FF (NASA PDS Geosciences Node) | Checking the position of the mineral map | — |
| NASA GISS Mars24 Sunclock, "Algorithm and Worked Examples" | Sun elevation and azimuth for the sun table | https://www.giss.nasa.gov/tools/mars24/help/algorithm.html |
| NASA xEVA System Concept of Operations, EVA-EXP-0042 Rev B | EVA length, walking speed, walking range | https://www.nasa.gov/wp-content/uploads/2017/02/eva-exp-0042_xeva_system_con_ops_rev_b_final_dtd_10192020_ref_doc.pdf |

### Other sources

| Product | Used for | Licence | Reference |
|---|---|---|---|
| Parente, Itoh, Saranathan 2021, Jezero crater mineral map | Mineral classes | CC BY 4.0 | https://doi.org/10.5281/zenodo.5575824 |
| Smith 2022, Perseverance MEDA/TIRS aerosol retrievals | Dust optical depth for the weather replay and the dust threshold | CC BY 4.0 | https://doi.org/10.17632/48phhtkcj8.1 |

The source of every numeric parameter is written next to its value in `config/params.yaml`.
A value without a source is left empty instead of guessed.

## Third-party code

| What | Licence |
|---|---|
| React, Leaflet, three.js, Vite, TypeScript | MIT, BSD-2-Clause (Leaflet), Apache-2.0 (TypeScript) |
| Fontsource fonts: Cormorant Garamond, Inter, JetBrains Mono | SIL OFL 1.1 |
| React Bits components in `screen/src/vendor/` (used unchanged) | MIT + Commons Clause, © David Haz — see `screen/src/vendor/README.md` |
| NumPy, SciPy, rasterio, pyogrio, scikit-image, Pillow, PyYAML, pydantic, FastAPI, uvicorn, websockets | see each project |

## Use of AI

Most of the code, tests and English text in this repository were written with an AI coding assistant
(Claude Code, Anthropic) under the team's direction and review. The assistant was also used to find and read references.

The product itself contains no AI or machine-learning model. Every number on the screen comes from deterministic
computation on the data listed above.

## Limits

- This is not a safety system. It is an information tool beside the suit's own caution and warning system.
- "Science value" is a relative index built from the geologic unit, the mineral class and the crew's observations.
  It is not a calibrated probability, and the starting table (`config/prior_table.yaml`) has not been reviewed by a geologist.
- The device and rover programs run inside one process in the simulator. They have not been run on flight-like hardware.
