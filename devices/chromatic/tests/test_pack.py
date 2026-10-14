#!/usr/bin/env python3
"""Exercise the native bounded cache codec with allocation and memory guards."""
import os
import pathlib
import subprocess
import tempfile
import unittest

CHROMATIC = pathlib.Path(__file__).resolve().parents[1]


class BoundedPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="homehq-pack-")
        directory = pathlib.Path(cls.temporary.name)
        allocator = directory / "allocator.c"
        allocator.write_text("""#undef malloc
#undef free
#include <stdlib.h>
size_t HQ_TestAllocations;
void *HQ_TestMalloc(size_t length) { ++HQ_TestAllocations; return malloc(length); }
void HQ_TestFree(void *pointer) { free(pointer); }
""")
        cls.binary = directory / "pack_check"
        command = ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-O1", "-g",
                   "-DHQ_PACK_COUNT_ALLOCS", "-Dmalloc=HQ_TestMalloc", "-Dfree=HQ_TestFree",
                   "-I", str(CHROMATIC / "src"), str(CHROMATIC / "tests/test_pack.c"),
                   str(CHROMATIC / "src/homehq_pack.c"), str(allocator), "-o", str(cls.binary)]
        if os.environ.get("HQ_PACK_SANITIZE") == "1":
            command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(command, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def check_fixture(self, fixture):
        completed = subprocess.run([str(self.binary), str(fixture)], check=True,
                                   capture_output=True, text=True)
        self.assertIn("exact round-trip", completed.stdout)
        self.assertIn("Compression boundaries and corrupt/truncated input PASS", completed.stdout)

    def test_demo_fixture_golden_format_bounds_canaries_and_no_allocations(self):
        self.check_fixture(CHROMATIC.parents[1] / "fixtures/demo.json")

    @unittest.skipUnless(os.environ.get("HOMEHQ_HOSTED_SNAPSHOT"), "Private fixture path is optional")
    def test_private_fixture_without_logging_values(self):
        self.check_fixture(pathlib.Path(os.environ["HOMEHQ_HOSTED_SNAPSHOT"]))


if __name__ == "__main__":
    unittest.main()
