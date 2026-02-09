"""ColorExtractor - Tkinter app to extract color palettes from an image."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from tkinter import HORIZONTAL, DISABLED, NORMAL, LEFT, RIGHT, END
from PIL import Image, ImageTk, ImageDraw, ImageFont
from src.palette import Palette, rgb_to_hex, hex_to_rgb, relative_luminance
import io
import math
import json
import numpy as np
import time

MAX_WARN = 50
MAX_ERROR = 75

# Default settings and settings file path
DEFAULT_SETTINGS = {
    'MAX_WARN': MAX_WARN,
    'MAX_ERROR': MAX_ERROR,
    'MAX_SAMPLE_DIM': 1200,
    'FULL_SCAN_PIXEL_LIMIT': 6000000,
    'UNIQUE_THRESHOLD': 2048,
    'UNIQUE_RATIO_THRESHOLD': 0.05,
    'MAX_QUANT_DIM': 800,
}
SETTINGS_FILE = Path.home() / '.colorextractor_settings.json'

# Debug controls (off by default; enable via env vars)
DEBUG_ENABLED = os.getenv('COLOREXTRACTOR_DEBUG') == '1'
DEBUG_RESET = os.getenv('COLOREXTRACTOR_DEBUG_RESET') == '1'
DEBUG_LOG_PATH = Path.home() / '.colorextractor_debug.log'

# Enable a focused button-layout debug mode when explicitly requested.
BUTTON_LAYOUT_DEBUG = os.getenv('COLOREXTRACTOR_BUTTON_DEBUG') == '1'

if DEBUG_RESET:
    try:
        if DEBUG_LOG_PATH.exists():
            DEBUG_LOG_PATH.unlink()
    except Exception:
        pass

def _debug_log(message: str):
    if not DEBUG_ENABLED:
        return
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {message}\n')
    except Exception:
        pass

class ColorExtractor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ColorExtractor')
        self.geometry('1000x700')
        # Reset any previously applied minimum size so the window stays freely resizable
        try:
            self.minsize(1, 1)
        except Exception:
            pass
        # runtime-configurable thresholds (defaults mirrored from module-level constants)
        self.max_warn = MAX_WARN
        self.max_error = MAX_ERROR
        # palette instance (needed for settings to apply)
        self.palette = Palette()
        # Keep palette scrollbar usable by enforcing a minimum thumb fraction (e.g. 8% of track)
        # This prevents the thumb from becoming too small to grab when there are many colors.
        self._min_scroll_frac = 0.08
        # Load persisted settings if present (non-fatal)
        try:
            self.load_settings()
        except Exception:
            pass
        # create a small runtime icon and apply it (generate a temporary .ico placeholder and delete it)
        try:
            # draw a 32x32 base icon (Windows prefers small icons)
            ico = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
            draw = ImageDraw.Draw(ico)
            # draw a simple two-tone circle icon
            draw.ellipse((2, 2, 29, 29), fill=(34, 139, 34, 255))
            draw.ellipse((8, 8, 23, 23), fill=(173, 255, 47, 255))
            # keep the PIL icon and an in-memory PhotoImage
            self._icon_pil = ico.copy()
            self._icon_photo = ImageTk.PhotoImage(self._icon_pil)
            try:
                # set the window icon from the in-memory image (works cross-platform in many cases)
                self.iconphoto(False, self._icon_photo)
            except Exception:
                pass
            # create a temporary .ico for platforms (like Windows) that prefer an .ico file
            try:
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ico')
                tmp_path = tmp.name
                tmp.close()
                # save multiple sizes into the .ico for better scaling (up to 32x32)
                ico.save(tmp_path, format='ICO', sizes=[(16,16),(32,32)])
                try:
                    self.iconbitmap(tmp_path)
                except Exception:
                    pass
                # keep the temporary file until program exit so platform can use it reliably,
                # and register cleanup on exit
                try:
                    import atexit
                    self._tmp_icon_path = tmp_path
                    atexit.register(lambda p=tmp_path: os.remove(p) if os.path.exists(p) else None)
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            self._icon_photo = None
        # initialize runtime attributes before building the UI so callbacks and bindings
        # triggered during widget layout see consistent state
        self.img = None
        self.tk_img = None
        self.markers = []  # positions of sample pixels per color
        self.settings_win = None
        # debug: track last log times to avoid spamming the console
        self._button_debug_last_log = {}
        # track original button styles for debug flashing
        self._button_orig_style = {}
        self._button_debug_pending = None
        self._build_ui()

        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.after(100, lambda: (self.lift(), self.focus_force()))
            pass
        except Exception:
            pass

    def _build_ui(self):
        # Use native window decorations and keep the UI simple and robust.
        # Remove custom titlebar and related Win32 manipulations — we will use the OS-provided titlebar and controls.
        try:
            # ensure native decorations are active
            try:
                self.overrideredirect(False)
            except Exception:
                pass
        except Exception:
            pass

        # subtle bottom separator like Win11
        sep = tk.Frame(self, bg='#E6E6E6', height=1)
        sep.pack(fill='x', side='top')
        # debug style for highlighting problematic buttons when BUTTON_LAYOUT_DEBUG is enabled
        # debug style intentionally not applied to avoid visual side-effects (console-only debug)
        try:
            style = ttk.Style(self)
        except Exception:
            pass
        # Use native window move/resize; custom resize grips removed to simplify behavior and avoid platform issues.
        # Main toolbar
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=4)

        # create left and right groups so buttons retain their size when window shrinks
        left_group = ttk.Frame(top)
        left_group.pack(side=LEFT)
        right_group = ttk.Frame(top)
        right_group.pack(side=RIGHT)

        open_btn = ttk.Button(left_group, text='Open Image', command=self.open_image, width=12)
        open_btn.pack(side=LEFT, padx=4, ipady=4)
        self.open_btn = open_btn
        self._button_orig_style['open_btn'] = open_btn.cget('style')

        ttk.Label(left_group, text='Colors:').pack(side=LEFT, padx=(8,4))
        self.count_var = tk.StringVar(value='8')
        self.count_entry = ttk.Entry(left_group, width=8, textvariable=self.count_var)
        self.count_entry.pack(side=LEFT)

        self.generate_btn = ttk.Button(left_group, text='Generate', command=self.generate_palette, state=DISABLED, width=12)
        self.generate_btn.pack(side=LEFT, padx=8, ipady=4)
        self._button_orig_style['generate_btn'] = self.generate_btn.cget('style')

        ttk.Label(left_group, text='Sort:').pack(side=LEFT, padx=(12,4))
        self.sort_var = tk.StringVar(value='frequency')
        self.sort_combo = ttk.Combobox(left_group, textvariable=self.sort_var, state='readonly', values=['frequency','hue','saturation','value','luminance','hex'])
        self.sort_combo.pack(side=LEFT)
        self.sort_combo.bind('<<ComboboxSelected>>', lambda e: self._resort())

        self.disabled_top_var = tk.BooleanVar(value=False)
        self.disabled_check = ttk.Checkbutton(left_group, text='Disabled to top', variable=self.disabled_top_var, command=self._resort)
        self.disabled_check.pack(side=LEFT, padx=8)

        export_text = ttk.Button(right_group, text='Export Text', command=self.export_text, width=12)
        export_text.pack(side=RIGHT, padx=4, ipady=4)
        export_img = ttk.Button(right_group, text='Export Image', command=self.export_image, width=12)
        export_img.pack(side=RIGHT, padx=4, ipady=4)
        self.export_text = export_text
        self.export_img = export_img
        self._button_orig_style['export_text'] = export_text.cget('style')
        self._button_orig_style['export_img'] = export_img.cget('style')

        # lock the left/right group widths to their requested sizes to avoid button shrinking
        try:
            self.update_idletasks()
            lgw = left_group.winfo_reqwidth()
            rgw = right_group.winfo_reqwidth()
            left_group.configure(width=lgw)
            right_group.configure(width=rgw)
            # compute reasonable heights to avoid collapsing children to 1px
            try:
                self.update_idletasks()
                left_h = max(open_btn.winfo_reqheight(), self.generate_btn.winfo_reqheight(), self.count_entry.winfo_reqheight(), self.sort_combo.winfo_reqheight(), self.disabled_check.winfo_reqheight()) + 8
                right_h = max(export_text.winfo_reqheight(), export_img.winfo_reqheight()) + 8
                left_group.configure(height=left_h)
                right_group.configure(height=right_h)
            except Exception:
                pass
            left_group.pack_propagate(True)
            right_group.pack_propagate(True)
            # Do not enforce a window minsize so the user can resize freely. Log a suggestion for debugging.
            try:
                top_req = top.winfo_reqwidth()
                min_w = max(top_req + 16, 400)
                min_h = max(self.winfo_reqheight(), 400)
            except Exception:
                pass
        except Exception:
            pass

        main = ttk.Panedwindow(self, orient='horizontal')
        # reduced padding so the main pane takes more vertical space
        main.pack(fill='both', expand=True, padx=8, pady=2)
        # Keep a reference and guard sash movement so the right pane cannot be collapsed
        try:
            self.main_paned = main
            # Minimum visible width for right-hand pane to keep scrollbar usable
            try:
                MIN_RIGHT_PANE = 160
                # set a firm minimum so the user cannot collapse the pane below a usable width
                self._right_pane_minsize = max(getattr(self, '_right_pane_minsize', 0) or 0, MIN_RIGHT_PANE)
                main.paneconfigure(self.main_paned, minsize=self._right_pane_minsize)
            except Exception:
                pass
            # Use press/release + global motion binding to reliably detect sash dragging across platforms
            main.bind('<ButtonPress-1>', lambda e: self._on_pane_press(e, self.main_paned))
            main.bind('<ButtonRelease-1>', lambda e: self._on_pane_release(e, self.main_paned))
            # periodic enforcement as a fallback for platforms that bypass motion events
            self.after(150, self._periodic_pane_enforce)
        except Exception:
            pass

        # Left: image canvas
        left = ttk.Frame(main)
        main.add(left, weight=3)
        self.canvas = tk.Canvas(left, background='#222', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self._redraw_image())

        # Right: palette list
        right = ttk.Frame(main)
        main.add(right, weight=1)
        # keep a reference to the right pane widget
        try:
            self._right_pane_widget = right
            # Do not force a firm minimum width here; allow layout to condense buttons naturally.
            # The palette rendering will adapt its columns to remain vertically scrollable.
            self._right_pane_minsize = getattr(self, '_right_pane_minsize', None)
        except Exception:
            pass

        ctrl = ttk.Frame(right)
        ctrl.pack(fill='x', pady=4)
        # make palette control buttons wide enough to show their text and lock the control frame
        add_btn = ttk.Button(ctrl, text='Add Color', command=self.add_color, width=14)
        add_btn.pack(side=LEFT, padx=4, ipady=4)
        rem_btn = ttk.Button(ctrl, text='Remove Selected', command=self.remove_selected, width=20)
        rem_btn.pack(side=LEFT, padx=4, ipady=4)
        self.add_btn = add_btn
        self.rem_btn = rem_btn
        self._button_orig_style['add_btn'] = add_btn.cget('style')
        self._button_orig_style['rem_btn'] = rem_btn.cget('style')
        try:
            # compute required width and lock the control frame so buttons don't get truncated
            self.update_idletasks()
            ctrl_req = add_btn.winfo_reqwidth() + rem_btn.winfo_reqwidth() + 12
            ctrl.configure(width=ctrl_req)
            ctrl.pack_propagate(True)

            # schedule a deferred lock that will run after the window is mapped and theme/fonts settle
            def _deferred_lock():
                try:
                    import tkinter.font as tkfont
                    import time
                    self.update_idletasks()
                    # measure left group using font metrics for precision
                    try:
                        try:
                            f_open = self._resolve_widget_font(open_btn)
                            f_generate = self._resolve_widget_font(self.generate_btn)
                            open_w = f_open.measure(open_btn['text']) + 40  # larger safety padding
                            gen_w = f_generate.measure(self.generate_btn['text']) + 40
                        except Exception as e:
                            open_w = open_btn.winfo_reqwidth()
                            gen_w = self.generate_btn.winfo_reqwidth()
                        # include other left-group items spacing
                        other_left = 220  # increased reserve for entries/combo/check
                        lgw_px = open_w + gen_w + other_left
                        left_group.configure(width=lgw_px)
                        try:
                            left_h = max(open_btn.winfo_reqheight(), self.generate_btn.winfo_reqheight(), self.count_entry.winfo_reqheight(), self.sort_combo.winfo_reqheight(), self.disabled_check.winfo_reqheight()) + 8
                            left_group.configure(height=left_h)
                        except Exception:
                            pass
                        left_group.pack_propagate(True)
                    except Exception as e:
                        lgw = left_group.winfo_reqwidth()
                        left_group.configure(width=lgw)
                        left_group.pack_propagate(True)

                    # measure right group (export buttons)
                    try:
                        try:
                            f_export = self._resolve_widget_font(export_text)
                            exp1 = f_export.measure(export_text['text']) + 36
                            f_export2 = self._resolve_widget_font(export_img)
                            exp2 = f_export2.measure(export_img['text']) + 36
                            rgw_px = exp1 + exp2 + 20
                        except Exception as e:
                            rgw_px = export_text.winfo_reqwidth() + export_img.winfo_reqwidth() + 20
                        right_group.configure(width=rgw_px)
                        try:
                            right_h = max(export_text.winfo_reqheight(), export_img.winfo_reqheight()) + 8
                            right_group.configure(height=right_h)
                        except Exception:
                            pass
                        right_group.pack_propagate(True)
                    except Exception as e:
                        rgw = right_group.winfo_reqwidth()
                        right_group.configure(width=rgw)
                        right_group.pack_propagate(True)

                    # recompute ctrl width using font metrics
                    try:
                        try:
                            f_add = self._resolve_widget_font(add_btn)
                            f_rem = self._resolve_widget_font(rem_btn)
                            add_w = f_add.measure(add_btn['text']) + 36
                            rem_w = f_rem.measure(rem_btn['text']) + 36
                            creq = add_w + rem_w + 16
                        except Exception as e:
                            creq = add_btn.winfo_reqwidth() + rem_btn.winfo_reqwidth() + 12
                        ctrl.configure(width=creq)
                        try:
                            ctrl_h = max(add_btn.winfo_reqheight(), rem_btn.winfo_reqheight()) + 8
                            ctrl.configure(height=ctrl_h)
                        except Exception:
                            pass
                        ctrl.pack_propagate(True)
                    except Exception as e:
                        creq = add_btn.winfo_reqwidth() + rem_btn.winfo_reqwidth() + 12
                        ctrl.configure(width=creq)
                        try:
                            ctrl_h = max(add_btn.winfo_reqheight(), rem_btn.winfo_reqheight()) + 8
                            ctrl.configure(height=ctrl_h)
                        except Exception:
                            pass
                        ctrl.pack_propagate(True)

                    # ensure main window minimum width accommodates the control group and toolbar
                    top_req = top.winfo_reqwidth()
                    min_w = max(top_req + 48, creq + 380)
                    min_h = max(self.winfo_reqheight(), 440)

                    # Guard the right-hand palette column from being collapsed too small so
                    # buttons there (Add/Remove) remain usable. Compute a conservative pane min.
                    try:
                        right_min = max(creq + 48, 240)
                        # only set if it meaningfully increases previous value
                        if getattr(self, '_right_pane_minsize', 0) < right_min:
                            try:
                                main.paneconfigure(right, minsize=right_min)
                                self._right_pane_minsize = right_min
                                if BUTTON_LAYOUT_DEBUG:
                                    import time
                                    now = time.time()
                                    last = getattr(self, '_pane_debug_last', 0)
                                    if now - last > 0.5:
                                        _debug_log(f"[PANE_DEBUG] applied right pane minsize: {right_min} total_w={self.winfo_width()}")
                                        self._pane_debug_last = now
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Apply a one-time guarded main-window minsize to avoid trivial truncation while preserving resizability.
                    try:
                        if not getattr(self, '_single_minsize_applied', False):
                            try:
                                self.minsize(min_w, min_h)
                                self._single_minsize_applied = True
                            except Exception:
                                # ignore failures
                                pass
                        else:
                            pass
                    except Exception:
                        pass
                    
                except Exception:
                    pass
            # run shortly and again after a bit to catch late layout changes
            self.after(50, _deferred_lock)
            self.after(500, _deferred_lock)
            self.after(2000, _deferred_lock)
        except Exception:
            pass

        self.palette_frame = ttk.Frame(right)
        self.palette_frame.pack(fill='both', expand=True)
        # scrollable region
        self.canvas_palette = tk.Canvas(self.palette_frame, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.palette_frame, orient='vertical', command=self._on_scrollbar)
        self.scrollable = ttk.Frame(self.canvas_palette)
        self.scrollable.bind("<Configure>", lambda e: self.canvas_palette.configure(scrollregion=self.canvas_palette.bbox("all")))
        # create window and keep a reference so we can resize it when the canvas changes
        self._palette_window = self.canvas_palette.create_window((0,0), window=self.scrollable, anchor='nw')
        # Use a custom yscroll handler to support a minimum thumb size for usability
        self.canvas_palette.configure(yscrollcommand=self._on_canvas_scroll)
        # Layout using grid so the scrollbar stays visible even when the pane is very narrow
        try:
            self.canvas_palette.grid(row=0, column=0, sticky='nsew')
            try:
                self.scrollbar.config(width=18)
            except Exception:
                pass
            self.scrollbar.grid(row=0, column=1, sticky='ns')
            # Ensure palette_frame grid expands correctly
            try:
                self.palette_frame.grid_rowconfigure(0, weight=1)
                self.palette_frame.grid_columnconfigure(0, weight=1)
                self.palette_frame.grid_columnconfigure(1, weight=0)
            except Exception:
                pass
        except Exception:
            # fallback to pack if grid fails for some reason
            try:
                self.canvas_palette.pack(side=LEFT, fill='both', expand=True)
                self.scrollbar.pack(side=RIGHT, fill='y')
            except Exception:
                pass

        # Keep the embedded window sized to the canvas so content doesn't overflow horizontally
        self.canvas_palette.bind('<Configure>', self._on_palette_canvas_configure)

        # Enable mousewheel scrolling when pointer is over the palette area (supports Windows/macOS/Linux)
        self.scrollable.bind('<Enter>', lambda e: self._bind_palette_mousewheel())
        self.scrollable.bind('<Leave>', lambda e: self._unbind_palette_mousewheel())

        # Enable mousewheel scrolling when pointer is over the palette area (supports Windows/macOS/Linux)
        self.scrollable.bind('<Enter>', lambda e: self._bind_palette_mousewheel())
        self.scrollable.bind('<Leave>', lambda e: self._unbind_palette_mousewheel())

        # bottom bar with Settings on the left and status text to the right (keeps placement simple and native)
        bottom = ttk.Frame(self)
        bottom.pack(fill='x')
        settings_btn = ttk.Button(bottom, text='Settings', command=lambda: self.open_settings(), width=10)
        settings_btn.pack(side=LEFT, padx=8, pady=4, ipady=4)
        self.settings_btn = settings_btn
        self._button_orig_style['settings_btn'] = settings_btn.cget('style')
        self.status = ttk.Label(bottom, text='No image loaded')
        self.status.pack(side=LEFT, padx=8, pady=4, fill='x', expand=True)
        # schedule debug checks on general window configure events (throttled via _schedule_button_debug_check)
        try:
            if BUTTON_LAYOUT_DEBUG:
                self.bind('<Configure>', lambda e: self._schedule_button_debug_check())
        except Exception:
            pass

    def open_image(self):
        p = filedialog.askopenfilename(title='Open image', filetypes=[('Images','*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp'),('All files','*.*')])
        if not p:
            return
        try:
            im = Image.open(p).convert('RGBA')
        except Exception as e:
            messagebox.showerror('Error', f'Unable to open image: {e}')
            _debug_log(f'open_image failed: {e}')
            return
        self.img = im
        self.img_path = Path(p)
        self.status.config(text=f'Loaded: {self.img_path.name} ({self.img.width}x{self.img.height})')
        self.generate_btn.config(state=NORMAL)
        _debug_log(f'open_image loaded: {self.img_path} {self.img.width}x{self.img.height}')
        self._redraw_image()

    def _redraw_image(self):
        # defend against early configure events during initialization by checking for the attribute
        if getattr(self, 'img', None) is None:
            try:
                self.canvas.delete('all')
            except Exception:
                pass
            return
        w = self.canvas.winfo_width() or 400
        h = self.canvas.winfo_height() or 300
        # fit image
        img = self.img.copy()
        img.thumbnail((w, h), Image.LANCZOS)
        self.display_scale = img.width / self.img.width
        self.tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(w//2, h//2, image=self.tk_img, anchor='center', tags='img')
        # draw markers
        self._draw_markers()

    # --- Button layout debug helpers -------------------------------------------------
    def _resolve_widget_font(self, widget):
        import tkinter.font as tkfont
        from tkinter import ttk
        s = ttk.Style(self)
        try:
            val = widget.cget('font')
        except Exception:
            val = None
        if val:
            try:
                return tkfont.Font(font=val)
            except Exception:
                pass
        try:
            style = widget.cget('style')
            if style:
                try:
                    fname = s.lookup(style, 'font')
                    if fname:
                        try:
                            return tkfont.Font(font=fname)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
        for name in ('TkButtonFont', 'TkDefaultFont', 'TkTextFont'):
            try:
                return tkfont.nametofont(name)
            except Exception:
                pass
        return tkfont.Font()

    # --- Palette mousewheel helpers -------------------------------------------------
    def _on_palette_mousewheel(self, event):
        try:
            import sys
            # macOS reports raw delta values whereas Windows multiples are usually +/-120
            if sys.platform == 'darwin':
                delta = int(-1 * event.delta)
            else:
                delta = int(-1 * (event.delta // 120))
            self.canvas_palette.yview_scroll(delta, 'units')
        except Exception:
            pass

    def _on_palette_button4(self, event):
        try:
            self.canvas_palette.yview_scroll(-1, 'units')
        except Exception:
            pass

    def _on_palette_button5(self, event):
        try:
            self.canvas_palette.yview_scroll(1, 'units')
        except Exception:
            pass

    def _bind_palette_mousewheel(self):
        try:
            self.canvas_palette.bind_all('<MouseWheel>', self._on_palette_mousewheel)
            self.canvas_palette.bind_all('<Button-4>', self._on_palette_button4)
            self.canvas_palette.bind_all('<Button-5>', self._on_palette_button5)
        except Exception:
            pass

    def _unbind_palette_mousewheel(self):
        try:
            self.canvas_palette.unbind_all('<MouseWheel>')
            self.canvas_palette.unbind_all('<Button-4>')
            self.canvas_palette.unbind_all('<Button-5>')
        except Exception:
            pass

    # --- Custom scrollbar behavior -----------------------------------------------
    def _on_scrollbar(self, *args):
        """Intercept scrollbar commands and map them to canvas yview while
        preserving a minimum visual thumb size for usability."""
        try:
            if not args:
                return
            cmd = args[0]
            # current real view
            a, b = self.canvas_palette.yview()
            real_span = float(b) - float(a)
            if cmd == 'moveto':
                frac = float(args[1])
                # If the real span is large enough, passthrough
                if real_span >= self._min_scroll_frac:
                    self.canvas_palette.yview_moveto(frac)
                    return
                # otherwise map visual position to real content position
                v = max(0.0, min(frac, 1.0 - self._min_scroll_frac))
                denom = (1.0 - self._min_scroll_frac)
                if denom == 0 or (1.0 - real_span) == 0:
                    r = 0.0
                else:
                    r = v * (1.0 - real_span) / denom
                r = max(0.0, min(r, 1.0 - real_span))
                self.canvas_palette.yview_moveto(r)
            elif cmd == 'scroll':
                # scroll N units/pages - pass through to canvas
                n = int(args[1])
                what = args[2]
                self.canvas_palette.yview_scroll(n, what)
        except Exception:
            pass

    def _on_palette_canvas_configure(self, event):
        """Ensure the embedded scrollable frame matches the visible canvas width minus
        the scrollbar thickness and schedule a re-render so tile columns adapt."""
        try:
            # compute usable width for the embedded frame
            try:
                sbw = self.scrollbar.winfo_width() or 18
            except Exception:
                sbw = 18
            new_w = max(32, event.width - sbw)
            try:
                self.canvas_palette.itemconfig(self._palette_window, width=new_w)
            except Exception:
                pass
            # throttle re-render so window resizing doesn't redraw excessively
            try:
                if hasattr(self, '_palette_rerender_after') and self._palette_rerender_after:
                    self.after_cancel(self._palette_rerender_after)
                self._palette_rerender_after = self.after(100, lambda: self._render_palette_list())
            except Exception:
                pass
        except Exception:
            pass

    def _on_canvas_scroll(self, a, b):
        """Custom yscroll handler to present a minimum visual thumb size when
        the real viewport fraction is very small."""
        try:
            a = float(a)
            b = float(b)
            real_span = b - a
            if real_span >= self._min_scroll_frac:
                # show real span
                self.scrollbar.set(a, b)
                return
            # compute visual top based on linear mapping
            denom = (1.0 - real_span)
            if denom == 0:
                a_vis = 0.0
            else:
                a_vis = a * (1.0 - self._min_scroll_frac) / denom
                a_vis = max(0.0, min(a_vis, 1.0 - self._min_scroll_frac))
            self.scrollbar.set(a_vis, a_vis + self._min_scroll_frac)
        except Exception:
            pass

    def _button_layout_debug_check(self):
        """Measure buttons and highlight/log any that are too small for their text (width or height).
        This is intentionally lightweight and throttled to avoid spamming the console.
        When a vertical truncation is detected it will also raise the min-height of the
        owning toplevel (main window or dialog) to prevent further truncation.
        """
        if not BUTTON_LAYOUT_DEBUG:
            return
        try:
            import tkinter.font as tkfont
            import time
            now = time.time()
            checks = [
                ('open_btn', getattr(self, 'open_btn', None)),
                ('generate_btn', getattr(self, 'generate_btn', None)),
                ('export_text', getattr(self, 'export_text', None)),
                ('export_img', getattr(self, 'export_img', None)),
                ('add_btn', getattr(self, 'add_btn', None)),
                ('rem_btn', getattr(self, 'rem_btn', None)),
                ('settings_btn', getattr(self, 'settings_btn', None)),
            ]
            for name, btn in checks:
                try:
                    if btn is None or not getattr(btn, 'winfo_exists', lambda: False)():
                        continue
                    try:
                        f = self._resolve_widget_font(btn)
                    except Exception:
                        f = tkfont.Font()
                    # width requirement (existing behavior)
                    req_w = f.measure(btn['text']) + 18
                    actual_w = btn.winfo_width()
                    truncated_w = actual_w < req_w
                    # height requirement (new): use font linespace as baseline + modest padding
                    try:
                        lines = f.metrics('linespace')
                    except Exception:
                        lines = f.metrics('ascent') + f.metrics('descent')
                    req_h = lines + 12
                    actual_h = btn.winfo_height()
                    truncated_h = actual_h < req_h

                    if truncated_w or truncated_h:
                        last = self._button_debug_last_log.get(name, 0)
                        if now - last > 1.0:
                            self._button_debug_last_log[name] = now
                        # no visual highlights — console-only debug (no style changes or overlays)
                        # Auto-fix: raise owning toplevel minsize (for main window or dialog) when vertical truncation occurs
                        if truncated_h:
                            try:
                                tl = btn.winfo_toplevel()
                                # compute additional height required
                                delta = int(req_h - actual_h) + 12
                            except Exception:
                                pass

                        # No automatic min-width fixes applied; would suggest increasing min-width by delta if needed (not applied).
                except Exception:
                    pass
        except Exception:
            pass

    def _schedule_button_debug_check(self):
        try:
            if getattr(self, '_button_debug_pending', None):
                try:
                    self.after_cancel(self._button_debug_pending)
                except Exception:
                    pass
            self._button_debug_pending = self.after(100, self._button_layout_debug_check)
        except Exception:
            pass

    def _flash_button_border(self, btn, duration: int = 800):
        """Draw a transient red border around a button to make truncation visually obvious.
        Uses an overlay Frame placed in the button's parent and destroyed after `duration` ms.
        """
        try:
            parent = btn.master if hasattr(btn, 'master') else btn.nametowidget(btn.winfo_parent())
            # compute position relative to parent
            self.update_idletasks()
            x = btn.winfo_x()
            y = btn.winfo_y()
            w = btn.winfo_width()
            h = btn.winfo_height()
            if w <= 0 or h <= 0:
                return
            overlay = tk.Frame(parent, highlightbackground='red', highlightthickness=2, bd=0)
            try:
                overlay.place(x=max(0, x-2), y=max(0, y-2), width=w+4, height=h+4)
                self.after(duration, overlay.destroy)
            except Exception:
                try:
                    overlay.destroy()
                except Exception:
                    pass
        except Exception:
            pass

    def generate_palette(self):
        if not self.img:
            return
        val = self.count_var.get().strip()
        if val.lower() == 'max':
            # estimate unique colors from a sampled image to avoid slow full scans
            est_unique, sample_pixels, total_pixels = self.palette.estimate_unique_stats(self.img)
            # extrapolate estimated total unique colors from sample to better trigger thresholds
            if sample_pixels > 0:
                est_total_unique = min(total_pixels, int(est_unique * (total_pixels / sample_pixels)))
            else:
                est_total_unique = est_unique
            if est_total_unique > self.max_error:
                messagebox.showerror('Too many colors', 'There are too many colors to display!')
                _debug_log(f'generate_palette blocked: est_unique={est_total_unique} max_error={self.max_error}')
                return
            if est_total_unique > self.max_warn:
                # custom confirmation dialog with optional "force exact counts"
                proceed, force = self._ask_full_scan_confirmation(est_total_unique)
                if not proceed:
                    return
                try:
                    self._run_from_image_max(force_full_scan=force)
                except ValueError as e:
                    messagebox.showerror('Too many colors', str(e))
                    _debug_log(f'generate_palette full-scan error: {e}')
                    return
            else:
                # safe to build from sampled heuristics
                self.palette.from_image_max(self.img)
        else:
            try:
                n = int(val)
                if n <= 0:
                    raise ValueError()
            except Exception:
                messagebox.showerror('Invalid value', 'Enter a positive integer or `max`')
                return
            # generate via quantization
            self.palette.from_image_quant(self.img, n, max_dim=self.palette.MAX_QUANT_DIM)
        _debug_log(f'generate_palette done: count={len(self.palette.colors)} mode={val}')
        self._pick_markers()
        self._render_palette_list()
        self._redraw_image()

    def _run_from_image_max(self, *, force_full_scan: bool = False):
        # helper to run from_image_max and apply max_unique_error safety cap
        # inform user if we're doing an exact scan
        if force_full_scan:
            messagebox.showinfo('Full scan', 'Performing exact full-resolution color scan. This may take a while.')
        self.palette.from_image_max(self.img, force_full_scan=force_full_scan, max_unique_error=self.max_error)

    def _ask_full_scan_confirmation(self, est_unique: int):
        # modal dialog asking user to confirm large number of colors and optionally force exact counts
        d = tk.Toplevel(self)
        d.title('Many colors')
        d.transient(self)
        d.grab_set()
        ttk.Label(d, text=f'Estimated unique colors: {est_unique}').pack(padx=12, pady=(12,6))
        ttk.Label(d, text='Too many colors may cause lag. Proceed?').pack(padx=12, pady=(0,6))
        force_var = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(d, text='Force exact counts (may be slow)', variable=force_var)
        chk.pack(padx=12, pady=(0,12))
        btn_frame = ttk.Frame(d)
        btn_frame.pack(fill='x', pady=6, padx=8)
        result = {'proceed': False, 'force': False}
        def on_ok():
            result['proceed'] = True
            result['force'] = bool(force_var.get())
            d.destroy()
        def on_cancel():
            d.destroy()
        ttk.Button(btn_frame, text='Cancel', command=on_cancel, width=12).pack(side=LEFT, padx=6, ipady=4)
        ttk.Button(btn_frame, text='Proceed', command=on_ok, width=12).pack(side=RIGHT, padx=6, ipady=4)
        self.wait_window(d)
        return result['proceed'], result['force']

    def open_settings(self):
        # Non-modal settings popout to edit thresholds and behavior
        if self.settings_win and tk.Toplevel.winfo_exists(self.settings_win):
            self.settings_win.lift()
            return
        d = tk.Toplevel(self)
        self.settings_win = d
        d.transient(self)
        d.title('Settings')
        d.geometry('420x320')
        # On Windows, ensure this popout does not appear in taskbar
        try:
            import sys
            if sys.platform == 'win32':
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                hwnd = d.winfo_id()
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_TOOLWINDOW)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass
        # fields
        frame = ttk.Frame(d, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Palette thresholds (for performance & accuracy)').pack(anchor='w')
        # palette values
        vals = [
            ('Max sample dim', 'MAX_SAMPLE_DIM', str(getattr(self.palette, 'MAX_SAMPLE_DIM', 1200))),
            ('Full scan pixel limit', 'FULL_SCAN_PIXEL_LIMIT', str(getattr(self.palette, 'FULL_SCAN_PIXEL_LIMIT', 6000000))),
            ('Unique threshold', 'UNIQUE_THRESHOLD', str(getattr(self.palette, 'UNIQUE_THRESHOLD', 2048))),
            ('Unique ratio threshold', 'UNIQUE_RATIO_THRESHOLD', str(getattr(self.palette, 'UNIQUE_RATIO_THRESHOLD', 0.05))),
            ('Max quant dim', 'MAX_QUANT_DIM', str(getattr(self.palette, 'MAX_QUANT_DIM', 800))),
        ]
        self._settings_vars = {}
        for label, key, val in vals:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=6)
            ttk.Label(row, text=label).pack(side=LEFT)
            v = tk.StringVar(value=val)
            self._settings_vars[key] = v
            ttk.Entry(row, textvariable=v, width=16).pack(side=RIGHT)
        # app warnings
        ttk.Label(frame, text='Warning thresholds (colors)').pack(anchor='w', pady=(8,2))
        warn_row = ttk.Frame(frame)
        warn_row.pack(fill='x', pady=6)
        ttk.Label(warn_row, text='Warn threshold (ask) - current').pack(side=LEFT)
        self._settings_vars['MAX_WARN'] = tk.StringVar(value=str(self.max_warn))
        ttk.Entry(warn_row, textvariable=self._settings_vars['MAX_WARN'], width=8).pack(side=RIGHT)
        err_row = ttk.Frame(frame)
        err_row.pack(fill='x', pady=6)
        ttk.Label(err_row, text='Error threshold (block) - current').pack(side=LEFT)
        self._settings_vars['MAX_ERROR'] = tk.StringVar(value=str(self.max_error))
        ttk.Entry(err_row, textvariable=self._settings_vars['MAX_ERROR'], width=8).pack(side=RIGHT)
        # buttons
        btn_frame = ttk.Frame(d)
        btn_frame.pack(fill='x', pady=8, padx=8)
        def do_save(close=False):
            try:
                # palette settings
                self.palette.MAX_SAMPLE_DIM = int(self._settings_vars['MAX_SAMPLE_DIM'].get())
                self.palette.FULL_SCAN_PIXEL_LIMIT = int(self._settings_vars['FULL_SCAN_PIXEL_LIMIT'].get())
                self.palette.UNIQUE_THRESHOLD = int(self._settings_vars['UNIQUE_THRESHOLD'].get())
                self.palette.UNIQUE_RATIO_THRESHOLD = float(self._settings_vars['UNIQUE_RATIO_THRESHOLD'].get())
                self.palette.MAX_QUANT_DIM = int(self._settings_vars['MAX_QUANT_DIM'].get())
                # app warnings
                self.max_warn = int(self._settings_vars['MAX_WARN'].get())
                self.max_error = int(self._settings_vars['MAX_ERROR'].get())
            except Exception as e:
                messagebox.showerror('Invalid value', f'Invalid input: {e}')
                return
            # persist
            self.save_settings()
            messagebox.showinfo('Saved', 'Settings saved')
            if close:
                d.destroy()
                self.settings_win = None
        def do_reset():
            # reset UI fields to defaults (does not auto-save)
            for key, val in DEFAULT_SETTINGS.items():
                if key in self._settings_vars:
                    self._settings_vars[key].set(str(val))
            # also reset warn/error
            self._settings_vars['MAX_WARN'].set(str(DEFAULT_SETTINGS['MAX_WARN']))
            self._settings_vars['MAX_ERROR'].set(str(DEFAULT_SETTINGS['MAX_ERROR']))
            messagebox.showinfo('Reset', 'Settings reset to defaults. Click Save to persist.')
        ttk.Button(btn_frame, text='Reset to Defaults', command=do_reset, width=18).pack(side=LEFT, padx=6, ipady=4)

        # Restart UI button
        def _on_restart_ui():
            if messagebox.askyesno('Restart UI', 'This will restart the application now. Any unsaved changes will be lost. Continue?'):
                try:
                    # persist settings before restarting
                    try:
                        self.save_settings()
                    except Exception:
                        pass
                    # replace the current process with a fresh one
                    import sys, os
                    python = sys.executable
                    args = [python] + sys.argv
                    os.execv(python, args)
                except Exception as e:
                    messagebox.showerror('Restart failed', f'Restart failed: {e}')
        ttk.Button(btn_frame, text='Restart UI', command=_on_restart_ui, width=16).pack(side=LEFT, padx=6, ipady=4)
        ttk.Button(btn_frame, text='Save', command=lambda: do_save(close=False), width=14).pack(side=RIGHT, padx=6, ipady=4)
        ttk.Button(btn_frame, text='Save & Close', command=lambda: do_save(close=True), width=14).pack(side=RIGHT, ipady=4)
        def on_close():
            d.destroy()
            self.settings_win = None
        d.protocol('WM_DELETE_WINDOW', on_close)

        # Ensure the dialog opens at its requested layout size, but do not enforce a minsize so user can resize freely.
        try:
            d.update_idletasks()
            dw = d.winfo_reqwidth()
            dh = d.winfo_reqheight()
            # size to requested sizes (do not set an enforced minsize)
            cur_w = d.winfo_width()
            cur_h = d.winfo_height()
            new_w = max(cur_w, dw)
            new_h = max(cur_h, dh)
            # center the dialog over the parent window
            try:
                px = self.winfo_rootx()
                py = self.winfo_rooty()
                pw = self.winfo_width()
                ph = self.winfo_height()
                x = px + max(0, (pw - new_w) // 2)
                y = py + max(0, (ph - new_h) // 2)
                d.geometry(f"{new_w}x{new_h}+{x}+{y}")
            except Exception:
                # fallback: at least set the size
                d.geometry(f"{new_w}x{new_h}")
            # apply a one-time minsize for this dialog so it doesn't open smaller than its layout
            try:
                d.minsize(new_w, new_h)
            except Exception:
                pass
        except Exception:
            pass

    def repair_window_chrome(self, destroy_orphans: bool = False):
        """No-op shim retained for backward compatibility with Settings UI.
        Use the Restart UI action to fully restart and recover if necessary.
        """
        return

    def _on_pane_press(self, event, paned):
        """Detect potential sash drag start and begin motion binding."""
        try:
            try:
                sash = paned.sashpos(0)
            except Exception:
                return
            # event.x is relative to the paned widget; allow a small tolerance for clicks around the sash
            if abs(event.x - sash) <= 16:
                self._sash_dragging = True
                try:
                    paned.bind_all('<Motion>', lambda e: self._enforce_pane_mins(paned))
                except Exception:
                    pass
                if BUTTON_LAYOUT_DEBUG:
                    _debug_log(f"[PANE_DEBUG] start drag at x={event.x} sash={sash}")
        except Exception:
            pass

    def _on_pane_release(self, event, paned):
        """End sash drag; unbind global motion handler and force an enforcement check."""
        try:
            if getattr(self, '_sash_dragging', False):
                self._sash_dragging = False
                try:
                    paned.unbind_all('<Motion>')
                except Exception:
                    pass
                # Force an immediate, unthrottled enforcement and verbose debug output
                try:
                    # gather measurements
                    total_w = paned.winfo_width()
                    sash = paned.sashpos(0)
                    right_min = getattr(self, '_right_pane_minsize', None)
                    right_w = total_w - sash
                    if BUTTON_LAYOUT_DEBUG:
                        _debug_log(f"[PANE_DEBUG] end drag: sash={sash} total_w={total_w} right_w={right_w} min={right_min}")
                except Exception:
                    pass
                # force enforcement
                try:
                    self._enforce_pane_mins(paned, force=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _periodic_pane_enforce(self):
        """Periodic fallback that enforces pane minima in case motion events are missed."""
        try:
            if getattr(self, 'main_paned', None):
                self._enforce_pane_mins(self.main_paned)
        except Exception:
            pass
        finally:
            try:
                self.after(150, self._periodic_pane_enforce)
            except Exception:
                pass

    def _enforce_pane_mins(self, paned, force: bool = False):
        """Clamp sash to keep right-hand pane at or above the computed min width.

        If `force` is True, bypass print throttles and compute a fallback minsize if needed.
        """
        try:
            right_min = getattr(self, '_right_pane_minsize', None)
            # fallback compute if not set
            if not right_min:
                try:
                    creq = None
                    if getattr(self, 'add_btn', None) and getattr(self, 'rem_btn', None):
                        creq = self.add_btn.winfo_reqwidth() + self.rem_btn.winfo_reqwidth() + 16
                    inferred = max((creq + 48) if creq else 0, 240)
                    # Respect the previously-set firm minimum if present
                    try:
                        firm = getattr(self, '_right_pane_minsize', None) or 0
                        inferred = max(inferred, firm)
                    except Exception:
                        pass
                    right_min = inferred
                    # record so later checks are consistent
                    self._right_pane_minsize = right_min
                    # ensure the PanedWindow enforces it immediately
                    try:
                        if getattr(self, 'main_paned', None) and getattr(self, '_right_pane_widget', None):
                            try:
                                self.main_paned.paneconfigure(self._right_pane_widget, minsize=self._right_pane_minsize)
                            except Exception:
                                try:
                                    # fallback: configure by index (1 usually right pane)
                                    self.main_paned.paneconfigure(1, minsize=self._right_pane_minsize)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if BUTTON_LAYOUT_DEBUG and force:
                        _debug_log(f"[PANE_DEBUG] inferred right pane minsize: {right_min}")
                except Exception:
                    pass
            if not right_min:
                return
            total_w = paned.winfo_width()
            try:
                sash_pos = paned.sashpos(0)
            except Exception:
                return
            right_w = total_w - sash_pos
            # debug: report sash and widths (throttled unless forced)
            if BUTTON_LAYOUT_DEBUG:
                import time
                now = time.time()
                last = getattr(self, '_pane_debug_last', 0)
                if force or (now - last > 0.3):
                    _debug_log(f"[PANE_DEBUG] sash_pos={sash_pos} total_w={total_w} right_w={right_w} min={right_min}")
                    self._pane_debug_last = now
            if right_w < right_min:
                new_sash = max(0, total_w - right_min)
                if BUTTON_LAYOUT_DEBUG:
                    _debug_log(f"[PANE_DEBUG] clamping sash: new_sash={new_sash} (was {sash_pos})")
                try:
                    paned.sashpos(0, new_sash)
                except Exception:
                    pass
        except Exception:
            pass

    def _pick_markers(self):
        # find at least one pixel coordinate in the original image for each color for highlighting
        # Uses nearest-neighbor mapping on a sampled image to keep performance reasonable.
        self.markers = []
        if not self.img or not self.palette.colors:
            return
        img = self.img.convert('RGBA')
        w, h = img.size
        max_dim = 420
        sample_scale = 1.0
        if max(w, h) > max_dim:
            sample_scale = max_dim / max(w, h)
            sample = img.resize((max(1, int(w * sample_scale)), max(1, int(h * sample_scale))), Image.NEAREST)
        else:
            sample = img
        arr = np.array(sample)
        mask = arr[:, :, 3] > 0
        coords = np.argwhere(mask)
        if coords.size == 0:
            self.markers = [(c['rgb'], None) for c in self.palette.colors]
            return
        pixels = arr[:, :, :3][mask]
        k = len(self.palette.colors)
        pal = np.array([c['rgb'] for c in self.palette.colors], dtype=np.int16)
        mapping = {i: None for i in range(k)}
        remaining = set(mapping.keys())
        chunk = 20000
        total = pixels.shape[0]
        for start in range(0, total, chunk):
            if not remaining:
                break
            end = min(start + chunk, total)
            pix = pixels[start:end].astype(np.int16)
            diffs = pix[:, None, :] - pal[None, :, :]
            dists = np.sum(diffs * diffs, axis=2)
            nearest = np.argmin(dists, axis=1)
            for i, idx in enumerate(nearest):
                idx = int(idx)
                if idx in remaining:
                    y, x = coords[start + i]
                    mapping[idx] = (int(x), int(y))
                    remaining.remove(idx)
                    if not remaining:
                        break
        self.markers = []
        for i, c in enumerate(self.palette.colors):
            pos = mapping.get(i)
            if pos:
                orig_x = int(pos[0] / sample_scale)
                orig_y = int(pos[1] / sample_scale)
                orig_x = max(0, min(orig_x, w - 1))
                orig_y = max(0, min(orig_y, h - 1))
                disp_x = int(orig_x * self.display_scale)
                disp_y = int(orig_y * self.display_scale)
                self.markers.append((c['rgb'], (disp_x, disp_y)))
            else:
                self.markers.append((c['rgb'], None))

    def _draw_markers(self):
        # draws small markers for each color; if selected color, highlight more
        # remove previous marker tags
        self.canvas.delete('marker')
        # draw each marker
        w = self.canvas.winfo_width() or 400
        h = self.canvas.winfo_height() or 300
        # the image is centered; compute its top-left
        if not self.tk_img:
            return
        img_w = self.tk_img.width()
        img_h = self.tk_img.height()
        x0 = (w - img_w)//2
        y0 = (h - img_h)//2
        for i,(rgb,pos) in enumerate(self.markers):
            if not pos:
                continue
            x = x0 + pos[0]
            y = y0 + pos[1]
            color = '#%02X%02X%02X' % rgb
            r = 6
            self.canvas.create_oval(x-r, y-r, x+r, y+r, fill=color, outline='white', width=1, tags='marker')
        # ensure titlebar stays on top when using overrideredirect
        try:
            self.lift()
        except Exception:
            pass

    def _render_palette_list(self):
        # clear
        for child in self.scrollable.winfo_children():
            child.destroy()
        # Determine tile size and adapt number of columns to available canvas width so
        # the layout stays readable and vertical scrolling is used when necessary.
        tile_w = 80
        padding_x = 12  # includes per-tile padx
        try:
            canvas_w = max(1, self.canvas_palette.winfo_width())
        except Exception:
            canvas_w = 600
        # calculate max columns that can fit without horizontal overflow
        max_cols = max(1, canvas_w // (tile_w + padding_x))
        cols = min(max_cols, len(self.palette.colors) or 1)
        # create compact color tiles with overlayed hex and count labels; keep copy-on-click
        for i, c in enumerate(self.palette.colors):
            r = i // cols
            cc = i % cols
            frame = ttk.Frame(self.scrollable)
            frame.grid(row=r, column=cc, padx=6, pady=6, sticky='n')
            enabled = c.get('enabled', True)
            block_color = c['hex'] if enabled else '#888888'
            block = tk.Frame(frame, background=block_color, width=tile_w, height=tile_w, relief='flat')
            block.grid(row=0, column=0)
            block.grid_propagate(False)
            # toggle enabled on single click
            block.bind('<Button-1>', lambda e, idx=i: self._toggle_enabled(idx))
            # zoom to color on double click
            block.bind('<Double-Button-1>', lambda e, rgb=c['rgb']: self._zoom_to_color(rgb))
            # overlay hex label (click to copy)
            fg = 'black' if relative_luminance(c['rgb']) > 0.5 else 'white'
            hex_lbl = tk.Label(block, text=c['hex'], bg=block_color, fg=fg, cursor='hand2')
            hex_lbl.place(relx=0.5, rely=0.5, anchor='center')
            hex_lbl.bind('<Button-1>', lambda e, hexv=c['hex']: self._copy_hex(hexv))
            # overlay count in bottom-right
            cnt_lbl = tk.Label(block, text=str(c.get('count', 0)), bg=block_color, fg=fg)
            cnt_lbl.place(relx=0.95, rely=0.95, anchor='se')
        # keep status updated
        self.status.config(text=f'Palette: {len(self.palette.colors)} colors')

    def _copy_hex(self, hexval: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(hexval)
            self.status.config(text=f'Copied {hexval} to clipboard')
        except Exception:
            messagebox.showinfo('Copied', f'{hexval} copied to clipboard')

    def _toggle_enabled(self, idx):
        self.palette.toggle_enabled(idx)
        self._render_palette_list()

    # Window move/resize helpers
    def _start_move(self, event):
        # On Windows, hand off to the OS so dragging is native (MWNCLBUTTONDOWN HTCAPTION)
        try:
            import sys
            if sys.platform == 'win32':
                import ctypes
                WM_NCLBUTTONDOWN = 0x00A1
                WM_SYSCOMMAND = 0x0112
                SC_MOVE = 0xF010
                HTCAPTION = 2
                hwnd = self.winfo_id()
                ctypes.windll.user32.ReleaseCapture()
                # Try a safe approach: temporarily disable overrideredirect so Windows will perform a proper native move.
                try:
                    # log attempt
                    # native move attempt (no logging)
                    # toggle off and remember so we can reapply later
                    try:
                        self.overrideredirect(False)
                        self._override_toggled_for_move = True
                    except Exception:
                        self._override_toggled_for_move = False
                    # issue native move message
                    try:
                        ctypes.windll.user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MOVE | HTCAPTION, 0)
                    except Exception:
                        try:
                            ctypes.windll.user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                        except Exception:
                            pass
                    # bind release event to reapply our custom chrome and capture final native rect
                    try:
                        def _end_native_move(e):
                            try:
                                if getattr(self, '_override_toggled_for_move', False):
                                    # Query final native window rect and set Tk geometry to keep positions consistent
                                    try:
                                        import ctypes
                                        from ctypes import wintypes
                                        GetWindowRect = ctypes.windll.user32.GetWindowRect
                                        r = wintypes.RECT()
                                        hwnd_local = self.winfo_id()
                                        if GetWindowRect(hwnd_local, ctypes.byref(r)):
                                            left, top, right, bottom = r.left, r.top, r.right, r.bottom
                                            w = right - left
                                            h = bottom - top
                                            try:
                                                self.geometry(f"{w}x{h}+{left}+{top}")
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    try:
                                        self.overrideredirect(True)
                                    except Exception:
                                        pass
                                    try:
                                        if hasattr(self, '_titlebar') and self._titlebar:
                                            self._titlebar.lift()
                                    except Exception:
                                        pass
                                    try:
                                        self.update_idletasks()
                                    except Exception:
                                        pass
                                    try:
                                        # final redraw
                                        self._redraw_image()
                                    except Exception:
                                        pass
                                    self._override_toggled_for_move = False
                            finally:
                                try:
                                    self.unbind('<ButtonRelease-1>')
                                except Exception:
                                    pass
                        # use a one-time bind; ensure it replaces previous helper
                        self.bind('<ButtonRelease-1>', _end_native_move)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        # fallback: record starting positions for manual move
        self._move_start_x = event.x_root
        self._move_start_y = event.y_root
        geo = self.geometry()
        try:
            wh, xy = geo.split('+', 1)
            w, h = wh.split('x')
            x, y = xy.split('+')
            self._win_x = int(x)
            self._win_y = int(y)
            self._win_w = int(w)
            self._win_h = int(h)
        except Exception:
            self._win_x = 0
            self._win_y = 0
            self._win_w = self.winfo_width()
            self._win_h = self.winfo_height()
        # initialize throttled move state
        try:
            self._move_last_target = None
            self._move_pending = False
        except Exception:
            pass

    def _on_move(self, event):
        try:
            dx = event.x_root - self._move_start_x
            dy = event.y_root - self._move_start_y
            nx = int(self._win_x + dx)
            ny = int(self._win_y + dy)
            # coalesce the requested target and schedule a single native move call
            try:
                self._move_last_target = (nx, ny)
                if not getattr(self, '_move_pending', False):
                    self._move_pending = True
                    # schedule at ~60Hz (16ms)
                    self.after(16, self._process_pending_move)
            except Exception:
                # fallback: immediate geometry update
                try:
                    self.geometry(f'+{nx}+{ny}')
                except Exception:
                    pass
        except Exception:
            pass

    def _process_pending_move(self):
        """Perform one coalesced move to the latest requested target. This avoids flooding SetWindowPos and potential UI hangs."""
        try:
            target = getattr(self, '_move_last_target', None)
            # clear the pending target so new events can set it while we're moving
            self._move_last_target = None
            self._move_pending = False
            if not target:
                return
            nx, ny = int(target[0]), int(target[1])
            try:
                import sys
                if sys.platform == 'win32':
                    import ctypes
                    SWP_NOSIZE = 0x0001
                    SWP_NOZORDER = 0x0004
                    HWND_TOP = 0
                    hwnd = self.winfo_id()
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOP, nx, ny, 0, 0, SWP_NOSIZE | SWP_NOZORDER)
                    return
            except Exception:
                # SetWindowPos failed; fall back to geometry without logging
                try:
                    self.geometry(f'+{nx}+{ny}')
                except Exception:
                    pass
        except Exception:
            pass

    def _toggle_maximize(self):
        if getattr(self, '_is_maximized', False):
            try:
                self.state('normal')
                if hasattr(self, '_normal_geometry'):
                    self.geometry(self._normal_geometry)
            except Exception:
                pass
            self._is_maximized = False
        else:
            try:
                self._normal_geometry = self.geometry()
                self.state('zoomed')
            except Exception:
                pass
            self._is_maximized = True

    def _minimize_window(self):
        try:
            self.iconify()
        except Exception:
            pass

    def _close_window(self):
        try:
            self.destroy()
        except Exception:
            pass


    def _start_resize(self, event, edge):
        # Prefer native OS resizing on Windows via WM_NCLBUTTONDOWN
        try:
            import sys
            if sys.platform == 'win32':
                import ctypes
                WM_NCLBUTTONDOWN = 0x00A1
                HT = {
                    'left': 10, 'right': 11, 'top': 12, 'bottom': 15,
                    'nw': 13, 'ne': 14, 'sw': 16, 'se': 17
                }
                ht = HT.get(edge, 11)
                hwnd = self.winfo_id()
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, ht, 0)
                return
        except Exception:
            pass
        # fallback to manual resize tracking
        self._resize_edge = edge
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        geo = self.geometry()
        try:
            wh, xy = geo.split('+', 1)
            w, h = wh.split('x')
            x, y = xy.split('+')
            self._res_x = int(x)
            self._res_y = int(y)
            self._res_w = int(w)
            self._res_h = int(h)
        except Exception:
            self._res_x = self.winfo_x()
            self._res_y = self.winfo_y()
            self._res_w = self.winfo_width()
            self._res_h = self.winfo_height()

    def _do_resize(self, event, edge):
        min_w, min_h = 300, 240
        try:
            dx = event.x_root - self._resize_start_x
            dy = event.y_root - self._resize_start_y
            nw = self._res_w
            nh = self._res_h
            nx = self._res_x
            ny = self._res_y
            if edge == 'right':
                nw = max(min_w, self._res_w + dx)
            elif edge == 'bottom':
                nh = max(min_h, self._res_h + dy)
            elif edge == 'se':
                nw = max(min_w, self._res_w + dx)
                nh = max(min_h, self._res_h + dy)
            elif edge == 'left':
                nw = max(min_w, self._res_w - dx)
                nx = self._res_x + dx
            elif edge == 'top':
                nh = max(min_h, self._res_h - dy)
                ny = self._res_y + dy
            elif edge == 'nw':
                nw = max(min_w, self._res_w - dx)
                nx = self._res_x + dx
                nh = max(min_h, self._res_h - dy)
                ny = self._res_y + dy
            elif edge == 'ne':
                nw = max(min_w, self._res_w + dx)
                nh = max(min_h, self._res_h - dy)
                ny = self._res_y + dy
            elif edge == 'sw':
                nw = max(min_w, self._res_w - dx)
                nx = self._res_x + dx
                nh = max(min_h, self._res_h + dy)
            self.geometry(f'{nw}x{nh}+{nx}+{ny}')
        except Exception:
            pass

    def _zoom_to_color(self, rgb):
        # find marker and draw a highlight
        # For now, center the canvas on that pixel if marker exists
        for r,pos in self.markers:
            if r == rgb and pos:
                # ensure visibility by scrolling? For now, draw an outline at that marker
                self.canvas.delete('highlight')
                w = self.canvas.winfo_width() or 400
                h = self.canvas.winfo_height() or 300
                img_w = self.tk_img.width()
                img_h = self.tk_img.height()
                x0 = (w - img_w)//2
                y0 = (h - img_h)//2
                x = x0 + pos[0]
                y = y0 + pos[1]
                r = 16
                self.canvas.create_oval(x-r, y-r, x+r, y+r, outline='yellow', width=3, tags='highlight')
                return
        messagebox.showinfo('Not found', 'No visible sample point found for this color')

    def _resort(self):
        mode = self.sort_var.get() or 'frequency'
        self.palette.sort(mode=mode, disabled_to_top=self.disabled_top_var.get())
        self._render_palette_list()

    def add_color(self):
        c = colorchooser.askcolor()
        if not c or not c[0]:
            return
        rgb = tuple(int(v) for v in c[0])
        self.palette.add_color(rgb)
        self._render_palette_list()

    def remove_selected(self):
        # remove disabled ones or last selected? For simplicity, remove disabled entries
        to_remove = [i for i,c in enumerate(self.palette.colors) if not c.get('enabled', True)]
        if not to_remove:
            messagebox.showinfo('Info', 'No disabled colors to remove. Click a block to toggle disabled state first.')
            return
        for idx in reversed(to_remove):
            self.palette.remove_color(idx)
        self._render_palette_list()

    def export_text(self):
        if not self.palette.colors:
            messagebox.showinfo('Info', 'No colors to export')
            return
        p = filedialog.asksaveasfilename(title='Save colors as text', defaultextension='.txt', filetypes=[('Text','*.txt')])
        if not p:
            return
        hex_list = self.palette.hex_list(enabled_only=True)
        lines = '\n'.join(hex_list)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(lines)
        messagebox.showinfo('Saved', f'Saved {len(hex_list)} colors to {p}')
        _debug_log(f'export_text saved: {p}')

    def export_image(self):
        if not self.palette.colors:
            messagebox.showinfo('Info', 'No colors to export')
            return
        p = filedialog.asksaveasfilename(title='Save colors as image', defaultextension='.png', filetypes=[('PNG','*.png')])
        if not p:
            return
        # create image: blocks of 100x100 with hex labels
        cols = 6
        rows = math.ceil(len(self.palette.colors)/cols)
        w = cols*200
        h = rows*120
        out = Image.new('RGBA',(w,h),(255,255,255,255))
        draw = ImageDraw.Draw(out)
        try:
            font = ImageFont.truetype('arial.ttf', 18)
        except Exception:
            font = ImageFont.load_default()
        for i,c in enumerate(self.palette.colors):
            col = c['hex']
            r = i//cols
            cc = i%cols
            x = cc*200 + 10
            y = r*120 + 10
            draw.rectangle([x,y,x+180,y+90], fill=col)
            draw.text((x+6,y+6), c['hex'], fill='black' if relative_luminance(c['rgb']) > 0.5 else 'white', font=font)
        out.save(p)
        messagebox.showinfo('Saved', f'Palette image saved to {p}')
        _debug_log(f'export_image saved: {p}')

    def load_settings(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            _debug_log(f'load_settings failed: {e}')
            return
        try:
            if 'MAX_SAMPLE_DIM' in data:
                self.palette.MAX_SAMPLE_DIM = int(data['MAX_SAMPLE_DIM'])
            if 'FULL_SCAN_PIXEL_LIMIT' in data:
                self.palette.FULL_SCAN_PIXEL_LIMIT = int(data['FULL_SCAN_PIXEL_LIMIT'])
            if 'UNIQUE_THRESHOLD' in data:
                self.palette.UNIQUE_THRESHOLD = int(data['UNIQUE_THRESHOLD'])
            if 'UNIQUE_RATIO_THRESHOLD' in data:
                self.palette.UNIQUE_RATIO_THRESHOLD = float(data['UNIQUE_RATIO_THRESHOLD'])
            if 'MAX_QUANT_DIM' in data:
                self.palette.MAX_QUANT_DIM = int(data['MAX_QUANT_DIM'])
            if 'MAX_WARN' in data:
                self.max_warn = int(data['MAX_WARN'])
            if 'MAX_ERROR' in data:
                self.max_error = int(data['MAX_ERROR'])
            _debug_log('load_settings applied')
        except Exception as e:
            _debug_log(f'load_settings apply failed: {e}')

    def save_settings(self):
        data = {
            'MAX_WARN': int(self.max_warn),
            'MAX_ERROR': int(self.max_error),
            'MAX_SAMPLE_DIM': int(getattr(self.palette, 'MAX_SAMPLE_DIM', DEFAULT_SETTINGS['MAX_SAMPLE_DIM'])),
            'FULL_SCAN_PIXEL_LIMIT': int(getattr(self.palette, 'FULL_SCAN_PIXEL_LIMIT', DEFAULT_SETTINGS['FULL_SCAN_PIXEL_LIMIT'])),
            'UNIQUE_THRESHOLD': int(getattr(self.palette, 'UNIQUE_THRESHOLD', DEFAULT_SETTINGS['UNIQUE_THRESHOLD'])),
            'UNIQUE_RATIO_THRESHOLD': float(getattr(self.palette, 'UNIQUE_RATIO_THRESHOLD', DEFAULT_SETTINGS['UNIQUE_RATIO_THRESHOLD'])),
            'MAX_QUANT_DIM': int(getattr(self.palette, 'MAX_QUANT_DIM', DEFAULT_SETTINGS['MAX_QUANT_DIM'])),
        }
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            _debug_log('save_settings done')
        except Exception as e:
            _debug_log(f'save_settings failed: {e}')

if __name__ == '__main__':
    _debug_log('ColorExtractor: starting')
    app = ColorExtractor()
    _debug_log('ColorExtractor: created app, entering mainloop')
    app.mainloop()
    _debug_log('ColorExtractor: mainloop exited')
