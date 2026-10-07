# Forge Neo Resolution Presets
![Forge Neo Resolution Presets tab](docs/resolution-presets-tab.png)

[日本語版 / Japanese](README_ja.md)

Documentation is available in English and Japanese. The extension UI uses compact English labels and the host WebUI's existing language/theme.

Compact resolution presets for Forge Neo and reForge txt2img and img2img.

## Compatibility

- Forge Neo: verified
- reForge: verified

UI rendering, preset selection, portrait/landscape color switching, and `Copy` have been tested successfully in both environments.

## Features

- Model-family profiles with one-click Width/Height presets.
- The `SDXL` profile covers SDXL/Illustrious-style workflows and includes additional portrait presets.
- The `Krea2` profile includes three square sizes and eight portrait presets, all visible together.
- Load existing named user presets in either generation tab. Edit Profiles and their resolutions in Settings.
- Optional per-generation randomization from the current Profile's built-in presets.
- All built-in presets stay visible in one compact, naturally wrapping flow, followed by `Randomize`, `Reset`, `Undo`, `Copy`, and Profile controls.
- Optional aspect-ratio calculator that preserves the current total pixel area.
- Works independently in txt2img and img2img without recreating Forge Neo's native Width/Height controls.
- No image processing, upscaling, checkpoint inspection, or generation-side processing.

## Krea2 profile

The `Krea2` profile contains 11 presets in the following order. Landscape sizes are available by swapping the native Width/Height controls.

| Display | Width × Height | Aspect ratio / use |
| --- | --- | --- |
| Preset 1 | 1024×1024 | Square, base size |
| Preset 2 | 1536×1536 | Square, intermediate comparison size |
| Preset 3 | 2048×2048 | Square, official Turbo example |
| Preset 4 | 928×1152 | Portrait, approximately 4:5 |
| Preset 5 | 896×1184 | Portrait, approximately 3:4 |
| Preset 6 | 832×1248 | Portrait, 2:3 |
| Preset 7 | 1024×1536 | Portrait, larger 2:3 |
| Preset 8 | 768×1376 | Portrait, approximately 9:16 |
| Preset 9 | 672×1568 | Portrait, rotated cinematic wide format |
| Preset 10 | 864×1152 | Portrait, exact 3:4 |
| Preset 11 | 720×1280 | Portrait, exact 9:16 |

