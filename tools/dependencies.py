"""Locate the badge's pinned public dependencies for builds and host tests."""
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]


def dependency_path(relative, repository=REPOSITORY):
    # Use the same pinned sources everywhere; a sibling SELECT checkout must
    # not silently replace a dependency that the public badge build verified.
    return repository / "devices" / "badge" / "vendor" / relative


def add_import_paths(repository=REPOSITORY):
    for relative in ("network/vendor", "badgelink/badge", "network/badge",
                     "shared", "identity/badge/identity", "kbqwerty/badge/kbqwerty"):
        sys.path.insert(0, str(dependency_path(relative, repository)))
    sys.path.insert(0, str(repository / "devices" / "badge"))
