import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "comfy-bootstrap"


class BundledWorkflowTest(unittest.TestCase):
    def test_krea_turbo_bf16_uses_only_connected_core_nodes(self):
        workflow = json.loads(
            (ROOT / "workflows/krea2-turbo-bf16.json").read_text()
        )
        nodes = {node["id"]: node for node in workflow["nodes"]}

        self.assertEqual(len(nodes), 9)
        self.assertEqual(len(workflow["links"]), 9)
        self.assertEqual(
            nodes[1]["widgets_values"],
            ["krea2_turbo_bf16.safetensors", "default"],
        )
        self.assertEqual(nodes[7]["type"], "KSampler")
        for node in nodes.values():
            self.assertTrue(all(item["link"] is not None for item in node["inputs"]))
        for link_id, source, source_slot, target, target_slot, _type in workflow[
            "links"
        ]:
            self.assertIn(link_id, nodes[source]["outputs"][source_slot]["links"])
            self.assertEqual(nodes[target]["inputs"][target_slot]["link"], link_id)

    def test_krea_workflow_has_an_editable_connected_canvas(self):
        workflow = json.loads(
            (ROOT / "workflows/krea2-text2img-turbo-bypass.json").read_text()
        )
        nodes = {node["id"]: node for node in workflow["nodes"]}

        self.assertEqual(workflow["version"], 0.4)
        self.assertEqual(len(nodes), 11)
        self.assertEqual(len(workflow["links"]), 11)
        self.assertEqual(nodes[265]["type"], "KSampler")
        self.assertEqual(
            nodes[265]["widgets_values"], [42, "randomize", 8, 1, "euler", "simple", 1]
        )
        self.assertNotIn(
            "ClownsharKSampler_Beta", {node["type"] for node in nodes.values()}
        )
        for node in nodes.values():
            self.assertTrue(all(item["link"] is not None for item in node["inputs"]))
        self.assertEqual(
            nodes[6]["widgets_values"],
            [
                "A cinematic portrait of a woman in soft natural light, "
                "warm expression, shallow depth of field."
            ],
        )
        for link_id, source, source_slot, target, target_slot, _type in workflow[
            "links"
        ]:
            self.assertIn(link_id, nodes[source]["outputs"][source_slot]["links"])
            self.assertEqual(nodes[target]["inputs"][target_slot]["link"], link_id)

        dependencies = json.loads(
            (
                ROOT / "workflows/krea2-text2img-turbo-bypass.nodes.json"
            ).read_text()
        )
        self.assertEqual(
            set(dependencies["custom_nodes"]),
            {"https://github.com/RealRebelAI/ComfyUI-GGUF_KREA-2"},
        )


