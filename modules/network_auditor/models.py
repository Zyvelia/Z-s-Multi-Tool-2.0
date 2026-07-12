from dataclasses import dataclass
from typing import List


@dataclass
class Device:
    """
    Represents a device found on the network.
    """

    ip: str
    mac: str
    hostname: str = "Unknown"
    vendor: str = "Unknown" # Added this line


@dataclass
class PortInfo:
    """
    Represents an open port.
    """

    port: int
    service: str


@dataclass
class Threat:
    """
    Represents a security warning.
    """

    title: str
    description: str
    severity: str


@dataclass
class ScanResult:
    """
    Full scan result for a device.
    """

    device: Device
    ports: List[PortInfo]
    threats: List[Threat]