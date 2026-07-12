"""
weather.py
Weather data helper using the Open-Meteo API (no API key required).
Includes IP-based location lookup with a hardcoded fallback, and a
lightweight time-based cache to avoid hammering the API on refresh.
"""

import time
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_LOCATION_URL = "https://ipapi.co/json/"

# Fallback location if IP lookup fails (New York City)
FALLBACK_LOCATION = {"lat": 40.7128, "lon": -74.0060, "name": "New York, US"}

CACHE_TTL_SECONDS = 300  # 5 minutes

# Open-Meteo WMO weather codes -> human readable condition + emoji
WEATHER_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    61: ("Slight rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    80: ("Rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "⛈️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ hail", "⛈️"),
    99: ("Thunderstorm w/ heavy hail", "⛈️"),
}

_cache = {"key": None, "timestamp": 0, "data": None}


class WeatherError(Exception):
    """Raised when weather data cannot be retrieved."""


def describe_code(code):
    return WEATHER_CODES.get(code, ("Unknown", "❓"))


def get_ip_location():
    """
    Try to determine an approximate location from the user's IP.
    Falls back to a hardcoded location if the lookup fails.
    """
    try:
        resp = requests.get(IP_LOCATION_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        lat = data.get("latitude")
        lon = data.get("longitude")
        city = data.get("city", "")
        region = data.get("region", "")
        country = data.get("country_name", "")
        if lat is None or lon is None:
            raise WeatherError("IP location response missing coordinates")
        name = ", ".join(p for p in [city, region, country] if p)
        return {"lat": lat, "lon": lon, "name": name or "Current location"}
    except Exception:
        return dict(FALLBACK_LOCATION)


def get_weather(lat=None, lon=None, use_cache=True, unit="C"):
    """
    Fetch current weather + hourly forecast for a given lat/lon.
    If lat/lon are None, attempts IP-based location detection.

    `unit` is "C" (Celsius/km-h) or "F" (Fahrenheit/mph), driven by the
    Settings tab's temperature unit preference.

    Returns a dict:
        {
            "location": str,
            "temperature": float,
            "windspeed": float,
            "condition": str,
            "icon": str,
            "unit": "C" | "F",
            "forecast": [ {"time": str, "temp": float, "condition": str, "icon": str}, ... ]
        }
    """
    if lat is None or lon is None:
        loc = get_ip_location()
        lat, lon, location_name = loc["lat"], loc["lon"], loc["name"]
    else:
        location_name = f"{lat:.2f}, {lon:.2f}"

    unit = "F" if str(unit).upper().startswith("F") else "C"
    temperature_unit = "fahrenheit" if unit == "F" else "celsius"
    windspeed_unit = "mph" if unit == "F" else "kmh"

    cache_key = f"{round(lat, 2)},{round(lon, 2)},{unit}"
    now = time.time()
    if use_cache and _cache["key"] == cache_key and (now - _cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _cache["data"]

    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "hourly": "temperature_2m,weathercode",
        "timezone": "auto",
        "forecast_days": 2,
        "temperature_unit": temperature_unit,
        "windspeed_unit": windspeed_unit,
    }

    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise WeatherError(f"Failed to reach weather service: {exc}") from exc
    except ValueError as exc:
        raise WeatherError(f"Invalid weather response: {exc}") from exc

    current = payload.get("current_weather")
    if not current:
        raise WeatherError("Weather response missing current_weather block")

    condition, icon = describe_code(current.get("weathercode"))

    forecast = []
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weathercode", [])

    # Find the index matching "now" so the forecast starts from the current hour
    start_idx = 0
    current_time = current.get("time")
    if current_time in times:
        start_idx = times.index(current_time)

    for t, temp, code in list(zip(times, temps, codes))[start_idx:start_idx + 12:3]:
        cond, ico = describe_code(code)
        forecast.append({
            "time": t.split("T")[1] if "T" in t else t,
            "temp": temp,
            "condition": cond,
            "icon": ico,
        })

    result = {
        "location": location_name,
        "temperature": current.get("temperature"),
        "windspeed": current.get("windspeed"),
        "condition": condition,
        "icon": icon,
        "unit": unit,
        "forecast": forecast,
    }

    _cache["key"] = cache_key
    _cache["timestamp"] = now
    _cache["data"] = result

    return result
