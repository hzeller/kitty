#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import re

from kitty.fast_data_types import CTFace as Face, coretext_all_fonts
from kitty.utils import ceil_int, get_logical_dpi, wcwidth

main_font = {}
symbol_map = {}
cell_width = cell_height = baseline = CellTexture = WideCellTexture = underline_thickness = underline_position = None
attr_map = {(False, False): 'font_family', (True, False): 'bold_font', (False, True): 'italic_font', (True, True): 'bold_italic_font'}


def create_font_map(all_fonts):
    ans = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        f = (x['family'] or '').lower()
        s = (x['style'] or '').lower()
        ps = (x['postscript_name'] or '').lower()
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(f + ' ' + s, []).append(x)
    return ans


def find_best_match(font_map, family, bold, italic):
    q = re.sub(r'\s+', ' ', family.lower())

    def matches(candidate, monospace):
        return candidate['bold'] == bold and candidate['italic'] == italic and candidate['monospace'] == monospace

    for monospace in (True, False):
        for selector in 'ps_map full_map family_map'.split():
            candidates = font_map[selector].get(q, ())
            if candidates:
                for candidate in candidates:
                    if matches(candidate, monospace):
                        return candidate
                if selector != 'family_map':
                    return candidates[0]


def get_face(font_map, family, main_family, font_size, dpi, bold=False, italic=False):
    def resolve_family(f):
        if f.lower() == 'monospace':
            f = 'Menlo'
        if (bold or italic) and f == 'auto':
            f = main_family
        return f
    family = resolve_family(family)
    descriptor = find_best_match(font_map, family, bold, italic) or {
        'monospace': True,
        'bold': bold,
        'italic': italic,
        'family': family
    }
    return Face(descriptor, font_size, dpi)


def install_symbol_map(all_fonts, val, font_size, dpi):
    global symbol_map
    symbol_map = {}
    family_map = {f: get_face(all_fonts, f, 'Menlo', font_size, dpi) for f in set(val.values())}
    for ch, family in val.items():
        symbol_map[ch] = family_map[family]


def set_font_family(opts, override_font_size=None, ignore_dpi_failure=False):
    global cell_width, cell_height, baseline, CellTexture, WideCellTexture, underline_thickness, underline_position
    try:
        dpi = get_logical_dpi()
    except Exception:
        if not ignore_dpi_failure:
            raise
        dpi = (72, 72)  # Happens when running via develop() in an ssh session
    dpi = sum(dpi) / 2.0
    font_size = override_font_size or opts.font_size
    all_fonts = create_font_map(coretext_all_fonts())

    for (bold, italic), attr in attr_map.items():
        main_font[(bold, italic)] = get_face(all_fonts, getattr(opts, attr), opts.font_family, font_size, dpi, bold, italic)

    install_symbol_map(all_fonts, opts.symbol_map, font_size, dpi)
    mf = main_font[(False, False)]
    cell_width, cell_height = mf.cell_size()
    CellTexture = ctypes.c_ubyte * (cell_width * cell_height)
    WideCellTexture = ctypes.c_ubyte * (2 * cell_width * cell_height)
    baseline = int(round(mf.ascent))
    underline_position = int(round(baseline - mf.underline_position))
    underline_thickness = ceil_int(mf.underline_thickness)
    return cell_width, cell_height


def test_font_matching(name='Menlo', bold=False, italic=False, dpi=72.0, font_size=11.0):
    all_fonts = create_font_map(coretext_all_fonts())
    face = get_face(all_fonts, name, 'Menlo', font_size, dpi, bold, italic)
    return face


def current_cell():
    return CellTexture, cell_width, cell_height, baseline, underline_thickness, underline_position


def split(buf, cell_width, cell_height):
    first, second = CellTexture(), CellTexture()
    for y in range(cell_height):
        offset, woffset = y * cell_width, y * cell_width * 2
        for x in range(cell_width):
            first[offset + x] = buf[woffset + x]
            second[offset + x] = buf[woffset + cell_width + x]
    return first, second


def render_cell(text=' ', bold=False, italic=False):
    ch = text[0]
    width = wcwidth(ch)
    face = symbol_map.get(ch) or main_font[(bold, italic)]
    if width == 2:
        buf, width = WideCellTexture(), cell_width * 2
    else:
        buf, width = CellTexture(), cell_width
    face.render_char(text, width, cell_height, ctypes.addressof(buf))
    if width == 2:
        first, second = split(buf, cell_width, cell_height)
    else:
        first, second = buf, None
    return first, second


def develop(family='monospace', sz=288):
    import pickle
    from .render import render_string
    from kitty.fast_data_types import glfw_init
    from kitty.config import defaults
    import os
    glfw_init()
    try:
        os.remove('/tmp/cell.data')
    except EnvironmentError:
        pass
    opts = defaults._replace(font_family=family, font_size=sz)
    set_font_family(opts, ignore_dpi_failure=True)
    for (bold, italic), face in main_font.items():
        print('bold: {} italic: {} {}'.format(bold, italic, face))
    print('cell_width: {}, cell_height: {}, baseline: {}'.format(cell_width, cell_height, baseline))
    buf, w, h = render_string()
    open('/tmp/cell.data', 'wb').write(pickle.dumps((bytearray(buf), w, h)))
