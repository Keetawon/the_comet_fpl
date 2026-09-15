"""Check the original research source after the owner's narrow runtime-wrapper adoption."""

import hashlib
import subprocess


def assert_minutes_reference_sources(root, contract):
    for name, expected in contract["unchanged_source_sha256"].items():
        if name == "src/fpl/jobs/prospective_points_v1.py":
            # The operational wrapper may now select SDP. The frozen research pin remains
            # the exact original Windows checkout at the contract's immutable base revision.
            # No result/config pin is updated to the newly adopted wrapper.
            blob = subprocess.check_output(
                ["git", "show", f"{contract['base_revision']}:{name}"], cwd=root
            )
            assert hashlib.sha256(blob).hexdigest() == (
                "42798fc73389f12ecdc516b0b3dc8e2a08a1984fc50dbf45132ef5937971f80c"
            )
            retained_windows_bytes = blob.replace(b"\n", b"\r\n")
            assert hashlib.sha256(retained_windows_bytes).hexdigest() == expected
        else:
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
