"""
tests/unit/test_partner_auth.py — Unit tests for API key auth utilities.
"""
from __future__ import annotations
import hashlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))

import pytest
from middleware.partner_auth import _hash_key, _ip_allowed


class TestHashKey:
    def test_produces_64_char_hex(self):
        h = _hash_key("zad_testkey123")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        assert _hash_key("key") == _hash_key("key")

    def test_different_inputs_different_hashes(self):
        assert _hash_key("key1") != _hash_key("key2")

    def test_matches_sha256(self):
        key = "zad_abc123"
        expected = hashlib.sha256(key.encode()).hexdigest()
        assert _hash_key(key) == expected


class TestIpAllowlist:
    def test_empty_allowlist_permits_all(self):
        assert _ip_allowed("1.2.3.4", []) is True
        assert _ip_allowed("192.168.1.1", []) is True

    def test_exact_match_permitted(self):
        assert _ip_allowed("1.2.3.4", ["1.2.3.4"]) is True

    def test_non_matching_ip_blocked(self):
        assert _ip_allowed("1.2.3.5", ["1.2.3.4"]) is False

    def test_cidr_range_permitted(self):
        assert _ip_allowed("192.168.1.50", ["192.168.1.0/24"]) is True

    def test_cidr_range_outside_blocked(self):
        assert _ip_allowed("192.168.2.1", ["192.168.1.0/24"]) is False

    def test_multiple_entries_one_match(self):
        assert _ip_allowed("10.0.0.5", ["192.168.1.1", "10.0.0.0/8"]) is True

    def test_invalid_ip_returns_false(self):
        assert _ip_allowed("not.an.ip", ["192.168.1.1"]) is False

    def test_ipv6_exact_match(self):
        assert _ip_allowed("::1", ["::1"]) is True

    def test_multiple_ips_none_match(self):
        assert _ip_allowed("8.8.8.8", ["1.1.1.1", "2.2.2.2"]) is False
