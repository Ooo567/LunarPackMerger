# 🌙 Lunar Pack Merger

A small Windows tool for merging multiple Minecraft resource packs (texture packs)
into one, built for **Lunar Client 1.8.9 / Hypixel** but works with any vanilla
1.8.9-compatible pack.

Instead of only being able to load one texture pack at a time, this lets you
combine, say, a PvP-focused pack with a separate GUI pack or cape pack into a
single `.zip` you drop straight into your resource packs folder.

![status](https://img.shields.io/badge/platform-Windows-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## Features

- Add any number of `.zip` resource packs
- Reorder them by priority — higher in the list wins when two packs edit the
  same file
- One click **Merge** → outputs a single ready-to-use `.zip`
- Auto-generates a valid `pack.mcmeta` if your packs don't have one
- Log panel shows exactly which files conflicted and which pack won
- Runs fully offline — no network access, no telemetry, nothing sent anywhere
- Clean, modern dark UI

## Download

Grab the latest `LunarPackMerger.exe` from the **[Releases](../../releases)**
tab — no install needed, no Python required, just run it.

> The exe is built automatically by GitHub Actions directly from this
> repo's source (see `.github/workflows/build.yml`), not compiled on
> anyone's personal machine. You can read every line of code that goes
> into it before you run it.

## How to use

1. Open `LunarPackMerger.exe`
2. Click **＋ Add Pack(s)** and select two or more resource pack `.zip` files
3. Use **↑ Move Up / ↓ Move Down** to set priority — the pack at the top wins
   any file conflicts (see the tip banner in the app for a suggested order)
4. Give your merged pack a name (and optional description)
5. Click **Merge Packs** and choose where to save the output `.zip`
6. Drop the resulting `.zip` into your resource packs folder:

   ```
   %appdata%\.minecraft\resourcepacks
   ```

   (In Lunar Client / Minecraft: **Options → Resource Packs → Open Resource
   Pack Folder** will take you straight there.)

7. Select it in-game like any other resource pack

## Tips for a good merge

- Put your **main/base pack** (the one with the most textures — e.g. a full
  PvP or FPS-boost pack) at the **top** of the list
- Put small **add-on packs** (GUI-only, cape, HUD, crosshair tweaks) **lower**
  down, so they only overwrite the handful of files they're actually meant to
  change
- Check the log after merging — it tells you exactly which files had
  conflicts and which pack "won" each one, so you can reorder and re-merge if
  the result isn't what you wanted

## Building it yourself

You don't need to build anything to use the tool — just grab the exe from
Releases. But if you want to build locally:

```bash
git clone https://github.com/yourname/LunarPackMerger.git
cd LunarPackMerger
pip install -r requirements.txt
python main.py          # run it directly
# or
build.bat                # build LunarPackMerger.exe with PyInstaller
```

The GitHub Actions workflow (`.github/workflows/build.yml`) does the same
thing automatically on every push to `main` and on every version tag
(`v1.0.0`, etc.), and attaches the exe to a GitHub Release.

## Why it might get flagged by antivirus

PyInstaller-built exes sometimes get falsely flagged by some antivirus
engines because of how they package Python into a single executable — this
is a known, common false positive for small open-source tools like this one,
not something specific to this project. Since the source is fully public and
the exe is built by GitHub itself (not a personal machine), you can verify
exactly what's in it.

## License

MIT — see [LICENSE](LICENSE).
