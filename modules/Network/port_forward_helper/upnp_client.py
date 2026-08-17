# modules/Network/port_forward_helper/upnp_client.py
#
# Minimal pure-Python UPnP IGD (Internet Gateway Device) client.
#
# No extra dependency needed — SSDP discovery is done with a raw UDP
# socket, and the device description / SOAP calls just use `requests`
# (already in requirements.txt). This talks directly to the router's
# WANIPConnection / WANPPPConnection service, the same one Windows
# itself uses for "NAT-PMP/UPnP" port forwarding.

import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

# Most home routers implement WANIPConnection; some (mostly older/PPPoE
# setups) implement WANPPPConnection instead. Either works identically
# for our purposes (AddPortMapping/DeletePortMapping/GetExternalIPAddress
# have the same signature on both).
WAN_SERVICE_TYPES = (
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)


class UPnPError(Exception):
    """Raised for any router-communication failure (discovery, SOAP
    fault, malformed XML, etc). Message is meant to be shown to the user
    as-is."""
    pass


class PortMapping:
    """One entry from the router's NAT port-mapping table."""

    def __init__(self, external_port, protocol, internal_client,
                 internal_port, enabled, description, lease_duration):
        self.external_port = int(external_port)
        self.protocol = protocol.upper()
        self.internal_client = internal_client
        self.internal_port = int(internal_port)
        self.enabled = str(enabled) in ("1", "true", "True")
        self.description = description or ""
        self.lease_duration = int(lease_duration) if str(lease_duration).isdigit() else 0


class IGDDevice:
    """A discovered router with a usable WAN connection service."""

    def __init__(self, control_url, service_type, friendly_name, location):
        self.control_url = control_url
        self.service_type = service_type
        self.friendly_name = friendly_name
        self.location = location


# =====================================================
# DISCOVERY
# =====================================================

def discover(timeout=3.0):
    """Broadcast SSDP M-SEARCH, then probe every device that answers
    for a usable WANIPConnection/WANPPPConnection service.

    Returns the first working IGDDevice found, or raises UPnPError.
    """
    locations = _ssdp_search(timeout)
    if not locations:
        raise UPnPError(
            "No UPnP-capable router found. Make sure UPnP is enabled "
            "in your router's settings (often under NAT / Forwarding)."
        )

    errors = []
    for location in locations:
        try:
            device = _probe_device(location)
            if device:
                return device
        except Exception as e:
            errors.append(f"{location}: {e}")

    detail = " / ".join(errors) if errors else "no responsive device"
    raise UPnPError(
        f"Found {len(locations)} UPnP device(s) but none exposed a WAN "
        f"connection service ({detail})."
    )


def _ssdp_search(timeout):
    locations = set()
    search_targets = [
        "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
        "ssdp:all",
    ]

    for st in search_targets:
        message = (
            "M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 2\r\n"
            f"ST: {st}\r\n"
            "\r\n"
        ).encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        try:
            sock.sendto(message, (SSDP_ADDR, SSDP_PORT))
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    data, _addr = sock.recvfrom(65507)
                except socket.timeout:
                    break
                loc = _extract_header(data.decode("utf-8", errors="ignore"), "location")
                if loc:
                    locations.add(loc)
        except OSError:
            pass
        finally:
            sock.close()

        if locations:
            # Got at least one hit on this search target — no need to
            # keep broadcasting ssdp:all etc.
            break

    return list(locations)


