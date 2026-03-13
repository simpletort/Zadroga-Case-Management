"""
ClamAV wrapper — runs clamscan on a local file path.

The Cloud Function container image installs ClamAV and bakes in an up-to-date
virus database at build time (see Dockerfile).  The freshclam daemon is NOT
run at runtime to keep cold-start latency low; definitions are refreshed
during each container build via Cloud Build.

Returns a ScanResult namedtuple:
    is_clean  (bool)   — True if no threats found
    raw_output (str)   — full clamscan stdout / stderr
    threat     (str|None) — threat name if infected, else None
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CLAMSCAN_BINARY = shutil.which("clamscan") or "/usr/bin/clamscan"


@dataclass
class ScanResult:
    is_clean: bool
    raw_output: str
    threat: str | None = None


def scan_file(file_path: str | Path) -> ScanResult:
    """
    Invoke clamscan on *file_path* and return a ScanResult.

    clamscan exit codes:
        0 — no virus found
        1 — virus(es) found
        2 — error
    """
    path = str(file_path)
    logger.info("Starting ClamAV scan: %s", path)

    try:
        result = subprocess.run(
            [CLAMSCAN_BINARY, "--no-summary", path],
            capture_output=True,
            text=True,
            timeout=120,    # 2-minute hard limit; large files are flagged as error
        )
    except FileNotFoundError:
        logger.error("clamscan binary not found at %s", CLAMSCAN_BINARY)
        return ScanResult(is_clean=False, raw_output="clamscan not found", threat="SCANNER_UNAVAILABLE")
    except subprocess.TimeoutExpired:
        logger.error("clamscan timed out on %s", path)
        return ScanResult(is_clean=False, raw_output="scan timed out", threat="SCAN_TIMEOUT")

    output = (result.stdout + result.stderr).strip()
    logger.info("clamscan exit=%d output=%r", result.returncode, output)

    if result.returncode == 0:
        return ScanResult(is_clean=True, raw_output=output)

    if result.returncode == 1:
        # Parse threat name from line like: "/tmp/file.pdf: Eicar-Signature FOUND"
        threat = _parse_threat(output)
        logger.warning("Threat detected in %s: %s", path, threat)
        return ScanResult(is_clean=False, raw_output=output, threat=threat)

    # returncode == 2 — scan error
    logger.error("clamscan error (exit=2) on %s: %s", path, output)
    return ScanResult(is_clean=False, raw_output=output, threat="SCAN_ERROR")


def _parse_threat(output: str) -> str:
    """
    Extract the threat name from clamscan output.
    Example line: "/tmp/test.pdf: Eicar-Signature FOUND"
    Returns the threat name or "UNKNOWN_THREAT" if unparseable.
    """
    for line in output.splitlines():
        if "FOUND" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                # second part looks like " Eicar-Signature FOUND"
                return parts[-1].replace("FOUND", "").strip()
    return "UNKNOWN_THREAT"
