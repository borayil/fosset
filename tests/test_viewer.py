import base64
import json
import re

from fosset.viewer import _Api, build_html


def test_html_embeds_plotly_and_the_figures():
    html = build_html([{"data": [], "layout": {"title": {"text": "Hi"}}}], status="asking…")
    assert "plotly.js v" in html
    assert "__PAYLOAD__" not in html and "__PLOTLY__" not in html
    payload = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(payload)["charts"][0]["layout"]["title"]["text"] == "Hi"
    assert json.loads(payload)["status"] == "asking…"


def test_data_cannot_close_the_script_tag():
    html = build_html([{"data": [], "layout": {"title": {"text": "</script><script>alert(1)</script>"}}}])
    payload = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script>" not in payload
    assert json.loads(payload)["charts"][0]["layout"]["title"]["text"] == "</script><script>alert(1)</script>"


def test_save_png_never_overwrites(tmp_path):
    api = _Api("my report/../x", tmp_path, None)
    url = "data:image/png;base64," + base64.b64encode(b"png-bytes").decode()
    first = api.save_png(url, 2)
    second = api.save_png(url, 2)
    assert first != second
    assert first.endswith("fosset-my_report_.._x-2.png")  # path separators are replaced
    assert (tmp_path / "fosset-my_report_.._x-2-2.png").read_bytes() == b"png-bytes"
