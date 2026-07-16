"""Theben-benchmark corrections (see docs/roadmap/room-library/theben-benchmark/).

Covers:
  (a) repair `_infer_dpt` — relative dimming (brighter/darker) -> 3.007, while an
      explicit "Dimming value %"/"Brightness value" stays 5.001 (dogfood bug fix);
  (b) the new/extended FUNCTION_OBJECTS (shutter_venetian, climate_floor valve,
      ventilation, lighting_dali, multisensor_air, central_*) — GA counts, DPTs,
      command/status pairing;
  (c) the ventilation domain classifier (airing/проветривание/Lüftung -> hvac);
  (d) end-to-end: a house using venetian blinds + central functions re-reads
      through the standard loader with 0 errors / 0 warnings, and the wind/frost
      safety-lock is an INFO (safety_input_no_status), never a missing-status.

DPT provenance: 3.007 = DPT_Control_Dimming (4-bit relative), 5.001 = Scaling %,
5.010 = 1-byte counter, 9.007 = humidity, 9.008 = CO₂ ppm, 20.102 = HVAC mode —
confirmed against the KNX DPT catalogue (XKNX/xknx via deepwiki).
"""
import os
import tempfile
from types import SimpleNamespace

from nickol_knx_mcp import room_library as rl
from nickol_knx_mcp.repair import _infer_dpt
from nickol_knx_mcp.project import load_project, _domain_from_text
from nickol_knx_mcp.analyze import (validate_naming, detect_missing_status,
                                    detect_dpt_issues)
from nickol_knx_mcp.policy import check_policy, load_policy


# --------------------------------------------------------------------------- #
# (a) repair._infer_dpt — relative vs absolute dimming
# --------------------------------------------------------------------------- #
def _stub(name, kind="command", category="lighting", main=1):
    return SimpleNamespace(name=name, kind=kind, category=category, main=main)


def test_infer_dpt_relative_dimming_is_3007():
    # relative brighter/darker (EN/DE/RU) -> 3.007 DPT_Control_Dimming (was 1.001)
    assert _infer_dpt(_stub("Brighter/ darker Light array 1")) == "3.007"
    assert _infer_dpt(_stub("Heller / dunkler Wohnzimmer")) == "3.007"
    assert _infer_dpt(_stub("Светлее/темнее гостиная")) == "3.007"
    assert _infer_dpt(_stub("Ярче/тусклее спальня")) == "3.007"


def test_infer_dpt_explicit_value_stays_5001():
    # explicit absolute value must NOT be flipped to relative — stays 5.001
    assert _infer_dpt(_stub("Dimming value % Light array 1")) == "5.001"
    assert _infer_dpt(_stub("Brightness value Kitchen")) == "5.001"
    assert _infer_dpt(_stub("Значение яркости кухня")) == "5.001"


def test_infer_dpt_defaults_unchanged():
    # a plain switch is still the safe 1.001 default (regression guard)
    assert _infer_dpt(_stub("Спальня свет - Вкл/выкл")) == "1.001"
    assert _infer_dpt(_stub("Hall switch")) == "1.001"


# --------------------------------------------------------------------------- #
# (b) new / extended FUNCTION_OBJECTS
# --------------------------------------------------------------------------- #
def test_function_objects_shutter_venetian():
    sv = {o.role: o for o in rl.FUNCTION_OBJECTS["shutter_venetian"]}
    assert len(rl.FUNCTION_OBJECTS["shutter_venetian"]) == 7  # shutter(4)+slat+slat_status+lock
    assert (sv["slat"].dpt_main, sv["slat"].dpt_sub, sv["slat"].kind) == (5, 1, "command")
    assert (sv["slat_status"].dpt_main, sv["slat_status"].dpt_sub, sv["slat_status"].kind) == (5, 1, "status")
    assert (sv["safety_lock"].dpt_main, sv["safety_lock"].dpt_sub, sv["safety_lock"].kind) == (1, 1, "command")
    # roller shutter is unchanged (backward compat)
    assert len(rl.FUNCTION_OBJECTS["shutter"]) == 4


def test_function_objects_climate_floor_valve():
    cf = {o.role: o for o in rl.FUNCTION_OBJECTS["climate_floor"]}
    assert (cf["actuating_value"].dpt_main, cf["actuating_value"].dpt_sub,
            cf["actuating_value"].kind) == (5, 1, "command")
    assert (cf["actuating_value_status"].dpt_main, cf["actuating_value_status"].dpt_sub,
            cf["actuating_value_status"].kind) == (5, 1, "status")
    # the historical on/off + setpoint + mode + statuses + actual-temp remain
    assert len(rl.FUNCTION_OBJECTS["climate_floor"]) == 9


