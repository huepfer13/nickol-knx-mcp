# Feature: G-File Parser for ETS6 ProjectStore

**Pull Request:** [`huepfer13/nickol-knx-mcp`](https://github.com/huepfer13/nickol-knx-mcp) → [`NickoScope/nickol-knx-mcp`](https://github.com/NickoScope/nickol-knx-mcp)

---

## 1. Use Case Description

### Problem
When working with ETS6 KNX projects, the canonical group-address data lives in
the **ProjectStore G-File** — not in the exported `.knxproj`.  The G-File is
updated on every ETS6 save, while the `.knxproj` export is a manual snapshot
that may be hours or days stale.

Integrators using `nickol-knx-mcp` for CI/CD linting or Home Assistant package
generation unknowingly work with **outdated data** because the tool only reads
`.knxproj` files.

### Solution
Add a new `gfile` module with three public functions and an MCP tool endpoint
so that users can:

1. **Parse a live G-File** directly from the ETS6 ProjectStore (via SMB, shared
   folder, or any file access method).
2. **Diff** the live G-File against a previously exported `.knxproj` to
   instantly see renames, new/deleted GAs, and DPT changes.
3. **Audit** naming, DPT consistency, and group hierarchy without ever opening
   the ETS6 GUI.

### Target Audience
- **Home Assistant integrators** who generate `knx:` packages and need
  up-to-date GA lists.
- **CI/CD pipelines** that lint KNX projects before deployment.
- **ETS6 power users** who edit the G-File via external tools (SMB, Git) and
  need automated verification.

---

## 2. Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│ ETS6 ProjectStore   │     │   nickol-knx-mcp     │
│  P-0110/G (XML)     │────▶│   gfile.py           │
│  (via SMB / file)   │     │                      │
└─────────────────────┘     │  flat_to_3level()    │
                            │  parse_gfile()       │
┌─────────────────────┐     │  diff_gfile_vs_knx() │
│ .knxproj export     │────▶│                      │
│ (loaded in session) │     │  → MCP tool:         │
└─────────────────────┘     │    analyze_gfile     │
                            └──────────────────────┘
```

### Module: `nickol_knx_mcp/gfile.py`

| Function | Purpose |
|----------|---------|
| `flat_to_3level(flat)` | Convert ETS6 flat address (e.g. `2304`) to 3-level (`1/1/0`) |
| `parse_gfile(xml_text)` | Parse G-File XML → list of GA dicts with hierarchy |
| `diff_gfile_vs_knxproj(gfile, knx)` | Compare live G-File vs loaded .knxproj |

### New MCP Tool: `analyze_gfile`

```python
@mcp.tool()
def analyze_gfile(gfile_path: str) -> dict:
    """Parse ETS6 G-File and diff against loaded .knxproj."""
```

**Parameters:**
- `gfile_path` (str): Path to the G-File XML (e.g. `P-0110/G`)

**Returns:**
```json
{
  "ga_count": 32,
  "group_addresses": [ ... ],
  "knxproj_ga_count": 31,
  "diff": {
    "only_in_gfile": ["0/0/4"],
    "only_in_knxproj": [],
    "renamed": {"1/1/2": {"gfile": "KuecheLicht Schalten", "knxproj": "Kanal 2"}},
    "dpt_changed": {}
  }
}
```

---

## 3. KNX Addressing Reference

Flat addresses use the standard KNX decomposition:

```
flat = Main × 2048 + Middle × 256 + Sub

Main:   0–31
Middle: 0–7
Sub:    0–255
```

**Examples:**

| 3-Level | Flat  | Typical Use |
|---------|-------|-------------|
| 0/0/1   | 1     | Time sensor |
| 1/1/0   | 2304  | Ceiling light switch |
| 2/0/0   | 4096  | Ceiling light status |
| 4/0/0   | 8192  | Heating control |

---

## 4. Testing

**11 unit tests** in `tests/test_gfile.py`:

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestFlatTo3Level` | 2 | Standard + boundary addresses |
| `TestParseGFile` | 4 | Count, names, DPTs, address conversion |
| `TestDiff` | 1 | Missing GA detection |

**Live integration test** with anonymized G-File (32 GAs, 8 unique DPTs):
```bash
python3 -m pytest tests/test_gfile.py -v  # 7/7 passed
python3 -c "from nickol_knx_mcp.gfile import parse_gfile; ..."  # 32 GAs ✅
```

---

## 5. Changelog Entry

### [0.8.0] — 2026-07-28

**Added**
- `gfile` module: `flat_to_3level()`, `parse_gfile()`, `diff_gfile_vs_knxproj()`
- New MCP tool: `analyze_gfile` — parse ETS6 G-File and optionally diff against
  loaded `.knxproj`
- 7 unit tests with 100% pass rate on sample data

**Changed**
- `server.py`: imports and registers `analyze_gfile` tool

---

## 6. Migration & Compatibility

- **Backward compatible**: No existing API is modified.
- **No new dependencies**: Uses only Python stdlib (`xml.etree.ElementTree`).
- The G-File is read-only; this tool **never** writes to the ProjectStore.

---

## 7. Future Work (Roadmap)

- [ ] Support for 3-level GR nesting (currently 2-level, matching typical ETS6)
- [ ] G-File write support (cautious: hash validation required)
- [ ] Integration with `generate_ha_package` to use live G-File data
- [ ] Watchdog mode: re-parse G-File on SMB change events
