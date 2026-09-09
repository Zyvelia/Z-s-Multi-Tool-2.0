# Minecraft Modpack Support

The Game Server Manager now includes a **Modpacks** tab for Minecraft Java.

## CurseForge

1. Create/get a CurseForge API key from CurseForge's developer/API tooling.
2. Open a Minecraft Java server and select **Modpacks**.
3. Enter the API key and click **Save Key**.
4. Search for a pack and click **Install Latest**, or use **Import ZIP**.

Manifest-based CurseForge packs use the API to resolve and download their listed files.
Server-pack ZIPs are extracted directly. The installer reads the CurseForge manifest and installs the requested Forge, NeoForge, Fabric, or Quilt loader before downloading pack files.

## Safety

Archives are path-validated before extraction to prevent ZIP path traversal. The manager will not install a modpack while the server is running. Mojang EULA acceptance is required before installation.

## Configuration

Installed modpack metadata is saved with the Minecraft server configuration:
- `modpack_provider`
- `modpack_name`
- `modpack_project_id`
- `modpack_file_id`
- `minecraft_version`
- `loader`
- `loader_version`

The existing Minecraft loader support remains responsible for server startup.