def test_function_objects_ventilation():
    v = {o.role: o for o in rl.FUNCTION_OBJECTS["ventilation"]}
    assert (v["airing_stage"].dpt_main, v["airing_stage"].dpt_sub, v["airing_stage"].kind) == (5, 10, "command")
    assert (v["airing_stage_status"].dpt_main, v["airing_stage_status"].dpt_sub) == (5, 10)
    assert (v["co2"].dpt_main, v["co2"].dpt_sub, v["co2"].kind) == (9, 8, "sensor")
    assert (v["humidity"].dpt_main, v["humidity"].dpt_sub, v["humidity"].kind) == (9, 7, "sensor")


def test_function_objects_dali_is_dimmer_clone():
    dali = [(o.role, o.dpt_main, o.dpt_sub, o.kind) for o in rl.FUNCTION_OBJECTS["lighting_dali"]]
    dim = [(o.role, o.dpt_main, o.dpt_sub, o.kind) for o in rl.FUNCTION_OBJECTS["lighting_dimmer"]]
    assert dali == dim, "lighting_dali must be a 1:1 clone of lighting_dimmer"
    assert rl.BOM_RECIPE["lighting_dali"] == "dali_gateway_group"


def test_function_objects_multisensor_and_central():
    ms = rl.FUNCTION_OBJECTS["multisensor_air"]
    assert {o.kind for o in ms} == {"sensor"}  # self-reporting, no command -> no status pair
    assert {(o.dpt_main, o.dpt_sub) for o in ms} == {(9, 1), (9, 7), (9, 8)}
    assert rl.FUNCTION_OBJECTS["central_scene"][0].dpt_main == 18
    assert rl.FUNCTION_OBJECTS["central_all_off"][0].dpt_main == 1
    assert rl.FUNCTION_OBJECTS["central_all_on"][0].dpt_main == 1


# --------------------------------------------------------------------------- #
# (c) ventilation domain classifier (F5: "Airing step" was 'unknown')
# --------------------------------------------------------------------------- #
def test_ventilation_domain_classifier():
    assert _domain_from_text("Airing step") == "hvac"
    assert _domain_from_text("Проветривание кухня") == "hvac"
    assert _domain_from_text("Lüftung Stufe 2") == "hvac"
    assert _domain_from_text("Bad Lüften") == "hvac"
    # regression: an existing lighting name is untouched by the new terms
    assert _domain_from_text("Terrace light") == "lighting"


# --------------------------------------------------------------------------- #
# (d) end-to-end: venetian blinds + central functions -> lint-clean, safety-lock
#     is INFO not a warning.
# --------------------------------------------------------------------------- #
def _reread(house):
    data = rl.build_knxproj_bytes(house)
    tf = tempfile.NamedTemporaryFile(suffix=".knxproj", delete=False)
    try:
        tf.write(data)
        tf.close()
        return load_project(tf.name)
    finally:
        os.unlink(tf.name)


def test_venetian_and_central_round_trip_clean():
    rooms = [{"template": "living", "preset": "comfort",
              "params": {"windows": 1, "venetian_windows": 2}},
             {"template": "central", "preset": "comfort"}]
    house = rl.resolve_house(rooms, rl.load_builtin_templates(), language="ru")
    names = " ".join(o.name for o in house.objects)
    assert "ламели" in names and "блокировка" in names, "venetian slat + safety-lock not emitted"
    assert "сцена" in names and "всё выкл" in names, "central scene + all-off not emitted"

    proj = _reread(house)
    assert len(proj.gas) == len(house.objects)
    findings = (validate_naming(proj) + detect_missing_status(proj) + detect_dpt_issues(proj)
                + check_policy(proj, load_policy(None))["findings"])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    assert not errors, [(f["code"], f["address"]) for f in errors]
    assert not warnings, [(f["code"], f["address"]) for f in warnings]

    # the wind/frost safety-lock is a write-only input: INFO, never missing_status
    codes = {(f["code"]) for f in detect_missing_status(proj)}
    assert "safety_input_no_status" in codes
    assert "missing_status_address" not in codes


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  {name}: OK")
    print("test_theben_corrections: OK — relative dimming -> 3.007 (abs value stays "
          "5.001); shutter_venetian/valve/ventilation/dali/multisensor/central objects "
          "verified; airing -> hvac; venetian+central house is lint-clean; safety-lock "
          "is INFO not missing-status.")


if __name__ == "__main__":
    main()
