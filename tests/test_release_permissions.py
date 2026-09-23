import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("rsync"), "deployment test requires rsync")
class ReleasePermissionTests(unittest.TestCase):
    def test_private_source_root_produces_service_accessible_release(self):
        script = Path("infra/vps/deploy-emerald.sh").read_text()
        # Exercise the actual copy phase without touching /opt, systemd or live services.
        copy_phase = script[script.index("rsync -a --delete"):script.index('\ncd "${release_dir}"')]
        for source_mode in (0o700, 0o750):
            with self.subTest(source_mode=oct(source_mode)), tempfile.TemporaryDirectory() as root:
                source = Path(root) / "source"
                release = Path(root) / "release"
                source.mkdir(mode=source_mode)
                release.mkdir(mode=0o755)
                (source / "app.py").write_text("# application code\n")
                (source / ".env").write_text("FAKE_TEST_SECRET=do-not-copy\n")
                subprocess.run(
                    ["bash", "-euc", copy_phase],
                    env={**os.environ, "project_root": str(source), "release_dir": str(release)},
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(stat.S_IMODE(release.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), source_mode)
                self.assertTrue((release / "app.py").is_file())
                self.assertFalse((release / ".env").exists())


if __name__ == "__main__":
    unittest.main()
