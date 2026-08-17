# Remote Access (Tailscale) Setup

The Security Vault's Settings tab can expose a mobile-friendly view of your
vault + authenticator codes to your phone, reachable only from devices on
your own Tailscale network (tailnet). Music Player and YouTube Downloader
each have the same kind of Settings/panel, and all three can now be live
at the same time — Security Vault is always on port 8443, Music Player on
8444, YouTube Downloader on 8445 (see APP_HTTPS_PORTS in
core/services/tailscale_service.py). There's also a new **Remote Hub**
module in the catalog: one page with a single "Go Live" button that brings
all three up at once and gives you one URL — `https://<this-device>.<tailnet>/`
— with buttons linking to whichever apps are currently live. That's the
easiest way to use this from your phone day-to-day; the steps below are
for setting each app up individually the first time. Setup:

1. **Install Tailscale** on this device (Settings tab → "Install Tailscale…")
   and on your phone, and sign both into the same tailnet.

2. **Enable HTTPS Certificates for your tailnet — required, one-time.**
   `tailscale serve` (which is what makes the vault reachable at
   `https://<this-device>.<tailnet>/`) cannot issue a certificate for your
   device until this is turned on. Without it, clicking **Start Remote
   Access** will fail or hang until it times out.

   - Go to the [Tailscale admin console → DNS
     settings](https://login.tailscale.com/admin/dns)
   - Under **HTTPS Certificates**, click **Enable HTTPS...**
   - This only needs to be done once per tailnet, not per device.

3. Back in the app, click **Connect** under "Tailscale network," then
   **Start Remote Access** under "Remote access (view on phone)."

4. On your phone (signed into the same tailnet), open
   `https://<this-device>.<tailnet>:8443/` — or just use the Remote Hub's
   `https://<this-device>.<tailnet>/` if you've also set up the other
   apps — and log in with your vault's master password.

## Troubleshooting

- **"tailscale command timed out" on Connect** — usually means Tailscale
  opened a browser tab for you to approve the login; finish that, then
  click Connect again.
- **"tailscale command timed out" on Start Remote Access** — almost always
  means HTTPS Certificates aren't enabled yet (see step 2 above).
- **"Error changing settings via 'tailscale up'... requires mentioning all
  non-default flags"** — the app always passes `--reset` on `up` to avoid
  this; if you still see it, another tool or the Tailscale GUI likely set
  flags outside the app. Reconnect once from here and it will resolve.
- A console/terminal window briefly flashing when connecting — this is
  fixed in the current build; make sure you're on the latest
  `tailscale_service.py`.