class AssetHandler(BaseHTTPRequestHandler):
    content = b"model-data-" * 1024
    ranges = []

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/models":
            return self.send_json(
                [
                    {
                        "id": "example/model",
                        "downloads": 42,
                        "likes": 7,
                    }
                ]
            )
        if path == "/api/models/example/model":
            return self.send_json(
                {
                    "siblings": [
                        {"rfilename": "README.md"},
                        {"rfilename": "model.safetensors"},
                        {"rfilename": "vae/model.safetensors"},
                    ]
                }
            )
        offset = 0
        requested_range = self.headers.get("Range")
        if requested_range:
            type(self).ranges.append(requested_range)
            offset = int(requested_range.removeprefix("bytes=").removesuffix("-"))
            self.send_response(206)
            self.send_header(
                "Content-Range",
                f"bytes {offset}-{len(self.content) - 1}/{len(self.content)}",
            )
        else:
            self.send_response(200)
        body = self.content[offset:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class CLITest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.manifest = self.base / "comfy-bootstrap.json"
        self.comfyui = self.base / "ComfyUI"
        self.comfyui.mkdir()
        self.workflow = self.base / "workflows" / "example.json"
        self.workflow.parent.mkdir()
        self.workflow.write_text('{"nodes": [], "links": []}\n')
        AssetHandler.ranges = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AssetHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/model"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def run_cli(self, *arguments, expected=0, input_text=None):
        result = subprocess.run(
            [str(CLI), "--manifest", str(self.manifest), *arguments],
            text=True,
            capture_output=True,
            input=input_text,
            env={
                **os.environ,
                "COMFYUI_DIR": str(self.comfyui),
                "COMFY_BOOTSTRAP_HF_API": (
                    f"http://127.0.0.1:{self.server.server_port}/api"
                ),
            },
        )
        self.assertEqual(
            result.returncode,
            expected,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def configure(self, checksum=None, asset_path="models/unet/model.bin"):
        arguments = ["asset", "add", "model", self.url, asset_path]
        if checksum:
            arguments.extend(["--sha256", checksum])
        self.run_cli(*arguments)
        self.run_cli("workflow", "add", "example", str(self.workflow))
        self.run_cli("workflow", "link", "example", "model")

    def fake_comfy_toolchain(self):
        tools = self.base / "toolchain/bin"
        tools.mkdir(parents=True)
        log = self.base / "toolchain.log"
        marker = tools / ".comfy-cli-installed"
        manager_marker = tools / ".comfy-manager-installed"
        nodes_marker = tools / ".custom-nodes-installed"
        fake_python = tools / "python"
        fake_python.write_text(
            f"""#!{sys.executable}
import json
import pathlib
import sys

log = pathlib.Path({str(log)!r})
marker = pathlib.Path({str(marker)!r})
manager_marker = pathlib.Path({str(manager_marker)!r})
with log.open("a") as stream:
    stream.write(json.dumps(["python", *sys.argv[1:]]) + "\\n")
if sys.argv[1:3] == ["-m", "pip"]:
    if any(value.startswith("comfy-cli==") for value in sys.argv):
        marker.touch()
    if any(value.startswith("comfyui_manager==") for value in sys.argv):
        manager_marker.touch()
elif sys.argv[1] == "-c" and "sys.version_info" in sys.argv[2]:
    print("3.11")
elif sys.argv[1] == "-c" and "importlib.metadata" in sys.argv[2]:
    if not marker.exists():
        raise SystemExit(1)
    print("1.12.0")
elif sys.argv[1] == "-c" and "sysconfig" in sys.argv[2]:
    print(pathlib.Path(__file__).parent)
elif sys.argv[1] == "-c" and "import cm_cli" in sys.argv[2]:
    raise SystemExit(0 if manager_marker.exists() else 1)
"""
        )
        fake_python.chmod(0o755)
        comfy = tools / "comfy"
        comfy.write_text(
            f"""#!{sys.executable}
import json
import pathlib
import sys

log = pathlib.Path({str(log)!r})
nodes_marker = pathlib.Path({str(nodes_marker)!r})
with log.open("a") as stream:
    stream.write(json.dumps(["comfy", *sys.argv[1:]]) + "\\n")
if "deps-in-workflow" in sys.argv:
    output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
    output.write_text(json.dumps({{
        "custom_nodes": {{
            "https://github.com/city96/ComfyUI-GGUF": {{
                "state": "not-installed",
                "hash": "-"
            }}
        }},
        "unknown_nodes": []
    }}))
elif "install-deps" in sys.argv:
    nodes_marker.touch()
elif "simple-show" in sys.argv and nodes_marker.exists():
    print("ComfyUI-GGUF@2.0.0")
"""
        )
        comfy.chmod(0o755)
        return fake_python, log

    def test_manifest_commands_and_sync_are_idempotent(self):
        checksum = hashlib.sha256(AssetHandler.content).hexdigest()
        self.configure(checksum)

        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["workflows"]["example"]["assets"], ["model"])
        self.assertEqual(
            manifest["assets"]["model"]["path"], "models/unet/model.bin"
        )

        first = self.run_cli("sync", "example")
        self.assertIn("Downloading model", first.stdout)
        self.assertIn("1 downloaded", first.stdout)
        installed = self.comfyui / "models/unet/model.bin"
        self.assertEqual(installed.read_bytes(), AssetHandler.content)
        copied = self.comfyui / "user/default/workflows/example.json"
        self.assertEqual(copied.read_text(), self.workflow.read_text())

        second = self.run_cli("sync", "example")
        self.assertIn("1 already present", second.stdout)

    def test_sync_resumes_partial_download(self):
        self.configure()
        destination = self.comfyui / "models/unet/model.bin"
        destination.parent.mkdir(parents=True)
        partial = destination.with_name(destination.name + ".part")
        partial.write_bytes(AssetHandler.content[:100])

        self.run_cli("sync", "example")

        self.assertEqual(destination.read_bytes(), AssetHandler.content)
        self.assertEqual(AssetHandler.ranges, ["bytes=100-"])

    def test_checksum_failure_does_not_install_workflow(self):
        self.configure("0" * 64)

        result = self.run_cli("sync", "example", expected=1)

        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse((self.comfyui / "models/unet/model.bin").exists())
        self.assertFalse(
            (self.comfyui / "user/default/workflows/example.json").exists()
        )

    def test_rejects_asset_path_traversal(self):
        result = self.run_cli(
            "asset", "add", "bad", self.url, "../outside.bin", expected=1
        )
        self.assertIn("safe relative path", result.stderr)
        self.assertFalse(self.manifest.exists())

    def test_rejects_api_format_workflow(self):
        api_workflow = self.base / "api.json"
        api_workflow.write_text('{"1": {"class_type": "SaveImage"}}')

        result = self.run_cli(
            "workflow", "add", "api", str(api_workflow), expected=1
        )

        self.assertIn("API-format prompt JSON has no editable canvas", result.stderr)

    def test_sync_rejects_symlink_escape(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.comfyui / "models").symlink_to(outside, target_is_directory=True)
        self.configure(asset_path="models/model.bin")

        result = self.run_cli("sync", "example", expected=1)

        self.assertIn("escapes the ComfyUI directory", result.stderr)
        self.assertFalse((outside / "model.bin").exists())

    def test_import_copies_workflow_and_extracts_embedded_assets(self):
        source = self.comfyui / "user/default/workflows/imported.json"
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "properties": {
                                "models": [
                                    {
                                        "name": "model.safetensors",
                                        "url": "https://huggingface.co/example/model/resolve/main/model.safetensors",
                                        "directory": "checkpoints",
                                    }
                                ]
                            },
                            "widgets_values": [
                                "model.safetensors",
                                "missing-vae.safetensors",
                            ],
                        }
                    ],
                    "links": [],
                }
            )
        )

        result = self.run_cli("workflow", "import", "imported", str(source))

        manifest = json.loads(self.manifest.read_text())
        asset_name = manifest["workflows"]["imported"]["assets"][0]
        self.assertEqual(
            manifest["assets"][asset_name]["path"],
            "models/checkpoints/model.safetensors",
        )
        self.assertEqual(
            (self.base / "workflows/imported.json").read_text(), source.read_text()
        )
        self.assertIn("Added 1 embedded asset(s)", result.stdout)
        self.assertIn("missing-vae.safetensors", result.stdout)
        self.assertNotIn("\n  model.safetensors", result.stdout)

    def test_hugging_face_search_files_and_add(self):
        search = self.run_cli("hf", "search", "example")
        self.assertIn("example/model", search.stdout)
        self.assertIn("downloads=42", search.stdout)

        files = self.run_cli("hf", "files", "example/model", "*.safetensors")
        self.assertIn("model.safetensors", files.stdout)
        self.assertIn("vae/model.safetensors", files.stdout)
        self.assertNotIn("README.md", files.stdout)

        self.run_cli("workflow", "add", "example", str(self.workflow))
        self.run_cli(
            "hf",
            "add",
            "example/model",
            "model.safetensors",
            "--to",
            "checkpoints",
            "--workflow",
            "example",
        )
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(
            manifest["assets"]["model"]["url"],
            "https://huggingface.co/example/model/resolve/main/model.safetensors",
        )
        self.assertEqual(
            manifest["assets"]["model"]["path"],
            "models/checkpoints/model.safetensors",
        )
        self.assertEqual(
            manifest["workflows"]["example"]["assets"], ["model"]
        )

        guided = self.run_cli(
            "hf",
            "search",
            "example",
            "--add",
            "--workflow",
            "example",
            "--to",
            "vae",
            input_text="1\n2\n",
        )
        manifest = json.loads(self.manifest.read_text())
        self.assertIn("Select repository:", guided.stdout)
        self.assertEqual(
            manifest["assets"]["model-2"]["path"], "models/vae/model.safetensors"
        )
        self.assertEqual(
            manifest["workflows"]["example"]["assets"], ["model", "model-2"]
        )

    def test_setup_node_scan_and_sync(self):
        self.configure()
        (self.comfyui / "main.py").touch()
        fake_python, log = self.fake_comfy_toolchain()

        setup = self.run_cli("setup", "--python", str(fake_python))

        self.assertIn("Installing comfy-cli 1.12.0", setup.stdout)
        self.assertIn("Installing ComfyUI-Manager", setup.stdout)
        state = json.loads(
            (self.base / ".comfy-bootstrap/state.json").read_text()
        )
        self.assertEqual(state["comfy_cli_version"], "1.12.0")
        self.assertEqual(state["python"], str(fake_python))
        repeated = self.run_cli("setup", "--python", str(fake_python))
        self.assertIn("already installed", repeated.stdout)
        setup_calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            len(
                [
                    call
                    for call in setup_calls
                    if call[:3] == ["python", "-m", "pip"]
                ]
            ),
            2,
        )
        self.assertTrue(
            any(
                value == "comfyui_manager==4.2.2"
                for call in setup_calls
                for value in call
            )
        )

        self.run_cli("node", "scan", "example")
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(
            manifest["workflows"]["example"]["node_dependencies"],
            "workflows/example.nodes.json",
        )
        shown = self.run_cli("node", "show", "example")
        self.assertIn("ComfyUI-GGUF", shown.stdout)

        synced = self.run_cli("sync", "example")
        self.assertIn("Installing custom nodes", synced.stdout)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        install_calls = [
            call for call in calls if "install-deps" in call
        ]
        self.assertEqual(len(install_calls), 1)
        self.assertIn("--here", install_calls[0])

        repeated_sync = self.run_cli("sync", "example")
        self.assertIn("already installed", repeated_sync.stdout)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            len([call for call in calls if "install-deps" in call]), 1
        )

        state = json.loads(
            (self.base / ".comfy-bootstrap/state.json").read_text()
        )
        del state["node_dependencies"]
        (self.base / ".comfy-bootstrap/state.json").write_text(json.dumps(state))
        detected = self.run_cli("sync", "example")
        self.assertIn("already installed", detected.stdout)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            len([call for call in calls if "install-deps" in call]), 1
        )

        self.run_cli("sync", "example", "--force-nodes")
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            len([call for call in calls if "install-deps" in call]), 2
        )


if __name__ == "__main__":
    unittest.main()
