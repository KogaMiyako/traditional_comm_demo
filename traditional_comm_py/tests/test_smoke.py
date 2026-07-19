from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from traditional_comm.controller import TraditionalCommunicationController
from traditional_comm.runner import run_all
from traditional_comm.samples import generate_samples, parse_tvid
from traditional_comm.transport import LanTcpReceiver, LanTcpTransport, LoopbackTransport
from traditional_comm.web_adapter import WebRunManager


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
            self.assertTrue(controller.prepare_run({"kind": "text", "input_path": str(samples["text"])})["ready"])
            started = controller.start_run({"kind": "text", "input_path": str(samples["text"])})
            self.assertTrue(started["run_id"].startswith("traditional-text-"))
            self.assertEqual(controller.get_status(started["run_id"])["status"], "completed")
            self.assertEqual(controller.get_status(started["run_id"])["phase"], "completed")
            self.assertFalse(controller.get_error(started["run_id"])["has_error"])
            self.assertEqual(controller.get_performance(started["run_id"])["task"]["content_match"], 1)
            self.assertTrue(controller.get_result(started["run_id"])["content_match"])

    def test_lan_tcp_transport_and_receiver(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-lan-") as root:
            root_path = Path(root)
            receiver = LanTcpReceiver("127.0.0.1", 0, root_path / "receiver-runs")
            receiver.start()
            receiver_results: dict = {}

            def serve() -> None:
                receiver_results["items"] = receiver.serve_forever(max_connections=1)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                transport = LanTcpTransport("127.0.0.1", receiver.address[1])
                self.assertTrue(transport.health_check()["online"])
                payload = "局域网传统通信测试".encode("utf-8")
                received, stats = transport.send_payload(
                    payload,
                    {
                        "run_id": "traditional-text-lan-test",
                        "mode": "traditional",
                        "media_type": "text",
                        "codec": "utf8",
                        "container": "txt",
                        "codec_metadata": {},
                        "expected_total_bytes": len(payload),
                    },
                )
                self.assertEqual(received, payload)
                self.assertEqual(stats["transport"], "lan-tcp")
                self.assertEqual(stats["sent_bytes"], len(payload))
                self.assertEqual(stats["received_bytes"], len(payload))
                self.assertTrue(stats["acknowledged"])
                self.assertTrue(stats["receiver_decode_valid"])
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                receiver_result = root_path / "receiver-runs" / "traditional-text-lan-test" / "receiver_result.json"
                self.assertTrue(receiver_result.exists())
            finally:
                receiver.close()

    def test_web_run_manager_background_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-web-") as root:
            root_path = Path(root)
            samples = generate_samples(root_path / "samples")
            manager = WebRunManager(root_path / "samples", root_path / "runs")
            started = manager.start_run({"kind": "image", "sample_id": samples["image"].name})
            for _ in range(200):
                status = manager.get_status(started["run_id"])
                if status["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(manager.get_metrics(started["run_id"])["task"]["output_valid"], 1)
            self.assertGreaterEqual(len(manager.get_events(started["run_id"])), 5)
            self.assertIsNotNone(manager.get_result(started["run_id"]))


if __name__ == "__main__":
    unittest.main()
