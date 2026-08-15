from __future__ import annotations

import unittest


def main() -> int:
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return int(not result.wasSuccessful())