The base portrait candidates follow [Krea2 Harness](https://github.com/ANe5s/ComfyUI-Krea2-Harness#krea2-resolution-selector), rotated where needed. [Krea 2's official Turbo usage example](https://github.com/krea-ai/krea-2#usage) uses 2048×2048; 1536×1536 is an optional intermediate comparison size. This Profile is a practical preset collection, not an official list of training resolutions.

All 11 presets are applied at their exact listed dimensions, including when the host's `Resolution Step` is `64`. The extension does not round preset sizes or change the host's settings. Presets outside the native Width/Height range remain unavailable.

If you have saved edited Profiles in `data/profile_overrides.json`, those Profiles take priority over the built-ins. Add `Krea2` through the Profile Editor using the sizes above to keep your existing configuration.

## Install

Copy this folder into the WebUI's `extensions` directory:

```text
<webui-root>/extensions/Forge-Neo-Resolution-Presets
```

Restart Forge Neo or reForge after installation.

## Settings tab

![Forge Neo Settings - Profile Editor](docs/profile-editor-settings.png)

Open `Settings` → `Extensions` → `Resolution Presets` to edit Profiles and manage extension data. The Settings page does not replace Forge Neo's native Width/Height controls; changes are applied to txt2img/img2img after the saved Profile is reloaded.

### Resolution Step compatibility

Preset selection, portrait/landscape toggling, Reset, Undo, and Randomize preserve the exact preset dimensions. A mismatch with the native slider step does not disable a preset. Randomize uses the same native range limits as the active tab and excludes only unavailable sizes. Profile and user-preset files are not changed.

The host's `Resolution Step` still controls manual slider dragging. Gradio accepts exact preset values independently of that step; the numeric Width/Height fields are the authoritative values. No additional warning panel is shown.

The Advanced Ratio Calculator uses only rounding values compatible with the active Resolution Step and clamps results to the native Width/Height slider range.

### Profile Editor

`profiles.json` contains the read-only built-in Profiles. The editor keeps changes as a browser-side Draft until `Save changes` is clicked.

- `New profile` opens a name editor. `Duplicate profile` copies the selected Profile, while `Delete profile` removes it after confirmation. The last Profile cannot be deleted.
- Edit `Width`/`Height` directly. Values must be integers between 16 and 16384, multiples of 8, and unique within a Profile.
- Drag the ↕ handle to reorder rows. `Alt`+`↑`/`↓` also moves the focused row. All presets appear together in this order and wrap to fit the available width.
- Row `Duplicate`/`Delete` affects a Preset only. Use the Profile toolbar for Profile-level operations.
- `Save changes` validates the Draft, creates an automatic backup, and writes `data/profile_overrides.json`. Use `Reload UI` afterward to apply the saved Profile to txt2img/img2img.
- `Restore built-in profiles` warns before discarding the Draft. An unsaved Draft is also protected by a warning when the UI or page is reloaded.

### Backup / Restore

`Create backup` saves the current Profile configuration in `data/profile_backups/`. Select a backup and click `Restore selected` to restore it; the restored Profile still requires `Reload UI` before it appears in the main tabs.

### Randomize settings

- `Start Randomize ON` controls whether the main-tab `Randomize` mode starts enabled after a UI reload.
- `Include custom presets` allows User presets to participate in per-generation randomization. It is off by default.
- Click `Save Randomize settings`, then reload the UI to apply the initial-state setting.

### Resolution History

The history panel records recent resolution changes with the resolution, Profile, tab, and timestamp. Direct Width/Height edits are recorded when the slider is released; preset, Reset, Undo, and Ratio Apply actions record their final resolution once. `Clear history` removes the local history file (`data/resolution_history.json`).

Existing named user presets are read from `data/user_presets.json`. This file and its existing backups are preserved when updating the extension.

## File locations

Paths are relative to the extension root (`Forge-Neo-Resolution-Presets/`):

- Built-in model profiles and presets: `profiles.json`
- User presets: `data/user_presets.json`

- Last selected Profile per tab: `data/last_profiles.json`
- Legacy user-preset export, if present: `data/user_presets-export.json`
- Existing user-preset backups: `data/backups/`
- Edited profile override: `data/profile_overrides.json`
- Profile backups: `data/profile_backups/`
- Randomize settings: `data/behavior_settings.json`
- Resolution history: `data/resolution_history.json`

## UI behavior

- Clicking a built-in or user preset updates only the active tab's native Width and Height controls.
- A preset matching the current Width/Height is highlighted.
- A portrait preset is highlighted orange on exact match and blue with an outline when the current Width/Height is its landscape rotation; button labels and order stay fixed.
- Clicking the matching built-in preset toggles its orientation: orange switches to the blue landscape rotation, and blue switches back to the portrait value.
- Changing Profile changes the available built-in buttons but does not automatically change the current resolution.
- All built-in presets are always visible in one continuous wrapping row, in Profile order. Profile controls appear after the complete preset row.
- `Randomize` changes to a highlighted state; while enabled, one preset from the current Profile is selected for each generation. User presets are excluded by default; enable `Include custom presets` in the Settings tab to include them. Click `Randomize` again to disable it.
- `Reset` applies `1024x1024` (the first preset in the shipped Profiles). `Undo` restores the resolution before the last preset/reset action. `Copy` copies the current Width×Height text.
- Built-in presets contain square and portrait dimensions only. Use Forge Neo's native Width/Height swap control for landscape orientation.
- `1024x1536`, `960x1280`, `832x1152`, and `768x1280` are general portrait candidates based on mixed-aspect-ratio use; they are not guaranteed to be optimal for every checkpoint.
- The Advanced Ratio Calculator is collapsed by default.

## User presets

Click a named button in the `User` row to load an existing preset into the active tab. Existing `data/user_presets.json` files remain compatible, and saved presets can still participate in Randomize when `Include custom presets` is enabled in Settings.

The generation tabs no longer include the inline `Manage` panel or its save, update, delete, import, merge, and export controls. To add or edit Profile resolutions, use `Settings` → `Extensions` → `Resolution Presets`, then `Save changes` and `Reload UI`. The Profile Editor manages `data/profile_overrides.json`; it does not edit the legacy named-user-preset file.

User presets and the remembered Profile are local files only. They are not uploaded, synchronized with GitHub, or shared with another Forge Neo installation. Keep `data/user_presets.json` and any existing `data/backups/` files to retain your saved presets and backups.

## Advanced Ratio Calculator

The calculator keeps the current total pixel area as the basis, calculates dimensions for the entered aspect ratio, and rounds them to the selected grid. It does not change Width/Height until `Apply` is clicked. It is an optional helper, not model analysis or upscaling. The `Quick` ratio buttons fill common aspect ratios into the calculator with one click.

## License

MIT License. See [LICENSE](LICENSE).
