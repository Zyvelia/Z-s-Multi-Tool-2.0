from .models import PortInfo
from .models import Threat


class ThreatReporter:
    """
    Generates security warnings
    based on discovered services.
    """

    DANGEROUS_PORTS = {
        21: (
            "FTP Exposed",
            "FTP transmits data unencrypted.",
            "Medium"
        ),

        23: (
            "Telnet Exposed",
            "Telnet is insecure and should be disabled.",
            "High"
        ),

        445: (
            "SMB Exposed",
            "SMB can expose file shares to attackers.",
            "Medium"
        ),

        3389: (
            "RDP Exposed",
            "Remote Desktop is accessible.",
            "High"
        )
    }

    def analyze(
        self,
        ports: list[PortInfo]
    ) -> list[Threat]:

        threats = []

        for port_info in ports:

            if port_info.port in self.DANGEROUS_PORTS:

                title, description, severity = (
                    self.DANGEROUS_PORTS[
                        port_info.port
                    ]
                )

                threats.append(
                    Threat(
                        title=title,
                        description=description,
                        severity=severity
                    )
                )

        # Too many open ports

        if len(ports) > 15:

            threats.append(
                Threat(
                    title="Many Open Ports",
                    description=(
                        "Large number of open ports "
                        "detected on this device."
                    ),
                    severity="Medium"
                )
            )

        return threats