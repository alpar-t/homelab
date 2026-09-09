#!/usr/bin/env python3
import importlib.util
import sys
import unittest

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('updater', 'scripts/update-newjoy-staging.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def ref(run, attempt=1):
    return f'{module.IMAGE}:sha-{"a" * 40}-run-{run}-{attempt}@sha256:{"b" * 64}'


class UpdateTests(unittest.TestCase):
    def test_numeric_order_and_monotonic_updates(self):
        original = f'namespace: newjoy-website-staging\n    image: {ref(9)}\n'
        self.assertIn(ref(10), module.replace_image(original, ref(10)))
        self.assertEqual(original, module.replace_image(original, ref(8)))
        self.assertEqual(original, module.replace_image(original, ref(9)))
        self.assertIn(ref(9, 2), module.replace_image(original, ref(9, 2)))

    def test_rejects_injection_and_wrong_targets(self):
        for value in ['latest', ref(2) + '\ncommand: bad', ref(2).replace('newjoy-website', 'another-site')]:
            with self.assertRaises(ValueError):
                module.replace_image(f'  image: {ref(1)}\n', value)
        with self.assertRaises(ValueError):
            module.replace_image('image: nginx:latest\n', ref(2))

    def test_fixture_can_advance(self):
        before = f'  image: {module.IMAGE}:sha-{"a" * 40}@sha256:{"b" * 64}\n'
        self.assertIn(ref(3), module.replace_image(before, ref(3)))


if __name__ == '__main__':
    unittest.main()
