"""the native window. arrows flip through charts, s saves a png, esc closes"""

import base64
import html
import importlib.util
import json
import re
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

_TEMPLATE = Path(__file__).with_name("viewer.html")


def build_html(figures: list[dict], status: str = "", export: bool = False) -> str:
    page = _TEMPLATE.read_text().replace("__PLOTLY__", _plotly_js())
    return page.replace("__PAYLOAD__", _js({"charts": figures, "status": status, "export": export}))


def write_html(figures: list[dict], path: Path, status: str = "") -> None:
    """a standalone page that works in any browser, for when there's no window to open"""
    path.write_text(build_html(figures, status))


def show(
    figures: list[dict],
    title: str,
    stem: str,
    started: float | None = None,
    status: str = "",
    later: Callable[[], tuple[list[dict] | None, str]] | None = None,
    png_dir: Path | None = None,
    headless: bool = False,
) -> None:
    """`later` runs in the background while the window opens (that's the llm call), and
    whatever charts it comes back with get swapped into the open window. with `png_dir`
    every chart also gets saved as a png, and `headless` hides the window and quits after"""
    import webview  # slow to import, so only load it when we actually open a window

    api = _Api(stem, Path.cwd(), started, png_dir, headless)
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)
    window = webview.create_window(
        title, html=build_html(figures, status, export=png_dir is not None), js_api=api,
        width=1100, height=720, hidden=headless,
    )
    window.events.closed += api._closed.set
    api._window = window
    if later:
        threading.Thread(target=api._swap_in, args=(later,), daemon=True).start()
    webview.start()


def _js(value) -> str:
    # escape < so nothing in the data can close the script tag
    return json.dumps(value).replace("<", "\\u003c")


class _Api:
    """stuff the page can call. underscore attributes stay hidden from it"""

    def __init__(
        self, stem: str, out_dir: Path, started: float | None, png_dir: Path | None = None, headless: bool = False
    ):
        self._stem = re.sub(r"[^\w.-]", "_", stem) or "chart"
        self._out_dir = out_dir
        self._started = started
        self._png_dir = png_dir
        self._headless = headless
        self._exported = []
        self._window = None
        self._loaded = threading.Event()
        self._closed = threading.Event()

    def export_png(self, data_url: str, index: int, title: str) -> None:
        slug = re.sub(r"[^a-z0-9]+", "-", html.unescape(title).lower()).strip("-")[:40] or "chart"
        path = self._png_dir / f"{int(index):02d}-{slug}.png"
        path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        self._exported.append(path.name)

    def export_done(self) -> None:
        # written last and renamed into place, so whoever waits on it never reads half a file
        tmp = self._png_dir / "done.json.tmp"
        tmp.write_text(json.dumps({"files": self._exported}))
        tmp.replace(self._png_dir / "done.json")
        if self._headless:
            self.close()

    def save_png(self, data_url: str, index: int) -> str:
        path = self._out_dir / f"fosset-{self._stem}-{int(index)}.png"
        n = 2
        while path.exists():
            path = self._out_dir / f"fosset-{self._stem}-{int(index)}-{n}.png"
            n += 1
        path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        return str(path)

    def rendered(self) -> None:
        self._loaded.set()
        if self._started is not None:
            print(f"first chart on screen: {time.perf_counter() - self._started:.2f}s", file=sys.stderr)

    def _swap_in(self, later) -> None:
        figures, status = later()
        self._loaded.wait(timeout=10)
        if self._closed.is_set():
            return
        self._window.evaluate_js(f"swapIn({_js(figures)}, {_js(status)})")

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
