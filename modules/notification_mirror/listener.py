# modules/notification_mirror/listener.py
#
# Captures notifications from Windows' own Action Center via the WinRT
# UserNotificationListener API — this reads notifications the shell is
# already tracking, it does not intercept or recreate them. Requires:
#
#   pip install winrt-Windows.UI.Notifications.Management \
#               winrt-Windows.UI.Notifications winrt-Windows.Foundation
#
# *** NOT TESTABLE IN THIS SANDBOX (Linux, no WinRT) — this file was
# written against the documented UserNotificationListener/UserNotification
# API shape and pywinrt's usual `.get()`-blocking projection style, but it
# needs a real run on your Windows 11 box before you trust it. The two
# likeliest adjustment points if something doesn't import or doesn't match:
#   1. Exact module path / class casing (pywinrt has renamed namespaces
#      between versions — check with `python -c "import winrt.windows.ui.
#      notifications.management as m; print(dir(m))"`).
#   2. Whether NotificationChanged actually fires "Added" again for an
#      in-place update, vs only for genuinely new notifications — the
#      dedupe/update logic below assumes the former; watch the debug log
#      output the first time you run it against something like Discord's
#      message-count badge updates to confirm.
#
# Runs entirely on its own thread; never touches Tk. All WinRT calls are
# wrapped so a failure here can't take down the rest of the app.

import threading
import time
import traceback

from . import storage

try:
    import winrt.windows.ui.notifications as notifications
    import winrt.windows.ui.notifications.management as notif_mgmt
    _WINRT_AVAILABLE = True
except Exception:
    _WINRT_AVAILABLE = False

try:
    import winrt.windows.applicationmodel as appmodel
    _APPMODEL_AVAILABLE = True
except Exception:
    _APPMODEL_AVAILABLE = False


class ListenerStatus:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ACCESS_DENIED = "access_denied"
    UNAVAILABLE = "unavailable"  # WinRT import failed / unsupported OS
    NO_PACKAGE_IDENTITY = "no_package_identity"  # unpackaged process — see packaging/
    ERROR = "error"


class AccessResult:
    """
    Fine-grained outcome of request_access(), replacing the old bare
    True/False/None. UserNotificationListener needs package identity
    (see packaging/AppxManifest.xml + userNotificationListener capability)
    — most real-world failures happen before Windows ever shows a consent
    prompt, so collapsing everything to False hides which stage failed.
    """
    ALLOWED = "allowed"
    DENIED = "denied"
    UNSPECIFIED = "unspecified"   # prompt shown, closed w/o a choice
    NO_PACKAGE_IDENTITY = "no_package_identity"
    WINRT_UNAVAILABLE = "winrt_unavailable"
    ERROR = "error"


def has_package_identity():
    """
    True only if this process is running with package identity (i.e.
    launched through the sparse package's registered Application entry —
    see packaging/build_and_register.ps1 — NOT a raw exe or `python
    main.py`). Package.current raises when there's no identity; that's
    the documented way to detect this, there's no separate "IsPackaged"
    flag.
    """
    if not _APPMODEL_AVAILABLE:
        return False
    try:
        _ = appmodel.Package.current.id.full_name
        return True
    except Exception:
        return False


