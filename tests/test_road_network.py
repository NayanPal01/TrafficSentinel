"""
Unit tests for Road Network Graph module.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.road_network import RoadNetwork

class TestRoadNetwork(unittest.TestCase):
    def setUp(self):
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "road_network.json")
        self.rn = RoadNetwork(json_path)

    def test_nodes_loaded(self):
        self.assertGreaterEqual(len(self.rn.nodes), 10)
        self.assertIn("CAM-01", self.rn.nodes)
        self.assertIn("CAM-03", self.rn.nodes)
        self.assertIn("CAM-07", self.rn.nodes)

    def test_fork_detection(self):
        # CAM-03 should fork into CAM-09 and CAM-08
        self.assertTrue(self.rn.is_fork("CAM-03"))
        outgoing_03 = self.rn.get_outgoing_edges("CAM-03")
        self.assertEqual(len(outgoing_03), 2)
        destinations_03 = {e.to_node for e in outgoing_03}
        self.assertEqual(destinations_03, {"CAM-09", "CAM-08"})

        # CAM-07 should fork into CAM-04 and CAM-05
        self.assertTrue(self.rn.is_fork("CAM-07"))
        outgoing_07 = self.rn.get_outgoing_edges("CAM-07")
        self.assertEqual(len(outgoing_07), 2)
        destinations_07 = {e.to_node for e in outgoing_07}
        self.assertEqual(destinations_07, {"CAM-04", "CAM-05"})

        # CAM-06 should NOT be a fork (only goes to CAM-11)
        self.assertFalse(self.rn.is_fork("CAM-06"))

    def test_edge_polyline_and_distance(self):
        edge = self.rn.get_edge("CAM-06", "CAM-11")
        self.assertIsNotNone(edge)
        self.assertGreater(edge.distance_m, 100.0)
        self.assertGreater(len(edge.polyline), 2)
        self.assertEqual(len(edge.cum_distances), len(edge.polyline))
        self.assertAlmostEqual(edge.cum_distances[0], 0.0, places=1)
        self.assertAlmostEqual(edge.cum_distances[-1], edge.distance_m, delta=5.0)

    def test_serialization(self):
        d = self.rn.to_dict()
        self.assertIn("nodes", d)
        self.assertIn("edges", d)
        self.assertEqual(len(d["nodes"]), len(self.rn.nodes))

if __name__ == "__main__":
    unittest.main()
