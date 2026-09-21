# Z's Multi Tool — Client / Developer Layout

The project uses one shared source tree. The public client does not contain the publisher implementation.

- `core/`, `modules/`, `pages/`: shared application source.
- `developer/publisher/`: developer-only marketplace publishing implementation.
- `developer/main.py`: standalone publisher GUI.
- `build_client.bat`: builds the public client.
- `build_developer.bat`: builds the private publisher app.
- `Client/`: client build output.
- `Developer/`: publisher build output.

The client reads the marketplace from the configured `marketplace_url`. The default is the public `Zyvelia/zmt-marketplace` GitHub index.

Do not put GitHub write tokens in the client project or client build. Keep publisher credentials in the developer environment only.
