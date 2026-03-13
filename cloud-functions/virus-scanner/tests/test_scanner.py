"""
Unit tests for the ClamAV scanner wrapper.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scanner import ScanResult, _parse_threat, scan_file


class TestParseThreat:
    def test_parses_standard_clamav_output(self):
        output = "/tmp/test.pdf: Eicar-Signature FOUND"
        assert _parse_threat(output) == "Eicar-Signature"

    def test_parses_multiline_output(self):
        output = "/tmp/test.pdf: OK\n/tmp/bad.exe: Win.Trojan.Agent FOUND"
        assert _parse_threat(output) == "Win.Trojan.Agent"

    def test_returns_unknown_when_unparseable(self):
        assert _parse_threat("something weird") == "UNKNOWN_THREAT"

    def test_trims_whitespace(self):
        output = "/tmp/f.pdf:  Eicar-Test-Signature FOUND"
        result = _parse_threat(output)
        assert "FOUND" not in result
        assert result.strip() == result


class TestScanFile:
    def test_clean_file_returns_is_clean_true(self, tmp_path):
        test_file = tmp_path / "clean.pdf"
        test_file.write_text("not a virus")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/tmp/clean.pdf: OK\n"
        mock_result.stderr = ""

        with patch("scanner.subprocess.run", return_value=mock_result):
            result = scan_file(str(test_file))

        assert result.is_clean is True
        assert result.threat is None

    def test_infected_file_returns_is_clean_false(self, tmp_path):
        test_file = tmp_path / "bad.pdf"
        test_file.write_text("eicar test")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "/tmp/bad.pdf: Eicar-Signature FOUND\n"
        mock_result.stderr = ""

        with patch("scanner.subprocess.run", return_value=mock_result):
            result = scan_file(str(test_file))

        assert result.is_clean is False
        assert result.threat == "Eicar-Signature"

    def test_scan_error_returns_is_clean_false(self, tmp_path):
        test_file = tmp_path / "file.pdf"
        test_file.write_text("data")

        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = ""
        mock_result.stderr = "Can't access file\n"

        with patch("scanner.subprocess.run", return_value=mock_result):
            result = scan_file(str(test_file))

        assert result.is_clean is False
        assert result.threat == "SCAN_ERROR"

    def test_clamscan_not_found_returns_scanner_unavailable(self, tmp_path):
        test_file = tmp_path / "file.pdf"
        test_file.write_text("data")

        with patch("scanner.subprocess.run", side_effect=FileNotFoundError):
            result = scan_file(str(test_file))

        assert result.is_clean is False
        assert result.threat == "SCANNER_UNAVAILABLE"

    def test_timeout_returns_scan_timeout(self, tmp_path):
        test_file = tmp_path / "huge.bin"
        test_file.write_bytes(b"\x00" * 100)

        with patch("scanner.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="clamscan", timeout=120)):
            result = scan_file(str(test_file))

        assert result.is_clean is False
        assert result.threat == "SCAN_TIMEOUT"

    def test_raw_output_captured(self, tmp_path):
        test_file = tmp_path / "file.pdf"
        test_file.write_text("data")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "detailed output here\n"
        mock_result.stderr = ""

        with patch("scanner.subprocess.run", return_value=mock_result):
            result = scan_file(str(test_file))

        assert "detailed output here" in result.raw_output
