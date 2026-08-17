import socket
import ipaddress
import time
from scapy.all import ARP
from scapy.all import Ether
from scapy.all import srp
import requests

from .models import Device


class NetworkScannerError(Exception):
    """Raised when discovery fails in a way the UI should tell the user
    about (permissions, missing driver, etc.) rather than silently
    returning an empty device list."""


class NetworkScanner:
    """
    Discovers devices on the local network.
    """

    # Free tier of api.macvendors.com is rate-limited to ~1 req/sec.
    # Without a cache + backoff, a /24 scan with 20-30 devices can start
    # getting 429s and each one still costs up to the request timeout.
    VENDOR_LOOKUP_TIMEOUT = 3
    VENDOR_MIN_INTERVAL = 1.1  # seconds between outbound vendor lookups

    def __init__(self):
        self._vendor_cache: dict[str, str] = {}  # OUI (first 8 chars of MAC) -> vendor
        self._last_vendor_call = 0.0

    def discover(
        self,
        network: str = "192.168.1.0/24"
    ) -> list[Device]:

        devices = []

        try:
            arp = ARP(pdst=network)
            ether = Ether(dst="ff:ff:ff:ff:ff:ff")
            packet = ether / arp

            result = srp(packet, timeout=2, verbose=False)[0]

            for _, received in result:
                hostname = self._get_hostname(received.psrc)
                vendor = self.get_vendor(received.hwsrc)

                devices.append(
                    Device(
                        ip=received.psrc,
                        mac=received.hwsrc,
                        hostname=hostname,
                        vendor=vendor
                    )
                )

        except PermissionError as e:
            raise NetworkScannerError(
                "Network scan needs elevated permissions. On Windows, make sure "
                "Npcap is installed and the app is running as administrator."
            ) from e
        except OSError as e:
            # Covers most scapy/libpcap failures (missing Npcap, no interface, etc.)
            raise NetworkScannerError(
                f"Couldn't access the network interface for scanning: {e}"
            ) from e

        return devices

    def _get_hostname(
        self,
        ip: str
    ) -> str:

        try:

            return socket.gethostbyaddr(
                ip
            )[0]

        except Exception:

            return "Unknown"

    def auto_detect_network(self) -> str:
        """
        Automatically detects the local network range (e.g., "192.168.1.0/24").
        """
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            network = ipaddress.ip_network(f"{ip}/24", strict=False)
            return str(network)
        except Exception:
            return "192.168.1.0/24"

    def get_vendor(
        self,
        mac: str
    ) -> str:
        oui = mac.upper()[:8]  # first 3 octets identify the manufacturer
        if oui in self._vendor_cache:
            return self._vendor_cache[oui]

        # Respect the API's ~1 req/sec free-tier limit so a scan with many
        # new devices doesn't start getting 429s partway through.
        elapsed = time.monotonic() - self._last_vendor_call
        if elapsed < self.VENDOR_MIN_INTERVAL:
            time.sleep(self.VENDOR_MIN_INTERVAL - elapsed)

        vendor = "Unknown Vendor"
        try:
            url = f"https://api.macvendors.com/{mac}"
            response = requests.get(url, timeout=self.VENDOR_LOOKUP_TIMEOUT)
            self._last_vendor_call = time.monotonic()

            if response.status_code == 200:
                vendor = response.text
            elif response.status_code == 429:
                # Rate-limited — don't cache this as "Unknown", just leave
                # it uncached so a later scan can retry the lookup.
                return "Unknown Vendor"
        except Exception:
            self._last_vendor_call = time.monotonic()

        self._vendor_cache[oui] = vendor
        return vendor
