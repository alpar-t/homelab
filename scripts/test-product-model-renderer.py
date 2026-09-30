"""Exercise the deployed renderer manifest's HTTP and isolation contract locally."""

import base64
import io
import json
import threading
import tempfile
import types
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import yaml


MANIFEST = Path(__file__).resolve().parents[1] / "config/interior-designer/manifests/product-model-renderer.yaml"
API_MANIFEST = MANIFEST.with_name("product-model-api.yaml")


class RendererContract(unittest.TestCase):
    def test_isolation_and_http_artifacts(self):
        config, deployment, service, policy = list(yaml.safe_load_all(MANIFEST.read_text()))
        self.assertEqual([item["kind"] for item in (config, deployment, service, policy)],
                         ["ConfigMap", "Deployment", "Service", "NetworkPolicy"])
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertFalse(pod["enableServiceLinks"])
        self.assertEqual({volume["name"] for volume in pod["volumes"]}, {"code", "work", "tmp"})
        self.assertEqual(policy["spec"]["egress"], [])
        self.assertEqual(policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"],
                         {"app.kubernetes.io/name": "product-model-api"})
        api_documents = list(yaml.safe_load_all(API_MANIFEST.read_text()))
        api_deployment = next(item for item in api_documents if item["kind"] == "Deployment")
        api_policy = next(item for item in api_documents if item["kind"] == "NetworkPolicy")
        self.assertFalse(api_deployment["spec"]["template"]["spec"]["automountServiceAccountToken"])
        self.assertEqual(api_policy["spec"]["policyTypes"], ["Ingress"])
        self.assertEqual(api_policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"],
                         {"app.kubernetes.io/name": "openclaw"})

        with tempfile.TemporaryDirectory() as scratch:
            source = config["data"]["server.py"].replace('dir="/work"', f'dir="{scratch}"')
            source = source.rsplit("ThreadingHTTPServer((\"0.0.0.0\", 18811), Handler).serve_forever()", 1)[0]
            namespace = {"__name__": "renderer_contract_test"}
            exec(compile(source, "server.py", "exec"), namespace)

            def fake_blender(command, **_kwargs):
                output, metrics = map(Path, command[-2:])
                output.write_bytes(b"glTF-test")
                metrics.write_text("{}")
                for view in ("front", "side", "top", "underside"):
                    (output.parent / f"preview-{view}.png").write_bytes(b"\x89PNG\r\n\x1a\npreview")
                return types.SimpleNamespace(pid=99_999_999, wait=lambda timeout=None: 0)

            namespace["subprocess"].Popen = fake_blender
            server = ThreadingHTTPServer(("127.0.0.1", 0), namespace["Handler"])
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps({"runnerScript": "pass",
                                   "spec": {"slug": "example"},
                                   "referenceImage": base64.b64encode(b"\x89PNG\r\n\x1a\nphoto").decode()}).encode()
                request = Request(f"http://127.0.0.1:{server.server_port}/render", data=body,
                                  headers={"Content-Type": "application/json"})
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                    with zipfile.ZipFile(io.BytesIO(response.read())) as bundle:
                        self.assertEqual(set(bundle.namelist()),
                                         {"model.glb", "metrics.json", "preview-front.png", "preview-side.png",
                                          "preview-top.png", "preview-underside.png"})
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
