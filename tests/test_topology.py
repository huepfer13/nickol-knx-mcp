"""Topology / individual-address checks (detect_topology_issues).

Grounded in the KNX standard: individual address = area(0-15).line(0-15).device
(0-255), device 0 = coupler (confirmed via xknx IndividualAddress, deepwiki
XKNX/xknx); TP1 segment holds 64 devices, a line up to 256 (KNX Handbook).
"""
from nickol_knx_mcp.project import build_loaded_from_raw
from nickol_knx_mcp.analyze import detect_topology_issues


def _dev(ia, name="Dev"):
    return {"name": name, "individual_address": ia, "order_number": "X",
            "manufacturer_name": "M", "hardware_name": "", "description": "",
            "application": None, "project_uid": None,
            "communication_object_ids": [], "channels": {}}


def _proj(devices, topology):
    raw = {"info": {"group_address_style": "ThreeLevel", "schema_version": "21"},
           "group_addresses": {}, "communication_objects": {},
           "devices": devices, "functions": {}, "topology": topology,
           "group_ranges": {}}
    return build_loaded_from_raw(raw, "t.knxproj")


def _codes(findings):
    return {f["code"] for f in findings}


def test_segment_limit_over_64_is_info():
    devs = [f"1.1.{i}" for i in range(1, 71)]  # 70 devices on one line
    devices = {ia: _dev(ia) for ia in devs}
    topology = {"1": {"name": "Area 1",
                      "lines": {"1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)",
                                        "devices": devs}}}}
    findings = detect_topology_issues(_proj(devices, topology))
    seg = [f for f in findings if f["code"] == "topology_segment_limit"]
    assert seg and seg[0]["severity"] == "info", findings
    assert seg[0]["device_count"] == 70
    # 70 <= 256 so it must NOT also raise a line overflow
    assert "topology_line_overflow" not in _codes(findings)


def test_invalid_individual_address_is_warning():
    # area 16 is out of range (max 15)
    devices = {"bad": _dev("16.0.1", "Rogue"), "1.1.1": _dev("1.1.1", "Ok")}
    topology = {"1": {"name": "Area 1",
                      "lines": {"1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)",
                                        "devices": ["1.1.1"]}}}}
    findings = detect_topology_issues(_proj(devices, topology))
    inv = [f for f in findings if f["code"] == "invalid_individual_address"]
    assert len(inv) == 1 and inv[0]["severity"] == "warning", findings
    assert inv[0]["address"] == "16.0.1"


def test_duplicate_individual_address_is_error():
    devices = {"a": _dev("1.1.5", "First"), "b": _dev("1.1.5", "Second")}
    topology = {"1": {"name": "Area 1",
                      "lines": {"1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)",
                                        "devices": ["1.1.5"]}}}}
    findings = detect_topology_issues(_proj(devices, topology))
    dup = [f for f in findings if f["code"] == "duplicate_individual_address"]
    assert len(dup) == 1 and dup[0]["severity"] == "error", findings
    assert dup[0]["address"] == "1.1.5"


def test_valid_small_project_is_clean():
    # single line, valid addresses, well under capacity -> no findings at all
    devs = ["1.1.1", "1.1.2", "1.1.3"]
    devices = {ia: _dev(ia) for ia in devs}
    topology = {"1": {"name": "Area 1",
                      "lines": {"1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)",
                                        "devices": devs}}}}
    findings = detect_topology_issues(_proj(devices, topology))
    assert findings == [], findings


def test_empty_topology_and_no_devices_returns_empty():
    assert detect_topology_issues(_proj({}, {})) == []


def test_multiline_without_coupler_is_info_but_singleline_is_clean():
    # two TP lines, neither has a .0 coupler device -> info per line
    devices = {"1.1.1": _dev("1.1.1"), "1.2.1": _dev("1.2.1")}
    topology = {"1": {"name": "Area 1", "lines": {
        "1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)", "devices": ["1.1.1"]},
        "1.2": {"name": "Line 2", "medium_type": "Twisted Pair (TP)", "devices": ["1.2.1"]},
    }}}
    findings = detect_topology_issues(_proj(devices, topology))
    coupler = [f for f in findings if f["code"] == "line_without_coupler"]
    assert len(coupler) == 2 and all(f["severity"] == "info" for f in coupler), findings

    # a line WITH a .0 coupler is not flagged
    devices2 = {"1.1.0": _dev("1.1.0", "Coupler"), "1.1.1": _dev("1.1.1"),
                "1.2.0": _dev("1.2.0", "Coupler2"), "1.2.1": _dev("1.2.1")}
    topology2 = {"1": {"name": "Area 1", "lines": {
        "1.1": {"name": "Line 1", "medium_type": "Twisted Pair (TP)", "devices": ["1.1.0", "1.1.1"]},
        "1.2": {"name": "Line 2", "medium_type": "Twisted Pair (TP)", "devices": ["1.2.0", "1.2.1"]},
    }}}
    findings2 = detect_topology_issues(_proj(devices2, topology2))
    assert "line_without_coupler" not in _codes(findings2), findings2


def test_ip_line_is_not_flagged_regression():
    """xknxproject reports the full medium string ('KNXnet/IP (IP)'), not 'IP'.
    An IP backbone/main line must NOT get TP1 findings: no segment/line-capacity
    note and no line_without_coupler (couplers-on-.0 is a TP concept)."""
    # IP line with 100 devices and no .0 coupler + a TP line over 64
    ip_devs = [f"1.0.{i}" for i in range(1, 101)]      # 100 on the IP main line
    tp_devs = [f"1.1.{i}" for i in range(1, 71)]       # 70 on a TP line
    devices = {ia: _dev(ia) for ia in ip_devs + tp_devs}
    topology = {"1": {"name": "Area 1", "lines": {
        "1.0": {"name": "Main", "medium_type": "KNXnet/IP (IP)", "devices": ip_devs},
        "1.1": {"name": "TP line", "medium_type": "Twisted Pair (TP)", "devices": tp_devs},
    }}}
    findings = detect_topology_issues(_proj(devices, topology))
    # The IP line (1.0) must appear in NO topology finding.
    for f in findings:
        assert f.get("line") != "1.0", f
    # The TP line (1.1) still gets its segment note + coupler note.
    assert "topology_segment_limit" in _codes(findings)
    seg = [f for f in findings if f["code"] == "topology_segment_limit"]
    assert all(f["line"] == "1.1" for f in seg), seg
    assert "line_without_coupler" in _codes(findings)  # 1.1 has no .0 coupler


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("test_topology: OK")
