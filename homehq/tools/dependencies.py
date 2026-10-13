"""Locate Home HQ's small source dependency set in either supported repository."""
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]


def dependency_path(relative, repository=REPOSITORY):
    # SELECT owns these shared modules at their original paths. The public
    # Wes fork carries only this app's allowlisted copies, so a fresh clone
    # must not depend on a sibling conference checkout or an installed package.
    source = repository / relative
    return source if source.exists() else repository / "homehq" / "vendor" / "tufty" / relative


def add_import_paths(repository=REPOSITORY):
    for relative in ("network/vendor", "badgelink/badge", "network/badge",
                     "shared", "identity/badge/identity", "kbqwerty/badge/kbqwerty"):
        sys.path.insert(0, str(dependency_path(relative, repository)))
    sys.path.insert(0, str(repository / "homehq" / "badge" / "homehq"))
