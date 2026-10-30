"""the native window. arrows flip through charts, s saves a png, esc closes"""

import base64
import importlib.util
import json
import re
import sys
import threading
import time
from pathlib import Path

_TEMPLATE = Path(__file__).with_name("viewer.html")


def build_html(figures: list[dict]) -> str:
    # escape < so nothing in the data can close the script tag
    payload = json.dumps(figures).replace("<", "\\u003c")
    html = _TEMPLATE.read_text().replace("__PLOTLY__", _plotly_js())
    return html.replace("__PAYLOAD__", payload)


def show(figures: list[dict], title: str, stem: str, started: float | None = None) -> None:
    import webview  # slow to import, so only load it when we actually open a window

    api = _Api(stem, Path.cwd(), started)
    window = webview.create_window(title, html=build_html(figures), js_api=api, width=1100, height=720)
    api._window = window
    webview.start()


class _Api:
    """stuff the page can call. underscore attributes stay hidden from it"""

    def __init__(self, stem: str, out_dir: Path, started: float | None):
        self._stem = re.sub(r"[^\w.-]", "_", stem) or "chart"
        self._out_dir = out_dir
        self._started = started
        self._window = None

    def save_png(self, data_url: str, index: int) -> str:
        path = self._out_dir / f"fosset-{self._stem}-{int(index)}.png"
        n = 2
        while path.exists():
            path = self._out_dir / f"fosset-{self._stem}-{int(index)}-{n}.png"
            n += 1
        path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        return str(path)

    def rendered(self) -> None:
        if self._started is not None:
            print(f"first chart on screen: {time.perf_counter() - self._started:.2f}s", file=sys.stderr)

    def close(self) -> None:
        # pywebview sends our return value back to the page after this returns. if the
        # window is already gone by then the process just hangs forever, so wait for
        # this call to wrap up before killing the window
        caller = threading.current_thread()

        def destroy():
            caller.join(timeout=1)
            self._window.destroy()

        threading.Thread(target=destroy, daemon=True).start()


def _plotly_js() -> str:
    # use the plotly.js that ships with the plotly package so nothing hits the network
    spec = importlib.util.find_spec("plotly")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("plotly is not installed")
    root = Path(spec.submodule_search_locations[0])
    return (root / "package_data" / "plotly.min.js").read_text()
