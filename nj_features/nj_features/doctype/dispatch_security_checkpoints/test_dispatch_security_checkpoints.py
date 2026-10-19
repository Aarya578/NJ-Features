# Copyright (c) 2024, NewJaisa - IT Team and Contributors
# See license.txt

# import frappe
import unittest

from nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints import (
	get_next_asset_action,
)


class TestDispatchSecurityCheckpoints(unittest.TestCase):
	def test_first_asset_gate_action_is_outward(self):
		self.assertEqual(get_next_asset_action(None), "Outward")

	def test_outward_must_be_followed_by_inward(self):
		self.assertEqual(get_next_asset_action("Outward"), "Inward")

	def test_inward_must_be_followed_by_outward(self):
		self.assertEqual(get_next_asset_action("Inward"), "Outward")
