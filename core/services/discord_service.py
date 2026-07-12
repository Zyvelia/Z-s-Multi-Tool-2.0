from pypresence import Presence
import time


class DiscordService:

    CLIENT_ID = "1491150039253258330"

    def __init__(self):

        self.rpc = None
        self.start_time = int(time.time())
        self.last_details = None  # NEW: Store the last details sent
        self.last_state = None    # NEW: Store the last state sent

    def connect(self):

        try:

            self.rpc = Presence(
                self.CLIENT_ID
            )

            self.rpc.connect()

            self.update(
                "Browsing Tools",
                "In Catalog"
            )

            print("[Discord] Connected")

        except Exception as e:

            print(
                "[Discord] Failed:",
                e
            )

    def update(
        self,
        details,
        state
    ):

        if not self.rpc:
            return

        # NEW: Only update if details or state have actually changed
        if details == self.last_details and state == self.last_state:
            return

        try:

            self.rpc.update(
                details=details,
                state=state,
                start=self.start_time,
                large_image="app_logo",
                large_text="Z's Multi Tool",
                buttons=[
                    {
                        "label": "GitHub",
                        "url": "https://github.com/Zyvelia"
                    },
                    {
                        "label": "Discord",
                        "url": "https://discord.gg/vSX49HJMHS"
                    }
                ]
            )
            self.last_details = details  # NEW: Update last sent details
            self.last_state = state      # NEW: Update last sent state

        except Exception:
            pass

    def clear(self):
        """Clears the Discord Rich Presence status."""
        if not self.rpc:
            return

        # NEW: Only clear if there was an active status to clear
        if self.last_details is None and self.last_state is None:
            return

        try:
            self.rpc.clear()
            self.last_details = None  # NEW: Reset last sent details
            self.last_state = None    # NEW: Reset last sent state
            print("[Discord] RPC cleared.")
        except Exception as e:
            print(f"[Discord] Failed to clear RPC: {e}")

    def close(self):

        try:

            if self.rpc:
                self.rpc.close()

        except Exception:
            pass