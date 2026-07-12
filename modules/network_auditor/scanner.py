import socket
import ipaddress
from scapy.all import ARP
from scapy.all import Ether
from scapy.all import srp
import requests # Added this import

from .models import Device


class NetworkScanner:
    """
    Discovers devices on the local network.
    """

    def discover(
        self,
        network: str = "192.168.1.0/24"
    ) -> list[Device]:

        devices = []

        try:

            arp = ARP(
                pdst=network
            )

            ether = Ether(
                dst="ff:ff:ff:ff:ff:ff"
            )

            packet = ether / arp

            result = srp(
                packet,
                timeout=2,
                verbose=False
            )[0]

            for _, received in result:
                # Added print statement
                print(
                    "FOUND:",
                    received.psrc,
                    received.hwsrc
                )

                hostname = self._get_hostname(
                    received.psrc
                )

                # Replaced this block as requested
                vendor = self.get_vendor(
                    received.hwsrc
                )

                devices.append(
                    Device(
                        ip=received.psrc,
                        mac=received.hwsrc,
                        hostname=hostname,
                        vendor=vendor
                    )
                )

        except Exception as e:

            print(
                "[NetworkScanner]",
                e
            )

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

    # Added this method
    def get_vendor(
        self,
        mac: str
    ) -> str:

        try:

            url = (
                f"https://api.macvendors.com/{mac}"
            )

            response = requests.get(
                url,
                timeout=3
            )

            if response.status_code == 200:

                return response.text

        except Exception:
            pass

        return "Unknown Vendor"