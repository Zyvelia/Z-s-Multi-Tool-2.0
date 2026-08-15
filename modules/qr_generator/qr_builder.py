# modules/qr_generator/qr_builder.py
#
# Turns whatever the user typed into the right payload string for each QR
# type, and wraps the `qrcode` library for actually rendering it. Kept
# separate from ui.py so the UI file only deals with widgets/layout.
#
# Requires the `qrcode` package (pip install qrcode). Everything else here
# (Pillow) is already a dependency elsewhere in this app.

from __future__ import annotations

from dataclasses import dataclass

import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
from PIL import Image

QR_TYPES = ["Text / URL", "Wi-Fi Network", "Email", "Phone Number", "SMS"]

ERROR_CORRECTION_LEVELS = {
    "Low (~7%)": ERROR_CORRECT_L,
    "Medium (~15%)": ERROR_CORRECT_M,
    "Quartile (~25%)": ERROR_CORRECT_Q,
    "High (~30%)": ERROR_CORRECT_H,
}
DEFAULT_ERROR_CORRECTION = "Medium (~15%)"

WIFI_SECURITY_TYPES = ["WPA/WPA2", "WEP", "None"]


class QRBuildError(ValueError):
    """A field the user needs to fix before a payload can be built."""


def _escape_wifi(value: str) -> str:
    # Per the WIFI: QR payload spec, these characters need escaping inside
    # each field: backslash, semicolon, comma, and double quote.
    for ch in ("\\", ";", ",", '"'):
        value = value.replace(ch, "\\" + ch)
    return value


@dataclass
class WifiFields:
    ssid: str = ""
    password: str = ""
    security: str = "WPA/WPA2"
    hidden: bool = False


@dataclass
class EmailFields:
    address: str = ""
    subject: str = ""
    body: str = ""


@dataclass
class SmsFields:
    number: str = ""
    message: str = ""


def build_payload(qr_type: str, *, text: str = "", wifi: WifiFields | None = None,
                   email: EmailFields | None = None, phone: str = "",
                   sms: SmsFields | None = None) -> str:
    """Returns the raw string to encode, or raises QRBuildError with a
    message suitable to show directly in the UI."""

    if qr_type == "Text / URL":
        if not text.strip():
            raise QRBuildError("Enter some text or a URL first.")
        return text.strip()

    if qr_type == "Wi-Fi Network":
        wifi = wifi or WifiFields()
        if not wifi.ssid.strip():
            raise QRBuildError("Network name (SSID) is required.")
        sec_map = {"WPA/WPA2": "WPA", "WEP": "WEP", "None": "nopass"}
        sec = sec_map.get(wifi.security, "WPA")
        password_part = "" if sec == "nopass" else f"P:{_escape_wifi(wifi.password)};"
        hidden_part = "H:true;" if wifi.hidden else ""
        return f"WIFI:T:{sec};S:{_escape_wifi(wifi.ssid)};{password_part}{hidden_part};"

    if qr_type == "Email":
        email = email or EmailFields()
        if not email.address.strip():
            raise QRBuildError("An email address is required.")
        payload = f"mailto:{email.address.strip()}"
        params = []
        if email.subject.strip():
            params.append("subject=" + _url_encode(email.subject.strip()))
        if email.body.strip():
            params.append("body=" + _url_encode(email.body.strip()))
        if params:
            payload += "?" + "&".join(params)
        return payload

    if qr_type == "Phone Number":
        if not phone.strip():
            raise QRBuildError("Enter a phone number first.")
        return f"tel:{phone.strip()}"

    if qr_type == "SMS":
        sms = sms or SmsFields()
        if not sms.number.strip():
            raise QRBuildError("Enter a phone number first.")
        payload = f"smsto:{sms.number.strip()}"
        if sms.message.strip():
            payload += f":{sms.message.strip()}"
        return payload

    raise QRBuildError(f"Unknown QR type: {qr_type}")


def _url_encode(value: str) -> str:
    # Minimal manual encoding (avoids pulling in urllib just for spaces/
    # a handful of reserved characters in mailto: params).
    replacements = {
        " ": "%20", "\n": "%0A", "&": "%26", "?": "%3F", "#": "%23",
        "=": "%3D", "+": "%2B",
    }
    for ch, enc in replacements.items():
        value = value.replace(ch, enc)
    return value


def generate_image(payload: str, *, error_correction: str = DEFAULT_ERROR_CORRECTION,
                    box_size: int = 10, border: int = 4,
                    fill_color: str = "#000000", back_color: str = "#ffffff") -> Image.Image:
    """Renders `payload` to a PIL Image. Raises QRBuildError if the payload
    is too long even at the lowest error-correction level."""
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECTION_LEVELS.get(error_correction, ERROR_CORRECT_M),
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except qrcode.exceptions.DataOverflowError:
        raise QRBuildError(
            "That's too much data for a QR code, even at the lowest error "
            "correction level. Try shortening it."
        )
    img = qr.make_image(fill_color=fill_color, back_color=back_color)
    return img.convert("RGB")
