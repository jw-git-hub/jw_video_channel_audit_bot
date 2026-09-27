import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "try_api.py"


def load_script():
    spec = importlib.util.spec_from_file_location("try_api", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skeleton_keeps_keys_and_hides_values():
    try_api = load_script()
    payload = {"items": [{"id": "секрет", "statistics": {"viewCount": "12"}, "live": True}], "next": None}
    assert try_api.skeleton(payload) == {"items": [{"id": "str", "statistics": {"viewCount": "str"},
                                                    "live": "bool"}], "next": "null"}


def test_skeleton_of_empty_list_is_empty_list():
    assert load_script().skeleton({"items": []}) == {"items": []}


def test_multipart_carries_fields_and_file(tmp_path):
    try_api = load_script()
    picture = tmp_path / "pic.png"
    picture.write_bytes(b"PNGDATA")
    body, content_type = try_api.multipart({"chat_id": "42"}, "photo", picture)
    boundary = content_type.split("boundary=", 1)[1]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert f"--{boundary}".encode() in body
    assert b'name="chat_id"\r\n\r\n42' in body
    assert b'filename="pic.png"' in body and b"PNGDATA" in body
