"""Unit tests for ETS6 G-File parser module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from nickol_knx_mcp.gfile import flat_to_3level, parse_gfile, diff_gfile_vs_knxproj

G_FILE_XML = """<?xml version="1.0" encoding="utf-8"?>
<GAs>
  <GRs>
    <GR Id="P-0110-0_GR-1" RangeStart="1" RangeEnd="2047" Name="Zentralfunktionen" Puid="32">
      <GR Id="P-0110-0_GR-2" RangeStart="1" RangeEnd="255" Name="Datum und Zeit" Puid="33">
        <GA Id="P-0110-0_GA-1" Address="1" Name="Zeit" DatapointType="DPST-10-1" Puid="44"/>
        <GA Id="P-0110-0_GA-2" Address="2" Name="Datum" DatapointType="DPST-11-1" Puid="45"/>
      </GR>
    </GR>
    <GR Id="P-0110-0_GR-3" RangeStart="2048" RangeEnd="4095" Name="Beleuchtung schalten" Puid="47">
      <GR Id="P-0110-0_GR-5" RangeStart="2304" RangeEnd="2559" Name="Erdgeschoss" Puid="49">
        <GA Id="P-0110-0_GA-4" Address="2304" Name="Wohnzimmer Beleuchtung schalten" DatapointType="DPST-1-1" Puid="51"/>
        <GA Id="P-0110-0_GA-21" Address="2305" Name="Bad Beleuchtung Fenster Schalten" DatapointType="DPST-1-1" Puid="81"/>
      </GR>
    </GR>
  </GRs>
</GAs>"""

class TestFlatTo3Level:
    def test_standard(self):
        assert flat_to_3level(1) == "0/0/1"
        assert flat_to_3level(2304) == "1/1/0"
        assert flat_to_3level(4096) == "2/0/0"
    
    def test_boundaries(self):
        assert flat_to_3level(0) == "0/0/0"
        assert flat_to_3level(255) == "0/0/255"
        assert flat_to_3level(2047) == "0/7/255"
        assert flat_to_3level(2048) == "1/0/0"

class TestParseGFile:
    def test_count(self):
        gas = parse_gfile(G_FILE_XML)
        assert len(gas) == 4
    
    def test_names(self):
        gas = parse_gfile(G_FILE_XML)
        names = {g['name'] for g in gas}
        assert 'Zeit' in names
        assert 'Wohnzimmer Beleuchtung schalten' in names
    
    def test_dpts(self):
        gas = parse_gfile(G_FILE_XML)
        dpts = {g['dpt'] for g in gas}
        assert 'DPST-10-1' in dpts
        assert 'DPST-1-1' in dpts
    
    def test_addresses(self):
        gas = parse_gfile(G_FILE_XML)
        addr_map = {g['name']: g['address'] for g in gas}
        assert addr_map['Zeit'] == '0/0/1'
        assert addr_map['Wohnzimmer Beleuchtung schalten'] == '1/1/0'

class TestDiff:
    def test_missing(self):
        gfile_gas = [{'address': '1/1/0'}, {'address': '1/1/1'}, {'address': '1/1/2'}]
        knxproj_gas = [{'address': '1/1/0'}, {'address': '1/1/1'}]
        result = diff_gfile_vs_knxproj(gfile_gas, knxproj_gas)
        assert 'only_in_gfile' in result
        assert '1/1/2' in result['only_in_gfile']