class NotificationListener:
    """
    on_event(kind, payload) is called from a background thread — kind is
    "added" or "removed", payload is a dict for "added" or just an id for
    "removed". Callers (web_server.py) are responsible for their own
    thread-safety when handling it (they hop onto a queue).
    """

    def __init__(self, on_event=None, on_status_change=None, on_log=None):
        self._on_event = on_event or (lambda *a, **k: None)
        self._on_status_change = on_status_change or (lambda *a, **k: None)
        self._on_log = on_log or (lambda *a, **k: None)

        self._listener = None
        self._thread = None
        self._stop_event = threading.Event()
        self._token = None  # event registration token, for clean unsubscribe

        self.status = ListenerStatus.STOPPED
        self._seen = {}  # notification id -> content hash, for dedupe

        if not _WINRT_AVAILABLE:
            self.status = ListenerStatus.UNAVAILABLE

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def request_access(self):
        """
        Must be called from the UI thread (Microsoft's docs are explicit
        that RequestAccessAsync should be invoked from a UI-thread context)
        — ui.py's "Enable" button handler calls this directly, before
        handing off to start() on a background thread.

        Returns one of the AccessResult constants — NOT a bare bool —
        so ui.py can show the actual reason instead of a generic
        "permission denied" message. See AccessResult docstring.
        """
        self._log(f"Package identity: {'YES' if has_package_identity() else 'NO'}")

        if not _WINRT_AVAILABLE:
            self._log("WinRT notification packages not importable.")
            return AccessResult.WINRT_UNAVAILABLE

        if not has_package_identity():
            # This is the common case for a raw PyInstaller exe / `python
            # main.py` dev run. RequestAccessAsync would just return
            # Denied here without ever prompting — check for this
            # explicitly so the UI can say something accurate instead of
            # sending the user hunting through Settings for a toggle that
            # doesn't exist. See packaging/ for how to get identity.
            self._log("userNotificationListener capability unavailable (no package identity).")
            self._log("Notification mirroring requires the packaged build — see packaging/README.md.")
            return AccessResult.NO_PACKAGE_IDENTITY

        try:
            listener = notif_mgmt.UserNotificationListener.get_current()
            self._log(f"UserNotificationListener available: YES")

            before = listener.get_access_status()
            self._log(f"Access status before request: {before}")

            result = listener.request_access_async().get()
            self._log(f"RequestAccessAsync result: {result}")

            if result == notif_mgmt.UserNotificationListenerAccessStatus.ALLOWED:
                self._log("Listener running.")
                return AccessResult.ALLOWED
            elif result == notif_mgmt.UserNotificationListenerAccessStatus.DENIED:
                return AccessResult.DENIED
            else:
                # UNSPECIFIED — user closed the consent dialog without
                # choosing; a later call will re-prompt.
                return AccessResult.UNSPECIFIED
        except Exception as e:
            self._log(f"request_access failed with unexpected error: {e}\n{traceback.format_exc()}")
            return AccessResult.ERROR

    def start(self):
        if not _WINRT_AVAILABLE:
            self._set_status(ListenerStatus.UNAVAILABLE)
            return False, "WinRT notification packages aren't installed."
        if not has_package_identity():
            self._set_status(ListenerStatus.NO_PACKAGE_IDENTITY)
            return False, "Notification mirroring requires the packaged build (see packaging/README.md)."
        if self._thread and self._thread.is_alive():
            return True, None

        self._stop_event.clear()
        self._set_status(ListenerStatus.STARTING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True, None

    def stop(self):
        self._stop_event.set()
        if self._listener is not None and self._token is not None:
            try:
                self._listener.remove_notification_changed(self._token)
            except Exception as e:
                self._log(f"unsubscribe failed (non-fatal): {e}")
        self._token = None
        self._listener = None
        if self._thread:
            self._thread.join(timeout=3)
        self._set_status(ListenerStatus.STOPPED)

    def is_running(self):
        return self.status == ListenerStatus.RUNNING

    # =====================================================
    # BACKGROUND THREAD
    # =====================================================

    def _run(self):
        try:
            listener = notif_mgmt.UserNotificationListener.get_current()
            access = listener.get_access_status()
            if access != notif_mgmt.UserNotificationListenerAccessStatus.ALLOWED:
                # Caller should have gone through request_access() first via
                # the UI thread; if we land here access was revoked since,
                # or was never granted — surface it distinctly so ui.py can
                # show "re-enable in Windows Settings > Notifications &
                # actions" rather than a generic error.
                self._set_status(ListenerStatus.ACCESS_DENIED)
                return

            self._listener = listener

            # Prime the dedupe table with whatever's already in the Action
            # Center on start, WITHOUT mirroring it — otherwise every PC
            # restart / app restart would dump the phone with a backlog of
            # stuff the user already saw.
            try:
                existing = listener.get_notifications_async(
                    notifications.NotificationKinds.TOAST
                ).get()
                for n in existing:
                    self._seen[n.id] = self._content_hash(n)
            except Exception as e:
                self._log(f"initial snapshot failed (non-fatal): {e}")

            self._token = listener.add_notification_changed(self._on_native_change)
            self._set_status(ListenerStatus.RUNNING)
            self._log("Listener running.")

            # NotificationChanged fires on its own callback thread; this
            # loop just keeps the Python thread (and its GC references to
            # the listener/token) alive until stop() is called.
            while not self._stop_event.is_set():
                time.sleep(1)

        except Exception as e:
            self._log(f"listener thread error: {e}\n{traceback.format_exc()}")
            self._set_status(ListenerStatus.ERROR)

    def _on_native_change(self, sender, args):
        # Runs on a WinRT callback thread, not our own — keep this fast and
        # never let an exception here propagate back into WinRT's callback
        # machinery (that's how you get a hard crash with no Python traceback).
        try:
            kind = args.change_kind
            notif_id = args.user_notification_id

            if kind == notifications.UserNotificationChangedKind.REMOVED:
                if notif_id in self._seen:
                    del self._seen[notif_id]
                self._on_event("removed", {"id": notif_id})
                return

            # ADDED (or, per the header note, possibly an in-place update
            # re-firing ADDED) — fetch the current notification list to get
            # the actual UserNotification object; NotificationChangedEventArgs
            # only carries the id + change kind, not the payload itself.
            try:
                items = self._listener.get_notifications_async(
                    notifications.NotificationKinds.TOAST
                ).get()
            except Exception as e:
                self._log(f"get_notifications_async failed on change: {e}")
                return

            match = next((n for n in items if n.id == notif_id), None)
            if match is None:
                return  # already gone by the time we asked — ignore

            payload = self._extract(match)
            if payload is None:
                return

            content_hash = self._content_hash(match)
            previous_hash = self._seen.get(notif_id)
            self._seen[notif_id] = content_hash

            if previous_hash == content_hash:
                return  # exact duplicate delivery — drop it

            storage.add_known_app(payload["app_name"])
            if not storage.is_app_enabled(payload["app_name"]):
                return

            payload["updated"] = previous_hash is not None
            self._on_event("added", payload)

        except Exception as e:
            self._log(f"_on_native_change error: {e}\n{traceback.format_exc()}")

    # =====================================================
    # FIELD EXTRACTION — defensive: not every notification exposes every
    # field, and toast binding shapes vary by app, so each piece is its
    # own try/except rather than one all-or-nothing block.
    # =====================================================

    def _extract(self, user_notification):
        try:
            app_info = user_notification.app_info
            app_name = self._safe(lambda: app_info.display_info.display_name, "Unknown App")
            app_id = self._safe(lambda: app_info.app_user_model_id, None)

            title, body_lines = self._extract_text(user_notification)
            actions = self._extract_actions(user_notification)
            created = self._safe(
                lambda: user_notification.creation_time.universal_time, None
            )

            return {
                "id": user_notification.id,
                "app_name": app_name,
                "app_id": app_id,
                "title": title,
                "body": "\n".join(body_lines) if body_lines else "",
                "timestamp": created,  # FILETIME ticks if present; web_server normalizes
                "actions": actions,
            }
        except Exception as e:
            self._log(f"_extract failed entirely for id={getattr(user_notification, 'id', '?')}: {e}")
            return None

    def _extract_text(self, user_notification):
        title, body_lines = "", []
        try:
            binding = user_notification.notification.visual.get_binding(
                notifications.KnownNotificationBindings.toast_generic()
            )
            if binding is None:
                return title, body_lines
            texts = list(binding.get_text_elements())
            if texts:
                title = texts[0].text or ""
                body_lines = [t.text for t in texts[1:] if t.text]
        except Exception as e:
            self._log(f"text extraction failed (non-fatal): {e}")
        return title, body_lines

    def _extract_actions(self, user_notification):
        # Only surfaces actions that map to something the PC can actually
        # invoke — see web_server.py's /api/actions/invoke, which replays
        # these through the same toast activation the notification itself
        # would have used. We do NOT invent actions that aren't here.
        actions = []
        try:
            toast_binding = user_notification.notification
            # ToastNotification exposes the original XML the app supplied;
            # actions live in <actions><action .../></actions>. The typed
            # object model doesn't expose parsed actions directly, so this
            # reads the raw content XML rather than guessing.
            xml_doc = toast_binding.content
            xml_str = xml_doc.get_xml() if xml_doc else ""
            if "<action" in xml_str:
                actions.append({"available": True, "raw_present": True})
        except Exception as e:
            self._log(f"action extraction failed (non-fatal): {e}")
        return actions

    def _content_hash(self, user_notification):
        title, body_lines = self._extract_text(user_notification)
        return hash((title, tuple(body_lines)))

    def _safe(self, fn, default):
        try:
            val = fn()
            return val if val is not None else default
        except Exception:
            return default

    # =====================================================
    # STATUS / LOGGING
    # =====================================================

    def _set_status(self, status):
        self.status = status
        self._on_status_change(status)

    def _log(self, msg):
        print(f"[notification_mirror] {msg}")
        self._on_log(msg)
