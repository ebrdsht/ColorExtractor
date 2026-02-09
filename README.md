# ColorExtractor

Small local Tkinter app to generate color palettes from an image.

Features
- Select an image to analyze.
- Choose number of colors to generate, or type `max` to include every unique color.
- Warnings for large number of colors: 51-75 -> confirmation; >75 -> error.
- Generated colors shown as selectable `hex` entries inside colored blocks.
- Toggle enable/disable for colors (disabled colors are greyed out and can be sorted to top).
- Sorting by frequency, hue, saturation, value, luminance, or hex.
- Export palette as a text list or an image of hex codes.
- Image preview with non-destructive markers showing where sampled colors appear.
- Settings persist between runs (`~/.colorextractor_settings.json`). Open the **Settings** button in the top bar to edit thresholds (including `MAX_QUANT_DIM`, which controls the max size used for fixed-count quantization) and click **Reset to defaults** to restore.

How fixed color counts are chosen
When you enter a specific number (for example, `8`), the app uses Pillow's adaptive palette quantization.
It first converts the image to RGBA and ignores fully transparent pixels. If the image is large,
it is resized so the longest edge is at most `MAX_QUANT_DIM` (default 800) to keep processing fast.
Then Pillow's adaptive palette algorithm selects the `n` colors that best represent the image. The
palette is sorted by how frequently each color appears in the sampled data.
Run
1. Create a virtual env (recommended): `python -m venv venv` and activate it.
2. Install dependencies: `pip install -r requirements.txt`.
3. Run: `python src/app.py`.

Debugging
- Enable debug logging to a file by setting the `COLOREXTRACTOR_DEBUG=1` environment variable before launching the app.
- Reset the debug log on startup with `COLOREXTRACTOR_DEBUG_RESET=1`.
- Enable button layout debug checks with `COLOREXTRACTOR_BUTTON_DEBUG=1`.

Requirements
- Python 3.8+
- Uses these PyPI packages (in `requirements.txt`)

License
MIT
