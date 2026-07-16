# Room Template format — public contract (schema_version 1)

A room template is a **locale-neutral** YAML file describing the *functions* of a
room. `compose_rooms` turns a list of rooms into a new KNX project (group-address
structure + ETS import files + a device BOM proposal).

> Stability: the schema is a public contract — a breaking change forces user
> migrations. Every template MUST carry `schema_version`. Identity of a template
> and of every slot is a semantic **ID**, never a human name; renaming a label
> never changes identity or the generated addresses.

## Top-level keys

| key | required | meaning |
|-----|----------|---------|
| `schema_version` | yes | `1`. Guards compatibility/migration. |
| `slot_id` | yes | Locale-neutral ASCII identifier (`[a-z0-9_]+`). The template's identity. |
| `labels` | yes | `{ru: …, en: …}` — presentation only (RU/EN). |
| `parameters` | yes | Named parameters with a `default` (and provenance). |
| `slots` | yes | List of functional slots (see below). |
| `automation_intents` | no | **Non-executable** metadata declarations only. |

## Parameters

Each parameter has a `default`. `area_m2` is special: it is a **hint** that seeds
defaults, not a normative fact — it MUST be declared `role: hint` and carry
`provenance`. In R1 area does not change GA counts; it documents the sizing
assumption only.

```yaml
parameters:
  lighting_circuits:
    default: 2
    provenance: {source: preset_rule, note: "why this default"}
  area_m2:
    default: 28
    role: hint
    provenance: {source: preset_default, user_overridden: false, note: "recommender only"}
```

## Slots and per-slot presets

A slot is a functional block. Each slot declares **both** a `basic` and a
`comfort` preset — presets are *per-slot*, not one monolithic room level, so a
house can pick e.g. comfort climate with basic lighting. A preset is either
`{enabled: false}` or `{enabled: true, function: <type>, multiplicity: {...}}`.

```yaml
slots:
  - slot_id: main_light
    labels: {ru: основной свет, en: main light}
    presets:
      basic:   {enabled: true, function: lighting_switch, multiplicity: {param: lighting_circuits}}
      comfort: {enabled: true, function: lighting_dimmer, multiplicity: {param: lighting_circuits}}
```

`multiplicity` is `{fixed: N}` or `{param: <declared parameter>}` — how many
instances (circuits, windows, zones) the slot expands to.

### Function types (function-first)

Each function type expands into a fixed set of KNX communication objects, each
with a canonical DPT and a command/status role:

| function | objects (role · DPT) |
|----------|----------------------|
| `lighting_switch` | on/off `1.001` · status `1.011` |
| `lighting_dimmer` | on/off `1.001` · dimming `3.007` · brightness `5.001` · status `1.011` · brightness-status `5.001` |
| `lighting_dali` | 1:1 clone of `lighting_dimmer` (DALI specifics live inside the gateway; BOM recipe `dali_gateway_group`) |
| `shutter` | up/down `1.008` · stop `1.010` · position `5.001` · position-status `5.001` |
| `shutter_venetian` | `shutter` + slat `5.001` · slat-status `5.001` + safety-lock `1.001` (write-only input — see below) |
| `climate_floor` | on/off `1.001` · setpoint `9.001` · mode `20.102` · +3 statuses · actual-temp `9.001` · actuating-value `5.001` · actuating-value-status `5.001` |
| `ventilation` | airing-stage `5.010` · airing-stage-status `5.010` · CO₂ `9.008` · humidity `9.007` |
| `multisensor_air` | temperature `9.001` · humidity `9.007` · CO₂ `9.008` (self-reporting, no command → no status pair) |
| `presence` | occupancy `1.018` · illuminance `9.004` |
| `central_scene` | scene `18.001` (no status — a scene has no single state) |
| `central_all_off` / `central_all_on` | all-off / all-on `1.001` (central macro — no single state to read back) |

Every controllable command gets its status object — the generated project passes
`check_missing_status`, `check_dpt`, `check_naming` and `check_policy` cleanly.

Three object classes legitimately have **no status pair**, and the linters treat
them as expected (INFO, not a warning), so a house using them is still clean:

* **safety-lock** input (`shutter_venetian`): a wind/frost lock is a *write-only*
  1-bit input the actuator listens to — there is no feedback object
  (`analyze._is_safety_input` → `safety_input_no_status`);
* **scene control** (`central_scene`, `17.x`/`18.x`): a scene recalls a preset,
  it has no single state (`scene_no_status`);
* **central macros** (`central_all_off`/`_all_on`, "all off"/"all on"/"всё"): a
  broadcast fans out to many actuators (`central_macro_no_status`).

### Status/feedback tokens (pairing)

The pairing engine treats **`Feedback` / `Rückmeldung` / `статус` / `state` /
`status`** (and `fb`, `rueck`, `rück`) as first-class status tokens — a vendor
that names its only status object just "Feedback" (e.g. Theben) still pairs. The
token list lives in `project.STATUS_KEYWORDS` and `pairing._FN_STATUS_TOKENS`.

### DPT tolerance (generation vs import)

"**Missing DPT = hard error**" (`check_dpt`) is a rule about **our generated
output**: the Room Library always emits fully DPT-typed GAs, so a missing DPT in
our own output is a real bug. It is *not* a judgement on a third-party **ETS4
import**: in ETS4-era projects the DPT legitimately lives on the device's
communication object, not on the GA, so `xknxproject` derives it (or reports
`missing_dpt` where the object link is unresolved). Auto-completing that DPT is a
feature, not a defect flag on the vendor — see
[`docs/roadmap/room-library/theben-benchmark/01-dpt-derivation.md`](../../../docs/roadmap/room-library/theben-benchmark/01-dpt-derivation.md).
Reserve GAs are intentionally left **without a DPT** — that is a convention (a
spare slot), not a KNX-required value.

## Address allocation (default taxonomy)

`main` = function domain, `middle` = role/sub-function, `sub` = sequential:

```
0 Central · 1 Lighting · 2 Shutters · 3 HVAC · 4 Sensors · 5 Energy · 6 Diag · 7 Reserve
```

Allocation is deterministic and **permutation-invariant** (rooms are sorted by a
canonical key before allocation), so the same *set* of rooms always yields the
same addresses regardless of input order. Sub-address exhaustion (> 255 in a
middle group) raises a hard error — never a silent overflow.

## automation_intents (declarations only)

Logic (presence→light, wind→shutter) is **not** executed by the templates. It is
declared as metadata for the upper layer (Home Assistant / the KNX program):

```yaml
automation_intents:
  - intent: presence_lights_off
    description: "Turn lights off when unoccupied."
    criticality: convenience        # or safety_related
    implementation: external        # external (HA) | knx
```

`implementation` is `external` (Home Assistant) or `knx` (the autonomous KNX
program). **Rule: `criticality: safety_related` ⇒ `implementation: knx`.**
Safety protection (wind/frost blind retract, leak→water-shutoff, fire) must run
autonomously in KNX and must never depend on a network-reachable HA. The template
lays the GA **hook** (e.g. the `shutter_venetian` safety-lock input); the
integrator tunes the **thresholds** (wind m/s, frost °C, timers) in KNX.

## Not in R1

Docking into an existing project (allocation lockfile, drift detection), exact
device selection with channel/price optimisation, and premium presets are R2 —
see `docs/roadmap/room-library/implementation-plan.md`.
