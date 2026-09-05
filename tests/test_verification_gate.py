"""CI and local checks must discover the same suites without duplicate staging."""
import sys
import unittest

from tools.verify import verification_commands


class VerificationGateTests(unittest.TestCase):
    def test_python_uses_this_interpreter_and_scoped_discovery(self):
        commands = verification_commands()
        self.assertIn([sys.executable, "-m", "pytest", "tests/", "-q"], commands)

    def test_default_is_non_mutating_asset_verification(self):
        self.assertEqual(verification_commands()[0], ["node", "tools/build_web.mjs", "--check"])
        self.assertEqual(verification_commands(build=True)[0], ["node", "tools/build_web.mjs"])

    def test_javascript_suites_are_discovered_explicitly(self):
        command = verification_commands()[-1]
        self.assertEqual(command[:2], ["node", "--test"])
        self.assertTrue(any(path.replace('\\', '/') == 'tests/test_settings_workspace.mjs' for path in command[2:]))
        self.assertTrue(any(path.replace('\\', '/') == 'tests/test_build_web.mjs' for path in command[2:]))


if __name__ == '__main__':
    unittest.main()
