"""Exercise the documented Docker flow from a source-only temporary snapshot."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="phase12_source_", dir=ROOT / "tmp"
    ) as scratch:
        clean = Path(scratch)
        ignored = shutil.ignore_patterns(
            ".env",
            ".env.*",
            "*.log",
            "node_modules",
            ".venv",
            ".cache",
            "__pycache__",
            "*.egg-info",
            "dist",
            "build",
            "test-results",
            "playwright-report",
            ".pytest_cache",
            ".ruff_cache",
        )
        for directory in (
            "backend",
            "frontend",
            "docker",
            "seed",
            "scripts",
            "docs",
            "assignment",
        ):
            shutil.copytree(ROOT / directory, clean / directory, ignore=ignored)
        for filename in (
            "README.md",
            "docker-compose.yml",
            ".env.example",
            ".gitignore",
        ):
            shutil.copy2(ROOT / filename, clean / filename)
        assert not (clean / ".env").exists()
        assert not (clean / "frontend/node_modules").exists()
        assert not (clean / ".cache").exists()
        print(
            "Phase 12: source-only snapshot; no .env, host dependencies or model cache copied",
            flush=True,
        )
        result = subprocess.run(
            [sys.executable, str(clean / "scripts/verify_phase11_docker.py")],
            cwd=clean,
            check=False,
        )
        if result.returncode:
            return result.returncode
        print(
            "Phase 12: source-only clean-run passed; Docker build cache permitted; temporary source removed",
            flush=True,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
