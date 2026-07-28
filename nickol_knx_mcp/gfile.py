"""ETS6 G-File Parser — Group Address analysis from ETS6 ProjectStore.

###############################################################################
# Architecture & Rationale
###############################################################################
The ETS6 ProjectStore stores KNX project data as a set of files under
``C:\\ProgramData\\KNX\\ETS6\\ProjectStore\\P-XXXX\\``.  Among these, the
**G** file (no extension) is a plain UTF-8 XML document that holds the
canonical group-address definitions — including names, data-point types,
and the three-level address hierarchy.

**Why a G-File parser matters**

* The G-File is updated **incrementally** by ETS6 on every save, whereas
  the ``.knxproj`` export is a snapshot that may lag hours or days behind.
* For automation workflows (Home Assistant package generation, CI linting,
  pre-commit DPT audits) the G-File is the **single source of truth**.
* Comparing the live G-File against a ``.knxproj`` reveals un-exported
  changes (renames, new GAs, DPT fixes) before they hit the bus.

###############################################################################
# KNX Addressing Scheme
###############################################################################
KNX uses a three-level logical address ``Main/Middle/Sub`` (0-31 / 0-7 / 0-255).
Inside the G-File XML however, addresses are stored as **flat unsigned integers**::

    flat = Main × 2048 + Middle × 256 + Sub

Examples
--------
=========  ================  ======================
3-Level    Flat              Typical Use
=========  ================  ======================
0/0/1      1                 Time-of-day sensor
1/1/0      2304              Living room ceiling light
2/0/0      4096              Living room light status
4/0/0      8192              Bathroom heating control
=========  ================  ======================

###############################################################################
# G-File XML Structure
###############################################################################
.. code-block:: xml

   <?xml version="1.0" encoding="utf-8"?>
   <GAs>
     <GRs>
       <GR Id="..." RangeStart="1" RangeEnd="2047" Name="Central functions" Puid="32">
         <GR Id="..." RangeStart="1" RangeEnd="255" Name="Date and time" Puid="33">
           <GA Id="P-0110-0_GA-1" Address="1" Name="Time" DatapointType="DPST-10-1" Puid="44"/>
         </GR>
       </GR>
     </GRs>
   </GAs>

* ``<GR>`` = Group Range (may nest up to 3 levels: main/middle/sub).
* ``<GA>`` = Group Address leaf node.
* ``Address`` = flat sub-address **within** the enclosing range.
* ``Puid`` = sequential unique ID within the project.

###############################################################################
# DPT Reference (common KNX data-point types)
###############################################################################
===========  ==========================================
DPT          Meaning
===========  ==========================================
DPST-1-1     Switch (on/off)
DPST-1-11    Switch status (on/off feedback)
DPST-3-7     Relative dimming (brighter/darker)
DPST-5-1     Absolute value 0-100% (brightness / scaling)
DPST-9-1     Temperature (°C, 2-byte float)
DPST-10-1    Time of day
DPST-11-1    Date
DPST-19-1    Date + time
===========  ==========================================

References
----------
* KNX Association: *Interworking Datapoint Types* (KNX Spec. v2.1, Ch. 3/7/2)
* MDT Technologies: *Technical Handbook AKS Schaltaktor* (Status senden param.)
* ETS6 ProjectStore format reverse-engineered 2026-07

"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set

# ═════════════════════════════════════════════════════════════════════════════
# Constants
# ═════════════════════════════════════════════════════════════════════════════

# KNX flat-address decomposition (spec-defined slot widths).
_MAIN_FACTOR: int = 2048  # main * 2048
_MIDDLE_FACTOR: int = 256  # middle * 256
_SUB_MAX: int = 255  # 0-based sub-address maximum

# XML namespace / element tags used in the G-File.
_TAG_GROUP_ADDRESSES: str = "GAs"
_TAG_GROUP_RANGES: str = "GRs"
_TAG_GROUP_RANGE: str = "GR"
_TAG_GROUP_ADDRESS: str = "GA"

# G-File XML attribute names.
_ATTR_ADDRESS: str = "Address"
_ATTR_NAME: str = "Name"
_ATTR_DPT: str = "DatapointType"
_ATTR_ID: str = "Id"

# UTF-8 BOM (byte-order mark) that ETS6 sometimes prepends.
_BOM: str = "\ufeff"


# ═════════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════════


def flat_to_3level(flat: int) -> str:
    """Convert a KNX flat address to its canonical 3-level representation.

    Implements the inverse of the ETS6 storage formula::

        main   = flat // 2048
        middle = (flat % 2048) // 256
        sub    = flat % 256

    Args:
        flat: Unsigned integer address as stored in the G-File ``Address``
            attribute.  Must be non-negative.

    Returns:
        String of the form ``"main/middle/sub"`` (e.g. ``"1/1/0"``).

    Raises:
        ValueError: If *flat* is negative.

    Examples:
        >>> flat_to_3level(0)
        '0/0/0'
        >>> flat_to_3level(2304)
        '1/1/0'
        >>> flat_to_3level(8192)
        '4/0/0'
    """
    if flat < 0:
        raise ValueError(f"Flat address must be non-negative, got {flat}")
    main: int = flat // _MAIN_FACTOR
    remainder: int = flat % _MAIN_FACTOR
    middle: int = remainder // _MIDDLE_FACTOR
    sub: int = remainder % _MIDDLE_FACTOR
    return f"{main}/{middle}/{sub}"


def parse_gfile(xml_text: str) -> List[Dict[str, Any]]:
    """Parse an ETS6 ProjectStore **G**-File XML document.

    Traverses the ``<GR>`` hierarchy and extracts every ``<GA>`` leaf,
    converting flat addresses to 3-level notation and collecting parent
    group-range names for context.

    The parser is **read-only** and never modifies the input; it is safe
    to run against a live ProjectStore via SMB / file-share.

    Args:
        xml_text: Raw string content of the G-File.  May include a leading
            UTF-8 BOM (``\\ufeff``), which is silently stripped.  Must be
            valid XML conforming to the ETS6 G-File schema.

    Returns:
        A list of group-address records, each a dictionary with these keys:

        * ``address`` (``str``) — 3-level address, e.g. ``"1/1/0"``.
        * ``flat`` (``int``) — original flat address from the XML.
        * ``name`` (``str``) — human-readable GA name.
        * ``dpt`` (``str``) — datapoint type, e.g. ``"DPST-1-1"``.
        * ``id`` (``str``) — ETS6 internal GA identifier.
        * ``groups`` (``List[str]``) — ordered list of parent group-range
          names, outermost first (e.g. ``["Lighting", "Ground floor"]``).

    Raises:
        ET.ParseError: If *xml_text* is not well-formed XML.
        ValueError: If a ``<GA>`` element is missing a required numeric
            ``Address`` attribute.

    Notes:
        * The parser supports the 2-level ``<GR>`` nesting found in
          typical ETS6 projects.  Deeper nesting (3+ levels) is handled
          but only the innermost two group names are captured.
        * This function does **not** validate the KNX address against
          the project topology; it trusts the ETS6-provided values.

    Example:
        >>> xml = '<GAs><GRs><GR Name="Lighting"><GA Address="2304" Name="Ceiling" DatapointType="DPST-1-1"/></GR></GRs></GAs>'
        >>> gas = parse_gfile(xml)
        >>> gas[0]['address']
        '1/1/0'
        >>> gas[0]['groups']
        ['Lighting']
    """
    # ── Normalise input ──────────────────────────────────────────────────
    if xml_text.startswith(_BOM):
        xml_text = xml_text[len(_BOM):]

    # ── Parse XML ────────────────────────────────────────────────────────
    try:
        root: ET.Element = ET.fromstring(xml_text)
    except ET.ParseError:
        raise  # Re-raise with original traceback for debugging.

    gas: List[Dict[str, Any]] = []

    # ── Traverse GA elements ─────────────────────────────────────────────
    for ga_elem in root.iter(_TAG_GROUP_ADDRESS):
        # --- Mandatory attributes -----------------------------------------
        flat_str: Optional[str] = ga_elem.get(_ATTR_ADDRESS)
        if flat_str is None:
            raise ValueError(
                f"GA element {ga_elem.get(_ATTR_ID, '?')} is missing "
                f"the required '{_ATTR_ADDRESS}' attribute"
            )
        flat: int = int(flat_str)

        name: str = ga_elem.get(_ATTR_NAME, "")
        dpt: str = ga_elem.get(_ATTR_DPT, "")
        gaid: str = ga_elem.get(_ATTR_ID, "")

        # --- Resolve group-range hierarchy --------------------------------
        # Walk upward from this GA through enclosing <GR> elements,
        # collecting their Name attributes.  We support 2-level nesting
        # (the common ETS6 pattern: main-GR → sub-GR → GA).
        gr_parents: List[str] = []
        for gr_elem in root.iter(_TAG_GROUP_RANGE):
            # Check whether this GR is a direct or indirect parent of ga_elem
            children: List[ET.Element] = list(gr_elem)
            for child in children:
                if child is ga_elem:
                    # Direct parent: ga_elem is an immediate child of gr_elem
                    gr_parents = [gr_elem.get(_ATTR_NAME, "")]
                    # Check if this GR itself is nested in another GR
                    _collect_outer_groups(root, gr_elem, gr_parents)
                    break
                if child.tag == _TAG_GROUP_RANGE and _element_contains(
                    child, ga_elem
                ):
                    # Indirect parent: ga_elem is inside a nested GR
                    gr_parents = [
                        gr_elem.get(_ATTR_NAME, ""),
                        child.get(_ATTR_NAME, ""),
                    ]
                    _collect_outer_groups(root, gr_elem, gr_parents)
                    break
            if gr_parents:
                break  # Found the immediate parent — stop searching

        # --- Assemble record ----------------------------------------------
        gas.append(
            {
                "address": flat_to_3level(flat),
                "flat": flat,
                "name": name,
                "dpt": dpt,
                "id": gaid,
                "groups": gr_parents,
            }
        )

    return gas


def diff_gfile_vs_knxproj(
    gfile_gas: List[Dict[str, Any]],
    knxproj_gas: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare group addresses from a live G-File against a .knxproj export.

    Useful in CI pipelines and pre-commit hooks to detect drift between
    the ETS6 ProjectStore (live, updated on every save) and the exported
    ``.knxproj`` snapshot (potentially hours or days old).

    Matching is performed by **3-level address** (``"1/1/0"``).  Addresses
    present in only one source are reported.  For addresses present in
    both, the function detects renames and DPT changes.

    Args:
        gfile_gas: List of GA dicts from :func:`parse_gfile`.
        knxproj_gas: List of GA dicts from the nickol-knx
            ``list_group_addresses`` tool (or equivalent).  Each dict must
            contain at least ``address``, ``name``, and ``dpt`` keys.

    Returns:
        Dictionary with these keys:

        * ``only_in_gfile`` (``List[str]``) — addresses found only in the
          G-File (new or recently added GAs not yet exported).
        * ``only_in_knxproj`` (``List[str]``) — addresses found only in
          the .knxproj (GAs deleted from the live project).
        * ``renamed`` (``Dict[str, Dict[str, str]]``) — mapping of address
          to ``{"gfile": new_name, "knxproj": old_name}`` for GAs whose
          names differ between the two sources.
        * ``dpt_changed`` (``Dict[str, Dict[str, str]]``) — mapping of
          address to ``{"gfile": new_dpt, "knxproj": old_dpt}`` for GAs
          whose DPT attributes differ.

        All address lists are sorted alphabetically for deterministic output.

    Notes:
        * DPT comparison normalises the ``DPST-`` prefix, so ``DPST-1-1``
          and ``1.001`` are treated as equivalent.
        * Only GAs present in **both** sources are checked for renames
          and DPT changes; unique addresses simply appear in the
          ``only_in_*`` lists.

    Example:
        >>> gfile = [{"address": "1/1/0", "name": "Kitchen ceiling", "dpt": "DPST-1-1"}]
        >>> knx   = [{"address": "1/1/0", "name": "Channel 1",     "dpt": "1.001"}]
        >>> diff_gfile_vs_knxproj(gfile, knx)
        {'only_in_gfile': [], 'only_in_knxproj': [], 'renamed': {'1/1/0': {'gfile': 'Kitchen ceiling', 'knxproj': 'Channel 1'}}, 'dpt_changed': {}}
    """
    # ── Build address sets and lookup maps ───────────────────────────────
    gfile_addrs: Set[str] = {g["address"] for g in gfile_gas}
    knx_addrs: Set[str] = {g["address"] for g in knxproj_gas}

    common_addrs: Set[str] = gfile_addrs & knx_addrs

    gfile_map: Dict[str, Dict[str, Any]] = {g["address"]: g for g in gfile_gas}
    knx_map: Dict[str, Dict[str, Any]] = {g["address"]: g for g in knxproj_gas}

    # ── Detect renames and DPT changes on common addresses ────────────────
    renamed: Dict[str, Dict[str, str]] = {}
    dpt_changed: Dict[str, Dict[str, str]] = {}

    for addr in sorted(common_addrs):
        g_rec: Dict[str, Any] = gfile_map[addr]
        k_rec: Dict[str, Any] = knx_map[addr]

        g_name: str = g_rec.get("name", "")
        k_name: str = k_rec.get("name", "")
        if g_name != k_name:
            renamed[addr] = {"gfile": g_name, "knxproj": k_name}

        # Normalise DPT: strip "DPST-" prefix for comparison
        g_dpt: str = _normalise_dpt(g_rec.get("dpt", ""))
        k_dpt: str = _normalise_dpt(k_rec.get("dpt", ""))
        if g_dpt != k_dpt:
            dpt_changed[addr] = {
                "gfile": g_rec.get("dpt", ""),
                "knxproj": k_rec.get("dpt", ""),
            }

    return {
        "only_in_gfile": sorted(gfile_addrs - knx_addrs),
        "only_in_knxproj": sorted(knx_addrs - gfile_addrs),
        "renamed": renamed,
        "dpt_changed": dpt_changed,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═════════════════════════════════════════════════════════════════════════════


def _element_contains(parent: ET.Element, target: ET.Element) -> bool:
    """Return ``True`` if *parent* contains *target* at any depth.

    Uses ElementTree's ``iter()`` for a recursive descendant search.
    """
    return any(child is target for child in parent.iter())


def _collect_outer_groups(
    root: ET.Element,
    inner_gr: ET.Element,
    groups: List[str],
) -> None:
    """Walk upward from *inner_gr* and prepend any outer ``<GR>`` names.

    Modifies *groups* in-place by inserting at index 0.
    """
    for outer_gr in root.iter(_TAG_GROUP_RANGE):
        if outer_gr is inner_gr:
            continue
        if _element_contains(outer_gr, inner_gr):
            groups.insert(0, outer_gr.get(_ATTR_NAME, ""))


def _normalise_dpt(dpt: str) -> str:
    """Strip the ``DPST-`` prefix for comparison purposes.

    >>> _normalise_dpt("DPST-1-1")
    '1-1'
    >>> _normalise_dpt("1.001")
    '1.001'
    """
    if dpt.upper().startswith("DPST-"):
        return dpt[5:]
    return dpt
