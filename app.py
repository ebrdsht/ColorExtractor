"""Top-level launcher for ColorExtractor.

Allows starting the app with `python app.py` from the repo root.
"""
from src.app import ColorExtractor

if __name__ == '__main__':
    ColorExtractor().mainloop()
