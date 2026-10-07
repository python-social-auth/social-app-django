"""Verify that wheels contain runtime files and source archives retain tests."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    package = root / "social_django"
    tests = root / "tests"
    runtime = {
        path.relative_to(root).as_posix()
        for path in package.rglob("*")
        if path.is_file()
        and "tests" not in path.relative_to(root).parts
        and (path.suffix in {".py", ".html", ".svg"} or path.name in {"py.typed", "NOTICE", "LICENSE.amplify-ui"})
    }
    fixtures = {
        path.relative_to(root).as_posix()
        for path in tests.rglob("*")
        if path.is_file() and path.suffix in {".py", ".html", ".txt", ".json", ".pem"}
    }
    sdists = []
    for directory in args.directories:
        wheels = list(directory.glob("*.whl"))
        if not wheels:
            message = f"No wheels found in {directory}"
            raise ValueError(message)
        for wheel in wheels:
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
            bundled_tests = {name for name in names if "tests" in Path(name).parts}
            if bundled_tests:
                message = f"{wheel}: bundled tests: {sorted(bundled_tests)}"
                raise ValueError(message)
            if missing := runtime - names:
                message = f"{wheel}: missing runtime files: {sorted(missing)}"
                raise ValueError(message)
            print(f"{wheel}: runtime file policy passed")
        sdists.extend(directory.glob("*.tar.gz"))
    if not sdists:
        message = "No source distributions found"
        raise ValueError(message)
    for sdist in sdists:
        with tarfile.open(sdist) as archive:
            names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
        if missing := fixtures - names:
            message = f"{sdist}: missing test files: {sorted(missing)}"
            raise ValueError(message)
        print(f"{sdist}: source file policy passed")


if __name__ == "__main__":
    main()
