"""ETS6 G-File parser — parse ProjectStore G XML to structured data.

The G-File lives in ETS6 ProjectStore (e.g. P-0110/G) and contains
the authoritative group address definitions as a flat XML structure.

Addresses are stored as flat integers:
  3-level = main/middle/sub  →  flat = main*2048 + middle*256 + sub
"""

import xml.etree.ElementTree as ET
from typing import Optional


def flat_to_3level(flat: int) -> str:
    """Convert flat KNX address to 3-level Main/Middle/Sub string.

    Args:
        flat: Integer address from ETS6 G-File.

    Returns:
        3-level address string like "1/1/0".

    Examples:
        >>> flat_to_3level(1)
        '0/0/1'
        >>> flat_to_3level(2304)
        '1/1/0'
    """
    main = flat // 2048
    middle = (flat % 2048) // 256
    sub = flat % 256
    return f"{main}/{middle}/{sub}"


def parse_gfile(xml_text: str) -> list[dict]:
    """Parse ETS6 G-File XML and return list of group address records.

    Args:
        xml_text: Raw XML content of the G-File (UTF-8 with optional BOM).

    Returns:
        List of dicts with keys: address, flat, name, dpt, id, groups.
        ``groups`` is a list of parent group names (hierarchical path).

    Example output:
        [{'address': '0/0/1', 'flat': 1, 'name': 'Zeit',
          'dpt': 'DPST-10-1', 'id': 'P-0110-0_GA-1',
          'groups': ['Zentralfunktionen', 'Datum und Zeit']}]
    """
    # Strip BOM if present
    if xml_text.startswith('\ufeff'):
        xml_text = xml_text[1:]

    root = ET.fromstring(xml_text)
    gas = []

    # Build group hierarchy while traversing
    for ga in root.iter('GA'):
        flat = int(ga.get('Address', '0'))
        name = ga.get('Name', '')
        dpt = ga.get('DatapointType', '')
        gaid = ga.get('Id', '')

        # Collect parent group names
        groups = []
        parent = ga
        while True:
            # Find parent GR element
            for ancestor in root.iter():
                if list(ancestor).count(parent) > 0 or parent in ancestor:
                    # Found the direct parent of 'parent'
                    if ancestor.tag == 'GR':
                        groups.insert(0, ancestor.get('Name', ''))
                        parent = ancestor
                        break
            else:
                break
            if parent is None or parent.tag != 'GR':
                break
            # Find the parent of this GR
            for ancestor in root.iter('GR'):
                if parent in list(ancestor):
                    parent = ancestor
                    groups.insert(0, ancestor.get('Name', ''))
                    break
            else:
                break
            break  # Simple 2-level hierarchy for now

        # Simpler approach: traverse GR hierarchy
        gr_parents = []
        for gr in root.iter('GR'):
            for child in gr:
                if child == ga or (child.tag == 'GR' and ga in child.iter()):
                    gr_parents = [gr.get('Name', '')]
                    # Check if this GR is nested in another GR
                    for outer_gr in root.iter('GR'):
                        if gr in list(outer_gr):
                            gr_parents.insert(0, outer_gr.get('Name', ''))
                    break

        gas.append({
            'address': flat_to_3level(flat),
            'flat': flat,
            'name': name,
            'dpt': dpt,
            'id': gaid,
            'groups': gr_parents,
        })

    return gas


def diff_gfile_vs_knxproj(
    gfile_gas: list[dict],
    knxproj_gas: list[dict],
) -> dict:
    """Compare G-File GAs with .knxproj GAs and report differences.

    Args:
        gfile_gas: List of GA dicts from parse_gfile().
        knxproj_gas: List of GA dicts from nickol-knx list_group_addresses().

    Returns:
        Dict with keys: only_in_gfile, only_in_knxproj, renamed, dpt_changed.
    """
    gfile_addrs = {g['address'] for g in gfile_gas}
    knx_addrs = {g['address'] for g in knxproj_gas}

    result = {
        'only_in_gfile': sorted(gfile_addrs - knx_addrs),
        'only_in_knxproj': sorted(knx_addrs - gfile_addrs),
        'renamed': {},
        'dpt_changed': {},
    }

    gfile_map = {g['address']: g for g in gfile_gas}
    knx_map = {g['address']: g for g in knxproj_gas}

    for addr in gfile_addrs & knx_addrs:
        g = gfile_map[addr]
        k = knx_map[addr]
        if g.get('name') != k.get('name'):
            result['renamed'][addr] = {
                'gfile': g.get('name'),
                'knxproj': k.get('name'),
            }
        if g.get('dpt', '').replace('DPST-', '') != k.get('dpt', '').replace('DPST-', ''):
            result['dpt_changed'][addr] = {
                'gfile': g.get('dpt'),
                'knxproj': k.get('dpt'),
            }

    return result
