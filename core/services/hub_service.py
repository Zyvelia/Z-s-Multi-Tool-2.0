# core/services/hub_service.py
#
# Builds the single static HTML file that `tailscale_service.enable_hub_page()`
# serves at this device's default tailnet address (https://<this-device>.<tailnet>/).
# It's just a links page — three buttons, one per app, each pointing at that
# app's own fixed HTTPS port (see APP_HTTPS_PORTS in tailscale_service.py).
#
# Deliberately a plain static file rather than a proxied web app: `tailscale
# serve --set-path=/something` mounting a real app under a sub-path is known
# to break apps that use root-relative asset/API paths (e.g. fetch('/api/x')
# resolves against the mount path, not the app's own root) — see
# https://github.com/tailscale/tailscale/issues/12413. Giving each app its
# own port instead of its own path sidesteps that entirely, and this page
# only ever needs to link OUT to full https://host:port/ URLs, which works
# regardless of what path it's served from.

from core import paths

HUB_HTML_PATH = paths.data_path("tailscale", "hub.html")

# (app_key, label, icon, blurb) — must match APP_HTTPS_PORTS in tailscale_service.py
APPS = [
    ("vault", "Security Vault", "🔒", "Passwords + authenticator codes"),
    ("music", "Music Player", "🎵", "Stream your library"),
    ("yt", "YouTube Downloader", "⬇️", "Send a link, get a download"),
]


def build_hub_html(hostname, live_apps):
    """
    hostname: this device's tailnet DNS name (e.g. "my-desktop.tailnet-name.ts.net")
    live_apps: set/list of app_key strings currently reachable (from
               TailscaleService.is_app_serving), so the page can show which
               buttons will actually work right now instead of guessing.
    """
    from core.services.tailscale_service import APP_HTTPS_PORTS

    live_apps = set(live_apps or [])
    cards = []
    for key, label, icon, blurb in APPS:
        port = APP_HTTPS_PORTS[key]
        url = f"https://{hostname}:{port}/"
        live = key in live_apps
        status = (
            '<span class="dot on"></span>Live'
            if live else '<span class="dot off"></span>Off — start it from the app on your PC'
        )
        button = (
            f'<a class="card{"" if live else " disabled"}" href="{url}">'
            f'<div class="icon">{icon}</div>'
            f'<div class="info"><div class="label">{label}</div>'
            f'<div class="blurb">{blurb}</div>'
            f'<div class="status">{status}</div></div>'
            f'</a>'
        )
        cards.append(button)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Remote Hub</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#a78bfa;
    --text:#e8ecf1; --muted:#8a93a6; --success:#3ecf8e; --off:#5a6273;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-tap-highlight-color:transparent;
  }}
  .wrap {{ max-width:520px; margin:0 auto; padding:28px 16px 60px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:22px; }}
  .card {{
    display:flex; align-items:center; gap:14px; background:var(--panel);
    border-radius:14px; padding:16px; margin-bottom:12px; text-decoration:none;
    color:var(--text); border:1px solid #22283a;
  }}
  .card.disabled {{ opacity:0.45; pointer-events:none; }}
  .icon {{ font-size:28px; }}
  .label {{ font-weight:700; font-size:16px; }}
  .blurb {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  .status {{ font-size:12px; margin-top:6px; display:flex; align-items:center; color:var(--muted); }}
  .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:6px; }}
  .dot.on {{ background:var(--success); }}
  .dot.off {{ background:var(--off); }}
  .foot {{ color:var(--muted); font-size:12px; margin-top:24px; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Remote Hub</h1>
  <div class="sub">Reachable only from devices on your own Tailscale network.</div>
  {''.join(cards)}
  <div class="foot">Refresh this page after starting an app on your PC.</div>
</div>
</body>
</html>
"""


def write_hub_html(hostname, live_apps):
    html = build_hub_html(hostname, live_apps)
    with open(HUB_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return HUB_HTML_PATH
