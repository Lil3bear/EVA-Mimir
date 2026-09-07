"""Tests for durable stage board landing."""

import tempfile
import unittest
from pathlib import Path

from solver.runtime.stage_board import (
    board_snapshot,
    known_host_ips,
    land_credentials,
    land_flag_progress,
    land_foothold,
    land_hosts,
    rescan_warning,
)
from solver.tools.bash_tool import _auto_extract
from solver.worker_context import RunContext, ctx


class StageBoardTests(unittest.TestCase):
    def test_land_and_snapshot(self):
        root = Path(tempfile.mkdtemp(prefix="stage-board-"))
        first = land_hosts(root, ["10.0.1.5", "10.0.1.5"])
        self.assertEqual(len(first), 1)
        self.assertEqual(land_hosts(root, ["10.0.1.5"]), [])
        land_credentials(root, ["s3cret"])
        land_flag_progress(root, correct=2, total=6, matched_index=1)
        land_foothold(root, summary="shell confirmed: uid=33(www-data)")
        snap = board_snapshot(root)
        self.assertIn("阶段看板", snap)
        self.assertIn("host=10.0.1.5", snap)
        self.assertIn("credential=s3cret", snap)
        self.assertIn("flag_progress 2/6", snap)
        self.assertIn("www-data", snap)
        self.assertEqual(known_host_ips(root), {"10.0.1.5"})

    def test_rescan_warning_after_hosts(self):
        root = Path(tempfile.mkdtemp(prefix="stage-board-"))
        land_hosts(root, ["172.18.0.9"])
        warn = rescan_warning(root, "nmap -p- 172.18.0.9")
        self.assertIn("阶段看板", warn)
        self.assertEqual(rescan_warning(root, "curl -si http://172.18.0.9/admin"), "")

    def test_auto_extract_lands_hosts_and_creds(self):
        root = Path(tempfile.mkdtemp(prefix="stage-board-auto-"))
        context = RunContext.create(str(root), "b-02", target_url="http://10.0.1.1:80")
        # challenge_dir for tools is context.challenge_dir
        with ctx.bind(context):
            # Ensure challenge_dir points at our temp root used as challenge workspace
            ctx.challenge_dir = str(root)
            ctx.attempt_id = "aggressive"
            text = (
                "password = KeepAlive99\n"
                "route via 172.18.0.3\n"
                "inet 172.18.0.3/16\n"
            )
            result = _auto_extract(text, command="ip addr")
            self.assertIn("凭据", result)
            self.assertIn("落地", result)
            snap = board_snapshot(root)
            self.assertIn("KeepAlive99", snap)
            self.assertIn("172.18.0.3", snap)


if __name__ == "__main__":
    unittest.main()
