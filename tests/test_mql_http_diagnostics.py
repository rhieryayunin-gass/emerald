from pathlib import Path


def test_webrequest_error_is_captured_before_response_processing():
    source = Path("apps/mt5/RIRI_EMERALD_DEMO_v1_204.mq5").read_text()
    post = source.split("bool HttpPost(", 1)[1].split("string BrokerId()", 1)[0]
    request_end = post.index("response, response_headers);")
    capture = post.index("const int request_error = GetLastError();")
    decode = post.index("CharArrayToString(response")
    assert request_end < capture < decode
    assert "if(response_bytes > 0)\n      response_text = CharArrayToString" in post
    assert "path, category, status_code, request_error, elapsed_ms" in post
    assert '"TRANSPORT"' in post
    assert "ArrayResize(body, copied - 1) != copied - 1" in post


def test_http_diagnostics_preserve_trading_and_timestamp_code():
    previous = Path("apps/mt5/RIRI_EMERALD_DEMO_v1_203.mq5").read_text()
    current = Path("apps/mt5/RIRI_EMERALD_DEMO_v1_204.mq5").read_text()

    def without_http_and_version(source):
        prefix, remainder = source.split("bool HttpPost(", 1)
        _, suffix = remainder.split("string BrokerId()", 1)
        return (prefix + suffix).replace("1.203", "VERSION").replace("1.204", "VERSION")

    assert without_http_and_version(previous) == without_http_and_version(current)
