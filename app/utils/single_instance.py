"""Keep one Mediary per user session.

Once Mediary can sit in the tray with no window, a second launch - from the
Start menu, a dock icon, or the sign-in entry firing while it is already up -
would otherwise create a duplicate process with its own queue and its own tray
icon. Instead the second process hands off to the first and exits.

Implemented with a ``QLocalServer`` named socket, which needs no extra
dependency and cleans itself up when the owning process dies.
"""

from __future__ import annotations

import getpass
import hashlib

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from app.utils.logging import get_logger

log = get_logger("instance")

WAKE_MESSAGE = b"show"
_CONNECT_TIMEOUT_MS = 400


def _socket_name() -> str:
    """A name unique to this user, so two accounts can each run Mediary."""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - unusual environments have no login name
        user = "default"
    digest = hashlib.sha1(user.encode("utf-8", "ignore")).hexdigest()[:12]
    return f"mediary-{digest}"


class SingleInstanceGuard(QObject):
    """Claims the instance lock, or signals the process that already holds it."""

    #: Emitted in the *first* process when another launch asks it to show itself.
    wake_requested = Signal()

    def __init__(self, parent: QObject | None = None, *, name: str = "") -> None:
        super().__init__(parent)
        # An explicit name lets the tests use an isolated socket rather than
        # colliding with a Mediary the developer happens to have running.
        self._name = name or _socket_name()
        self._server: QLocalServer | None = None
        self._is_primary = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def try_acquire(self) -> bool:
        """True if this process is the only one. False if another already runs."""
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            # Someone is already listening: ask them to surface, then step aside.
            probe.write(WAKE_MESSAGE)
            probe.flush()
            probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            log.info("Another Mediary is already running; asked it to show its window")
            return False

        self._server = QLocalServer(self)
        # A process killed without a clean exit leaves the socket file behind on
        # POSIX; removing a stale name is safe because nothing answered above.
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            log.warning(
                "Could not claim the instance lock (%s); continuing anyway",
                self._server.errorString(),
            )
            self._server = None
            self._is_primary = True
            return True

        self._server.newConnection.connect(self._on_connection)
        self._is_primary = True
        return True

    def _on_connection(self) -> None:
        if self._server is None:
            return
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.disconnected.connect(connection.deleteLater)
        connection.readyRead.connect(lambda: self._on_ready(connection))
        # The payload is tiny and often already buffered by the time we get the
        # connection, in which case readyRead has fired before we connected to
        # it and would never fire again. Drain whatever is waiting.
        if connection.bytesAvailable():
            self._on_ready(connection)

    def _on_ready(self, connection: QLocalSocket) -> None:
        payload = bytes(connection.readAll())
        if WAKE_MESSAGE in payload:
            self.wake_requested.emit()
        connection.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._name)
            self._server = None
