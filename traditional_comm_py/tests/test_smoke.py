from __future__ import annotations

import json
import pickle
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from traditional_comm.config import get_dataset_config, get_task_config, load_config
from traditional_comm.controller import TraditionalCommunicationController
from traditional_comm.dataset_adapter import materialize_cifar10_sample, select_cifar10_sample
from traditional_comm.runner import run_all, run_task_only
from traditional_comm.samples import generate_samples, parse_tvid
from traditional_comm.task_adapter import ConfiguredTaskAdapter
from traditional_comm.transport import LanTcpReceiver, LanTcpTransport, LoopbackTransport


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

    def test_config_and_udeepsc_task_contract(self) -> None:
        config = load_config()
        self.assertTrue(Path(config["paths"]["dataset_root"]).name == "dataset")
        self.assertEqual(get_dataset_config(config, "cifar10")["num_classes"], 10)
        self.assertEqual(get_task_config(config, "image_classification")["semantic_task"], "imgc")
        self.assertEqual(get_task_config(config, "video_sentiment")["semantic_task"], "msa")

    def test_external_task_command_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-task-adapter-") as root:
            root_path = Path(root)
            input_path = root_path / "decoded.ppm"
            input_path.write_bytes(b"test-input")
            config = load_config()
            config["tasks"]["image_classification"]["command"] = [
                sys.executable,
                "-c",
                (
                    "import json,sys; json.load(sys.stdin); "
                    "print(json.dumps({'success': True, 'prediction': {'label': 3}, "
                    "'metrics': {'top1': 1.0}}))"
                ),
            ]
            adapter = ConfiguredTaskAdapter(config)
            result = adapter.run(
                kind="image",
                source_path=input_path,
                decoded_path=input_path,
                source_bytes=b"test-input",
                decoded_bytes=b"test-input",
                task={"task_type": "image_classification"},
                quality={},
            )
            self.assertTrue(result["success"])
            self.assertEqual(result["semantic_task"], "imgc")
            self.assertEqual(result["prediction"]["label"], 3)

    def test_external_task_command_cwd_and_task_only_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-task-only-") as root:
            root_path = Path(root)
            input_path = root_path / "sample_test.pkl"
            input_path.write_bytes(b"feature-sample")
            config = load_config()
            config["tasks"]["video_sentiment"]["command_cwd"] = str(root_path)
            config["tasks"]["video_sentiment"]["command"] = [
                sys.executable,
                "-c",
                (
                    "import json,sys; request=json.load(sys.stdin); "
                    "print(json.dumps({'success': True, 'prediction': {'sentiment_score': 0.2}, "
                    "'metrics': {'mae': 0.1}, 'model_version': 'test-mmsa'}))"
                ),
            ]
            result = run_task_only(
                "video",
                input_path,
                root_path / "runs",
                {"task_id": "mosei-smoke", "task_type": "video_sentiment"},
                task_adapter=ConfiguredTaskAdapter(config),
            )
            self.assertEqual(result["metrics"]["status"], "completed")
            self.assertEqual(
                result["metrics"]["task"]["task_result"]["prediction"]["sentiment_score"],
                0.2,
            )
            self.assertTrue((result["run_dir"] / "result.json").exists())

    def test_external_task_failure_preserves_json_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-task-error-") as root:
            input_path = Path(root) / "decoded.ppm"
            input_path.write_bytes(b"test-input")
            config = load_config()
            config["tasks"]["image_classification"]["command"] = [
                sys.executable,
                "-c",
                (
                    "import json,sys; print(json.dumps({'success': False, 'error': 'missing torch', "
                    "'prediction': None, 'metrics': {}})); sys.exit(1)"
                ),
            ]
            result = ConfiguredTaskAdapter(config).run(
                kind="image",
                source_path=input_path,
                decoded_path=input_path,
                source_bytes=b"test-input",
                decoded_bytes=b"test-input",
                task={"task_type": "image_classification"},
                quality={},
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "missing torch")

    def test_cifar10_random_sample_materialization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="traditional-cifar-") as root:
            cifar_root = Path(root) / "cifar"
            cifar_root.mkdir()
            rows = [bytes([value % 256 for value in range(3072)]), bytes([7] * 3072)]
            with (cifar_root / "test_batch").open("wb") as handle:
                pickle.dump({b"data": rows, b"labels": [2, 5]}, handle)
            with (cifar_root / "batches.meta").open("wb") as handle:
                pickle.dump({b"label_names": [b"zero", b"one", b"two", b"three", b"four", b"five"]}, handle)

            sample = select_cifar10_sample(
                cifar_root,
                split="test",
                mode="random",
                seed=100,
                samples_per_file=2,
            )
            repeated = select_cifar10_sample(
                cifar_root,
                split="test",
                mode="random",
                seed=100,
                samples_per_file=2,
            )
            self.assertEqual(sample.index, repeated.index)
            self.assertEqual(sample.label_name, ["two", "five"][sample.index])
            self.assertTrue(sample.ppm_bytes.startswith(b"P6\n32 32\n255\n"))
            materialized = materialize_cifar10_sample(sample, Path(root) / "selected")
            self.assertTrue(materialized.exists())


if __name__ == "__main__":
    unittest.main()
