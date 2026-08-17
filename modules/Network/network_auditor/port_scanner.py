import shutil
import nmap

from .models import PortInfo


class PortScannerError(Exception):
    """Raised when the scan can't run at all (e.g. Nmap isn't installed),
    as opposed to running and simply finding zero open ports."""


class PortScanner:
    """
    Performs port scanning using Nmap.
    """

    def __init__(self):
        self.scanner = nmap.PortScanner()

    @staticmethod
    def is_nmap_available() -> bool:
        """python-nmap is just a wrapper around the nmap CLI binary — if
        it isn't on PATH, scans fail silently and return no ports with no
        indication why. Check once up front so the UI can say something
        useful instead."""
        return shutil.which("nmap") is not None

    def scan(
        self,
        ip: str
    ) -> list[PortInfo]:

        if not self.is_nmap_available():
            raise PortScannerError(
                "Nmap isn't installed (or not on PATH). Install it from "
                "nmap.org to enable port scanning."
            )

        ports = []

        try:

            self.scanner.scan(
                hosts=ip,
                arguments="-F"
            )

            if ip not in self.scanner.all_hosts():
                return ports

            for protocol in self.scanner[ip].all_protocols():

                protocol_data = self.scanner[ip][protocol]

                for port in protocol_data.keys():

                    service = protocol_data[port].get(
                        "name",
                        "unknown"
                    )

                    ports.append(
                        PortInfo(
                            port=port,
                            service=service
                        )
                    )

        except nmap.PortScannerError as e:
            raise PortScannerError(f"Nmap scan failed: {e}") from e

        return ports
