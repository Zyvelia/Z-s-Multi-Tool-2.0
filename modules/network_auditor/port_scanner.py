import nmap

from .models import PortInfo


class PortScanner:
    """
    Performs port scanning using Nmap.
    """

    def __init__(self):

        self.scanner = nmap.PortScanner()

    def scan(
        self,
        ip: str
    ) -> list[PortInfo]:

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

        except Exception as e:

            print(
                "[PortScanner]",
                e
            )

        return ports