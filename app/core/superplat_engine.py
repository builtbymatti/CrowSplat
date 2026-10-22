import http.server
import logging
import os
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from .base_engine import BaseEngine
from .i18n import tr
from .system import resolve_project_root

# Default port of the viewer itself, distinct from the data server's.
SUPERSPLAT_DEFAULT_PORT = 3000
DATA_SERVER_DEFAULT_PORT = 8000

# How long start_supersplat() waits for `npx serve` to actually bind its port
# before reporting failure, rather than trusting the spawn blindly (audit
# L3-07: `npx serve` can exit quietly on a busy port, or take a moment to
# come up, without raising in this process).
_PORT_PROBE_ATTEMPTS = 75
_PORT_PROBE_DELAY = 0.2  # seconds — ~15s worst case (cold npx start can be slow)


class SuperSplatEngine(BaseEngine):
    """Engine to manage the SuperSplat viewer and its accompanying data server.

    The engine provides methods to start/stop the SuperSplat HTTP server (served via
    ``npx serve``) and a lightweight data server that serves PLY files with proper
    CORS headers. All operations are logged using the structured logger inherited
    from :class:`BaseEngine`.
    """

    def __init__(self, logger_callback: Callable | None = None) -> None:
        """Create a new ``SuperSplatEngine`` instance.

        Parameters
        ----------
        logger_callback: Callable, optional
            Callback used by the base class to forward log messages to the UI.
        """
        super().__init__("SuperSplat", logger_callback)
        self.data_server_thread: threading.Thread | None = None
        self.httpd: socketserver.TCPServer | None = None

    def get_supersplat_path(self) -> Path:
        """Return the absolute path to the bundled SuperSplat distribution."""
        return resolve_project_root() / "engines" / "supersplat"

    @staticmethod
    def _port_is_open(host: str, port: int, timeout: float = 0.2) -> bool:
        """True when something is already accepting TCP connections on host:port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0

    # ---------------------------------------------------------------------
    # SuperSplat viewer management
    # ---------------------------------------------------------------------
    def start_supersplat(self, port: int = SUPERSPLAT_DEFAULT_PORT) -> tuple[bool, str]:
        """Launch the SuperSplat viewer using ``npx serve``.

        Parameters
        ----------
        port: int, default 3000
            Port on which the viewer will be reachable.

        Returns
        -------
        (bool, str)
            ``True`` and a success message on success, otherwise ``False`` and the
            error description.
        """
        splat_path = self.get_supersplat_path()
        if not splat_path.exists():
            return False, tr("err_supersplat_not_found", "Moteur SuperSplat non trouvé")

        # Preconditions checked before spawning: `npx serve dist` otherwise fails
        # with a node-level message that says nothing about what is missing.
        if not (splat_path / "dist").is_dir():
            return False, tr(
                "err_supersplat_not_built",
                "SuperSplat n'est pas construit (dossier 'dist' absent) — "
                "relancez l'installateur de dépendances.",
            )
        if shutil.which("npx") is None:
            return False, tr("err_npx_missing", "npx introuvable — Node.js est requis pour la visualisation.")

        # Someone is already answering on this port — an earlier call, the
        # other SuperSplat screen (pipeline "visualiser" vs tool "supersplat"
        # share the same default ports), or a leftover process. Starting a
        # second `npx serve` here would itself fail to bind, silently.
        if self._port_is_open("127.0.0.1", port):
            # Same convention as msg_supersplat_started: the URL is the {0}
            # placeholder of the translated message.
            reused = tr("msg_supersplat_reused", f"http://localhost:{port}")
            self.log(reused)
            return True, reused

        # Ensure any previous instance is stopped before starting a new one.
        self.stop_supersplat()

        # Bind to loopback only: `-p` listens on every interface, exposing the
        # viewer to the local network.
        cmd = ["npx", "serve", "dist", "-l", f"tcp://127.0.0.1:{port}", "--no-clipboard"]
        try:
            self.runner.start(cmd, env=os.environ.copy(), cwd=str(splat_path))

            def _consume_stdout():
                for line in self.runner.stdout_iter():
                    stripped = line.strip()
                    if stripped:
                        self.log(stripped)

            threading.Thread(target=_consume_stdout, daemon=True).start()

            # `runner.start()` only confirms the process was spawned, not that
            # it actually bound the port. Probe it instead of returning True
            # unconditionally (audit L3-07).
            for _ in range(_PORT_PROBE_ATTEMPTS):
                if self._port_is_open("127.0.0.1", port):
                    started = tr("msg_supersplat_started", f"http://localhost:{port}")
                    self.log(started)
                    return True, started
                returncode = self.runner.poll()
                if isinstance(returncode, int):
                    # The process already exited — no point waiting out the
                    # rest of the probe window.
                    break
                time.sleep(_PORT_PROBE_DELAY)

            self.log(tr("log_supersplat_bind_unconfirmed",
                        "SuperSplat did not confirm binding port {port}.").format(port=port),
                     level=logging.ERROR)
            self.stop_supersplat()
            return False, tr("err_supersplat_bind_failed", str(port))
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self.log(tr("log_supersplat_start_error",
                        "Error starting SuperSplat: {error}").format(error=e),
                     level=logging.ERROR)
            return False, str(e)

    def stop_supersplat(self) -> None:
        """Terminate the SuperSplat viewer process if it is running."""
        # Also called before every start: only report a stop when a process ran.
        was_running = (getattr(self.runner, "_process", None) is not None
                       and self.runner.poll() is None)
        self.runner.terminate()
        if was_running:
            self.log(tr("msg_supersplat_stopped", "SuperSplat arrêté"))

    # ---------------------------------------------------------------------
    # Data server (CORS‑enabled) management
    # ---------------------------------------------------------------------
    def start_data_server(self, directory: str, port: int = DATA_SERVER_DEFAULT_PORT,
                          viewer_port: int = SUPERSPLAT_DEFAULT_PORT) -> tuple[bool, str]:
        """Start a lightweight HTTP server that serves files from *directory*.

        Binds only to ``127.0.0.1``. The CORS fallback origin is the *viewer's*
        port, not this server's: it used to be built from `port`, naming the data
        server itself as the allowed origin, which is never the origin that
        actually asks.
        """
        self.stop_data_server()

        dir_path = Path(directory).expanduser().resolve()
        if not dir_path.is_dir():
            return False, tr("err_data_dir_missing", "Dossier de données introuvable")

        allowed_origin = f"http://localhost:{viewer_port}"
        # Same viewer reached through the loopback IP: the only other origin
        # that may read the data. Any other localhost port is refused.
        allowed_origins = {allowed_origin, f"http://127.0.0.1:{viewer_port}"}

        class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
            """Request handler that injects a safe ``Access-Control-Allow-Origin`` header."""

            def end_headers(self):  # pragma: no cover – exercised via runtime
                origin = self.headers.get('Origin')
                self.send_header('Access-Control-Allow-Origin',
                                 origin if origin in allowed_origins else allowed_origin)
                # The header varies with the request Origin: without this, a shared
                # cache could serve one origin's response to another.
                self.send_header('Vary', 'Origin')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                super().end_headers()

            def send_head(self):
                # Loopback binding alone does not stop DNS rebinding: a hostile
                # domain re-resolved to 127.0.0.1 would be same-origin with this
                # server and could read the served folder. Only answer requests
                # addressed to a loopback host name.
                host = urlparse(f"//{self.headers.get('Host', '')}").hostname
                if host not in ('localhost', '127.0.0.1'):
                    self.send_error(403)
                    return None
                # The viewer only ever asks for a file: no directory listing,
                # and no index.html either.
                if os.path.isdir(self.translate_path(self.path)):
                    self.send_error(403, "Directory listing disabled")
                    return None
                return super().send_head()

            def list_directory(self, path):
                self.send_error(403, "Directory listing disabled")
                return None

            def log_message(self, format, *args):  # Suppress noisy default logging
                return

        class _ReuseAddrTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        handler = partial(CORSRequestHandler, directory=str(dir_path))

        # Bound here rather than inside the thread. Assigning self.httpd from the
        # worker left a window where stop_data_server() read None and returned,
        # leaving a server running with nothing holding a reference to it.
        try:
            self.httpd = _ReuseAddrTCPServer(("127.0.0.1", port), handler)
        except OSError as e:
            self.log(tr("log_data_server_bind_error",
                        "Data server bind error: {error}").format(error=e),
                     level=logging.ERROR)
            return False, tr("err_data_server_bind", str(e))

        def run_server():  # pragma: no cover - runs in a background thread
            try:
                self.httpd.serve_forever()
            except (OSError, ValueError) as e:
                self.log(tr("log_data_server_error",
                            "Data server error: {error}").format(error=e),
                         level=logging.ERROR)

        self.data_server_thread = threading.Thread(target=run_server, daemon=True)
        self.data_server_thread.start()

        started = tr("msg_data_server_started", f"http://localhost:{port}")
        self.log(started)
        return True, started

    def stop_data_server(self) -> None:
        """Shut down the data server and clean up its thread."""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.log(tr("msg_data_server_stopped", "Serveur de données arrêté"))
        if self.data_server_thread:
            self.data_server_thread.join(timeout=1)
            self.data_server_thread = None

    def stop_all(self) -> None:
        """Convenience method to stop both the viewer and the data server."""
        self.stop_supersplat()
        self.stop_data_server()
