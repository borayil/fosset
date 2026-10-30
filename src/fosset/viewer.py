"""Show figures in a native window: arrow keys cycle, S saves a PNG, Esc closes."""

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
    # Escaping "<" keeps data from closing the <script> tag it is embedded in.
    payload = json.dumps(figures).replace("<", "\\u003c")
    html = _TEMPLATE.read_text().replace("__PLOTLY__", _plotly_js())
    return html.replace("__PAYLOAD__", payload)


def show(figures: list[dict], title: str, stem: str, started: float | None = None) -> None:
    import webview  # imported here because it is slow to load and only needed for the window

    api = _Api(stem, Path.cwd(), started)
    window = webview.create_window(title, html=build_html(figures), js_api=api, width=1100, height=720)
    api._window = window
    webview.start()


class _Api:
    """Methods the page can call. Private attributes are not exposed to it."""

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
        # pywebview sends this call's return value back to the page after we return.
        # Destroying the window first strands that reply and the process never exits,
        # so destroy it only once this call's thread has finished.
        caller = threading.current_thread()

        def destroy():
            caller.join(timeout=1)
            self._window.destroy()

        threading.Thread(target=destroy, daemon=True).start()


def _plotly_js() -> str:
    # Use the plotly.js bundled with the plotly package, so nothing loads from the network.
    spec = importlib.util.find_spec("plotly")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("plotly is not installed")
    root = Path(spec.submodule_search_locations[0])
    return (root / "package_data" / "plotly.min.js").read_text()
