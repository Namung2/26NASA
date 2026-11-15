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

The simulator and the screens need a data bundle in `data/bundles/`. Three bundles (about 60 MB each) come with this
repository as zip files in `release/`: `jezero_west_v1`, `jezero_floor_v1`, `jezero_inlet_v1`. Every bundle shows up
as a map on the start page. They are unpacked on first use:

- When the live server starts and the bundle is not unpacked yet, it checks the zip's size and SHA-256 against
  `config/bundles.yaml` and unpacks it into `data/bundles/`.
- When another map is picked on the start page for the first time, it is unpacked the same way.
- If the zip is not in `release/` (for example, a copy of the code without the zips), it is downloaded from this
  repository instead.

To unpack everything without starting the server:

```bash
.venv/bin/python -m host.fetch --all
```

To rebuild a bundle from the source data instead, download the products listed under [Data](#data), place them under
`자료/` at the paths written in `config/site.yaml` (the source elevation mosaic alone is 1.8 GB), and run:

```bash
.venv/bin/python -m pipeline.build --site config/site.yaml --out data/bundles/jezero_west_v1
```

The other two areas are defined in `config/sites/` (`jezero_floor`, `jezero_inlet`) and are built the same way with
their own `site.yaml`.

## Run

Live server with the screens (start page at `http://localhost:8000/`, also `/field.html` and `/console.html`):

```bash
.venv/bin/python -m sim.live --scenario D1_demo --speed 10
```

On the start page you pick, in order: a map, a scenario on that map, and a screen (field screen or rover console).
Picking a scenario starts it on the chosen map. Both screens then show the same run.

What the screens do:

- **Field screen** (tablet of the crew member outside): map with the path walked, the return route and the next leg;
  decision cards; observation, hypothesis, photo, new site / blocked area, and *Replan* (click stops on the map in the
  order you want; the rover returns that order as a "My plan" card next to the other cards, and the plan changes only
  when that card is selected). Photos are stored on the device under `photos_live/`. The browser gives camera access
  only on `localhost` or over https; elsewhere the photo panel offers a file picker instead.
- **Rover console**: all candidate options in one table with an elevation profile, notes and hypotheses, and a 2D / 3D
  switch on the map. The 3D view shows the terrain with the same layers as the 2D map and the live science-value map.
  Heights in 3D are stretched for viewing (×3 by default; the factor is always shown and can be changed).
- A *Simulation / Live* switch on the start page hides the simulator controls in Live mode. See [Limits](#limits).

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
| `F1_free_run.yaml` | Free run. Starts at the rover at EVA 0 with the plan P1 → P2 → P3 and scripts nothing: observations, hypotheses, replanning and card choices are made by the person at the screen. Walking, the recorded weather and the radio link are simulated |

Scenarios point at stops by name (P1, P2, P3) and at the rover park, so they also run on the other maps
(`sim.runner --bundle data/bundles/<id> --any-site`). All four finish on all three maps. The pass/fail checks in the
validation scenarios were written for `jezero_west_v1`.

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
- Live mode on the start page only hides the simulator controls. The data still comes from the simulator, because the
  device and rover programs do not yet run as separate programs fed by real sensors.
- Photos stay on the device. Sending them to the rover is not implemented, so the rover console does not show them.
- One map is loaded at a time. If two people pick different maps, the later choice replaces the earlier one for both.
- A few provenance notes shown beside values (the ⓘ marks) are still in Korean.
