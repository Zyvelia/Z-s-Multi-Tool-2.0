# modules/notification_mirror/__init__.py

from .ui import NotificationMirrorPage


def open_notification_mirror(manager):
    return NotificationMirrorPage(manager.container, manager)


# NOTE: Notification Mirror is disabled for now (not registered as a tool
# tab). Module code is kept in place — a proper notification feature is
# planned later. To re-enable, restore the `manager.register(...)` call
# that used to live in this function.
def register(manager):
    pass
