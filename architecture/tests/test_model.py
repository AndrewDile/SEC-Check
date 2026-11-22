import unittest

from architecture.model import Model, ModelError

GOOD = {
    "services": {"a": {"port": 80}, "b": {"port": 81, "published": ["81:81"]}},
    "connections": [{"from": "a", "to": "b", "why": "test"}],
    "generated": [{"file": "m.py", "from": ["spec.yaml"], "command": "gen.sh"}],
}


class ModelTest(unittest.TestCase):
    def assertInvalid(self, data, text):
        with self.assertRaises(ModelError) as caught:
            Model.parse(data)
        self.assertIn(text, str(caught.exception))

    def test_parses(self):
        model = Model.parse(GOOD)
        self.assertEqual(model.services["b"].published, ("81:81",))
        self.assertTrue(model.calls("a", "b"))
        self.assertFalse(model.calls("b", "a"))
        self.assertTrue(model.connects("b", "a"))
        self.assertEqual(model.generated[0].sources, ("spec.yaml",))

    def test_unknown_section(self):
        self.assertInvalid({**GOOD, "conections": []}, "unknown section conections")

    def test_port_must_be_a_number(self):
        self.assertInvalid({**GOOD, "services": {"a": {"port": "80"}}}, "a: port must be a number")

    def test_connection_to_unknown_service(self):
        bad = {**GOOD, "connections": [{"from": "a", "to": "c", "why": "test"}]}
        self.assertInvalid(bad, "no service c")

    def test_generated_needs_command(self):
        bad = {**GOOD, "generated": [{"file": "m.py", "from": []}]}
        self.assertInvalid(bad, "missing command")

    def test_connection_needs_why(self):
        self.assertInvalid({**GOOD, "connections": [{"from": "a", "to": "b"}]}, "missing why")
