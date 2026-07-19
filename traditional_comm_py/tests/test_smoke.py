from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from traditional_comm.controller import TraditionalCommunicationController
from traditional_comm.runner import run_all
from traditional_comm.samples import generate_samples, parse_tvid
from traditional_comm.transport import LoopbackTransport


class TraditionalCommunicationSmokeTest(unittest.TestCase):
    def test_all_media_types_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-python-") as root:
            root_path = Path(root)
            samples = generate_samples(root_path / "samples")
            video_info = parse_tvid(samples["video"].read_bytes())
            self.assertEqual(video_info["frame_count"], 12)
            results = run_all(root_path / "samples", root_path / "runs", LoopbackTransport(chunk_size=128))
            self.assertEqual([result["kind"] for result in results], ["text", "image", "video"])
            self.assertEqual(results[0]["metrics"]["task"]["content_match"], True)
            self.assertEqual(results[0]["output_path"].suffix, ".txt")
            self.assertEqual(results[1]["metrics"]["task"]["content_match"], None)
            self.assertEqual(results[1]["output_path"].suffix, ".jpg")
            self.assertEqual(results[2]["metrics"]["task"]["content_match"], None)
            self.assertEqual(results[2]["output_path"].suffix, ".mp4")
            for result in results:
                self.assertEqual(result["metrics"]["status"], "completed")
                self.assertEqual(result["metrics"]["task"]["output_valid"], 1)
                self.assertTrue(result["output_path"].exists())
                self.assertTrue((result["run_dir"] / "metrics.json").exists())
            self.assertGreater(results[1]["metrics"]["quality"]["psnr"], 0)
            self.assertGreater(results[2]["metrics"]["quality"]["psnr"], 0)
            self.assertTrue((results[1]["run_dir"] / "encoded_payload.jpg").exists())
            self.assertTrue((results[2]["run_dir"] / "encoded_payload.mp4").exists())

    def test_controller_interfaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-controller-") as root:
            root_path = Path(root)
            samples = generate_samples(root_path / "samples")
            controller = TraditionalCommunicationController(
                root_path / "runs", LoopbackTransport(chunk_size=64)
            )
            self.assertTrue(controller.health_check()["online"])
            self.assertEqual(controller.switch_mode("traditional"), {"mode": "traditional"})
            started = controller.start_run({"kind": "text", "input_path": str(samples["text"])})
            self.assertTrue(started["run_id"].startswith("traditional-text-"))
            self.assertEqual(controller.get_status(started["run_id"])["status"], "completed")
            self.assertEqual(controller.get_performance(started["run_id"])["task"]["content_match"], 1)
            self.assertTrue(controller.get_result(started["run_id"])["content_match"])


if __name__ == "__main__":
    unittest.main()