def _extract_header(raw_response, header_name):
    for line in raw_response.split("\r\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip().lower() == header_name.lower():
            return value.strip()
    return None


def _probe_device(location):
    resp = requests.get(location, timeout=4)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    friendly_name = _find_text(root, ".//d:device/d:friendlyName", ns) or "Router"

    service = _find_wan_service(root, ns)
    if not service:
        return None

    service_type, control_url_raw = service
    control_url = urljoin(location, control_url_raw)

    return IGDDevice(control_url, service_type, friendly_name, location)


def _find_wan_service(root, ns):
    """Walk the device -> deviceList -> device -> ... tree looking for
    any <service> whose serviceType matches one we support. UPnP IGD
    nests the WAN service 2-3 levels deep, so this recurses rather than
    assuming a fixed depth."""
    for service in root.iter("{urn:schemas-upnp-org:device-1-0}service"):
        service_type = _find_text(service, "d:serviceType", ns)
        control_url = _find_text(service, "d:controlURL", ns)
        if service_type in WAN_SERVICE_TYPES and control_url:
            return service_type, control_url
    return None


def _find_text(elem, path, ns):
    found = elem.find(path, ns)
    return found.text.strip() if found is not None and found.text else None


# =====================================================
# SOAP ACTIONS
# =====================================================

def _soap_call(device: IGDDevice, action, args=None, timeout=5):
    args = args or {}
    args_xml = "".join(
        f"<{k}>{'' if v is None else v}</{k}>" for k, v in args.items()
    )
    body = (
        '<?xml version="1.0"?>\r\n'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{device.service_type}">{args_xml}</u:{action}>'
        "</s:Body></s:Envelope>"
    )
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{device.service_type}#{action}"',
    }

    try:
        resp = requests.post(
            device.control_url, data=body.encode("utf-8"),
            headers=headers, timeout=timeout,
        )
    except requests.RequestException as e:
        raise UPnPError(f"Couldn't reach the router: {e}") from e

    if resp.status_code != 200:
        raise UPnPError(_parse_soap_fault(resp.content, action, resp.status_code))

    try:
        return ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise UPnPError(f"Router returned malformed response to {action}: {e}") from e


def _parse_soap_fault(content, action, status_code):
    try:
        root = ET.fromstring(content)
        code = None
        description = None
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "errorCode":
                code = elem.text
            elif tag == "errorDescription":
                description = elem.text
        if code or description:
            return f"{action} failed — router error {code}: {description}"
    except ET.ParseError:
        pass
    return f"{action} failed — router returned HTTP {status_code}"


def get_external_ip(device: IGDDevice):
    root = _soap_call(device, "GetExternalIPAddress")
    for elem in root.iter():
        if elem.tag.split("}")[-1] == "NewExternalIPAddress":
            return elem.text
    raise UPnPError("Router didn't return an external IP address.")


def list_mappings(device: IGDDevice, max_entries=200):
    """Walks GetGenericPortMappingEntry by index until the router
    signals it's out of entries (this is the standard, if clunky, way
    UPnP IGD exposes the existing mapping table)."""
    mappings = []
    for index in range(max_entries):
        try:
            root = _soap_call(
                device, "GetGenericPortMappingEntry",
                {"NewPortMappingIndex": index},
            )
        except UPnPError as e:
            # "SpecifiedArrayIndexInvalid" (or similar) just means we've
            # reached the end of the table — that's a normal stop
            # condition, not a real failure.
            if "array" in str(e).lower() or "invalid" in str(e).lower() or "index" in str(e).lower():
                break
            raise

        values = {}
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag.startswith("New"):
                values[tag] = elem.text

        if not values.get("NewExternalPort"):
            break

        mappings.append(PortMapping(
            external_port=values.get("NewExternalPort", 0),
            protocol=values.get("NewProtocol", "TCP"),
            internal_client=values.get("NewInternalClient", ""),
            internal_port=values.get("NewInternalPort", 0),
            enabled=values.get("NewEnabled", "0"),
            description=values.get("NewPortMappingDescription", ""),
            lease_duration=values.get("NewLeaseDuration", "0"),
        ))

    return mappings


def add_mapping(device: IGDDevice, external_port, internal_port,
                 internal_client, protocol="TCP", description="",
                 lease_duration=0):
    _soap_call(device, "AddPortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": external_port,
        "NewProtocol": protocol.upper(),
        "NewInternalPort": internal_port,
        "NewInternalClient": internal_client,
        "NewEnabled": 1,
        "NewPortMappingDescription": description or "Z's Multi Tool",
        "NewLeaseDuration": lease_duration,
    })


def delete_mapping(device: IGDDevice, external_port, protocol="TCP"):
    _soap_call(device, "DeletePortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": external_port,
        "NewProtocol": protocol.upper(),
    })


def get_local_ip():
    """Best-effort LAN IP for this machine, used as the default
    'Internal Client' when adding a new mapping. Doesn't actually send
    any traffic — connect() on a UDP socket just forces the OS to pick
    a route/interface."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
