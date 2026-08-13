import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from host.docker_manager import DockerManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_solver_without_init_file_falls_back_to_stdin(self):
        result = subprocess.run(
            [sys.executable, "-m", "solver.main"],
            input="",
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("未收到初始化消息", result.stdout)
        self.assertNotIn("读取初始化文件失败", result.stdout)

    def test_build_reports_missing_fastcoll_before_calling_docker(self):
        manager = DockerManager(image_name="ctf-agent-test", settings={})

        with patch("host.docker_manager.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "fastcoll"):
                manager.build_image(PROJECT_ROOT)

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
