"""In-memory session store."""
import time
import logging

logger = logging.getLogger("service.session")

_SESSIONS = {}


def get_session(session_id):
    """Return an active session, removing it if it has expired."""
    session = _SESSIONS.get(session_id)
    if session is None:
        return None
    if session["expires_at"] < time.time():
        # TODO: log when a session expires (include session["user_id"])
        del _SESSIONS[session_id]
        return None
    return session
