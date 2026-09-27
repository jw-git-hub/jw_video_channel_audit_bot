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


def test_detail_reasons_extracts_reason_values_from_error_details():
    try_api = load_script()
    payload = {"error": {"errors": [{"reason": "badRequest"}],
                         "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                     "reason": "API_KEY_INVALID", "domain": "googleapis.com"}]}}
    assert try_api.detail_reasons(payload) == ["API_KEY_INVALID"]


def test_detail_reasons_is_empty_without_details():
    assert load_script().detail_reasons({"error": {"errors": [{"reason": "badRequest"}]}}) == []


def test_custom_url_shape_flags_presence_and_encoding():
    try_api = load_script()
    assert try_api.custom_url_shape(None) == {"present": False, "starts_with_at": False, "percent_encoded": False,
                                              "non_ascii": False}
    assert try_api.custom_url_shape("@example") == {"present": True, "starts_with_at": True,
                                                    "percent_encoded": False, "non_ascii": False}
    assert try_api.custom_url_shape("%D0%B8%D0%BC%D1%8F") == {"present": True, "starts_with_at": False,
                                                              "percent_encoded": True, "non_ascii": False}
    assert try_api.custom_url_shape("имя") == {"present": True, "starts_with_at": False, "percent_encoded": False,
                                              "non_ascii": True}


def test_handle_label_names_by_position_not_by_the_real_handle():
    try_api = load_script()
    assert try_api.handle_label(1) == "--handle №1"
    assert try_api.handle_label(2) == "--handle №2"


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
