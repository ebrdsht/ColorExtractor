# ColorExtractor 

A simple, local Tkinter app for extracting color palettes from images.

---

## Quick overview 

- Open an image and generate a representative color palette.
- Choose a fixed number of colors or let the tool generate a compact palette.
- Export palettes as text or an image, add/remove custom colors, and visually see where sampled colors appear in the source image.

---

## Key features 

- **Open Image** — load common image formats and ignore fully transparent pixels.
- **Fixed-count or full scan** — request a specific number of colors or scan the image for unique colors.
- **Sorting options** — sort palette by frequency, hue, saturation, value, luminance, or hex code.
- **Enable / disable colors** — toggle colors on/off (disabled colors are gray and can be sorted to the top).
- **Visual markers** — non-destructive markers show where sampled pixels come from on the image preview.
- **Export** — save the palette as a plain text list or as an image of hex codes.
- **Persistent settings** — settings are saved to `~/.colorextractor_settings.json` and restored on startup.
- **Cross-platform icon** — the app generates an icon for the window and uses it when building the Windows executable.

> Note: Very large color counts or very large images may take additional time to process; the app may ask for confirmation before running very expensive operations.

---

## Quick start (run from source)

1. Create and activate a virtual environment (recommended):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1   # PowerShell on Windows
# or on macOS / Linux
# source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
python src/app.py
```

---

## Settings & debugging

- Settings file: `~/.colorextractor_settings.json`.
- Enable debug logging to a file by setting the environment variable `COLOREXTRACTOR_DEBUG=1` before launching.
- Reset debug log on startup with `COLOREXTRACTOR_DEBUG_RESET=1`.
- Button layout debug checks may be enabled with `COLOREXTRACTOR_BUTTON_DEBUG=1` (mainly helpful for development).

---

## Troubleshooting / FAQ

- The app uses Pillow's adaptive palette for fixed-count generation — large images are resized (controlled by `MAX_QUANT_DIM`) to keep processing responsive.
- If the app is slow or uses a lot of memory for very large images, reduce the requested color count or increase `MAX_QUANT_DIM` carefully in **Settings**.
- If you run into environment or dependency issues, ensure you are using a supported Python version and that `requirements.txt` is installed.

---

## Contributing

Contributions and bug reports are welcome. Please open an issue or create a pull request with clear reproduction steps.

---

## License

This project is licensed under the **MIT License**.
