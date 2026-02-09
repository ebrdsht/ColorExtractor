import traceback
from pathlib import Path
import sys
# make scripts runnable directly by ensuring project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
log = Path(__file__).parent.parent / 'start_log.txt'
try:
    from src.app import ColorExtractor
    print('imported ColorExtractor')
    a = ColorExtractor()
    print('instantiated')
    a.update()
    print('updated')
    a.destroy()
    print('destroyed')
    log.write_text('OK')
except Exception as e:
    s = traceback.format_exc()
    log.write_text(s)
    print('exception written to start_log.txt')