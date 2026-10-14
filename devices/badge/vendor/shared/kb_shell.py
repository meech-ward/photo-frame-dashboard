"""The keyboard bench: everything about `kbgrid` and `kbqwerty` except the board.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

WHY IT EXISTS AT ALL.  The owner is comparing two KEYBOARDS, and the only way to
do that is for the two apps to be one app.  If the chrome, the field, the caret,
the repeat curve, the softkey labels or the counters differ anywhere, he is
comparing two applications and the exercise is wasted.  So the difference is
confined to exactly one module per app -- `kbgrid_board.py` and
`kbqwerty_board.py` -- and every other file in both trees is generated from a
canonical source and hashed by `scripts/sync_ui.py --check` when a maintainer
runs the production lane by hand.  There is no
`if layout == ...` anywhere below, and there must never be one: a branch here
would reintroduce by hand the difference the whole design is spending files to
prevent.

WHAT A BOARD MODULE OWES THIS ONE.  The seam hands the module in; nothing here
imports it, so neither app can accidentally reach for the other's.

    TITLE       one word for the header, so the two apps are tellable apart
    ROWS        ragged tuple of tuples of cell tokens
    OPENS_AT    (row, column) the caret starts on
    BAR         the three softkey labels -- identical in both apps, and a test
                asserts that rather than trusting it
    UNITS       the board's width in layout units
    LAYOUT      per row, per cell, `(x, w)` in those units
    LABELS      token -> what to draw, for tokens that do not draw as themselves
    label(cell) the same, as a callable
    Model       a `identity_keyboard.GridModel` or a subclass of one

THE LAYOUT TABLE IS THE WHOLE TRICK.  A flush 7-wide grid and a QWERTY board
staggered by half keys are the same drawing problem once cells are `(x, w)` runs
in board units: the view maps units to pixels with integer arithmetic and takes
each cell's right edge from the NEXT cell's left edge, so a row tiles seamlessly
at any offset and neither board gets a code path of its own.

THE HEADER IS A FIXED HEIGHT, and that is not tidiness.  `identity_view` sizes
its board cells as `content_h // (rows + 2)`, which makes the whole screen a
function of the row count -- a 7-row board and a 5-row board would then differ
in their FIELD position, their caret, their counter and their type baseline, and
the owner would be looking at two different apps.  Here the header block is
`2 rows of type + padding` regardless, the board fills what is left and is
bottom-aligned against the softkey bar.  At LORES that reproduces `identity`'s
own grid geometry exactly (cell 11 px, board top 30) while giving QWERTY 15 px
cells, and every pixel above the board is identical in the two apps.

WHAT IS DELIBERATELY NOT HERE.  No store, no `ui.Saver`, no wallpaper, no menu,
no second screen and no file of any kind: the apps write nothing, so B6 has
nothing to debounce and `on_exit` has nothing to flush.  Open the app and a
field is focused; that is the entire product.
"""

import identity_keyboard as keyboard
import ui


# The field's cap is `identity_model.NAME_MAX`, restated rather than imported --
# the bench is for typing a NAME, so a bench with a different cap would be
# measuring a different screen from the one the badge ships.
LIMIT = keyboard.DEFAULT_LIMIT

# Two rows of type in the header: the field's name and its counter, then the
# text and the caret.  A constant, because it is what makes the two apps'
# chrome pixel-identical across different row counts.
HEAD_ROWS = 2

# Left margin and caret width, in logical pixels before the resolution scale.
# `identity_view.TEXT_X` is 6 against a 22 px cell; 3 here because the header
# and the board share a left edge and the board starts at x = 0.
TEXT_X = 3
CARET_W = 2


class KeyboardApp:
    """The controller.  Pure: no clock, no file, no Badgeware global.

    Every entry point takes its input as arguments, which is the property that
    lets `kb/tests` drive the whole app at CPython speed and lets
    `kb/host/kb_press_counts.py` drive the same caret this class drives.
    """

    def __init__(self, board, limit=LIMIT):
        self.board = board
        self.model = board.Model(text="", limit=limit, rows=board.ROWS,
                                 opens_at=board.OPENS_AT)
        # PRESSES, which is the number the whole comparison is about.  It counts
        # caret STEPS plus B presses, so it is the same quantity
        # `kb/host/kb_press_counts.py` reports: a step produced by the auto-
        # repeat ramp costs the wearer no thumb press but does cost a move, and
        # the host counter has no way to tell the two apart either.  Reset by
        # DONE so trial after trial can be run without relaunching.
        self.presses = 0
        self.trials = 0
        # Set for exactly ONE FRAME after DONE: `(text, presses)`.  The seam
        # prints it as the KB_TRIAL marker and nothing is stored, because a
        # marker that persisted would be printed on every subsequent frame and
        # drown the browser trace.
        self.trial = None
        # The same tuple, but KEPT.  Nothing on screen reads it and no file
        # holds it; it exists so a test and the playground's `--exec` can ask
        # what the last trial cost without having to catch the single frame the
        # marker is live for.  One tuple, in RAM, gone at power-off.
        self.last_trial = None
        self.exit = False
        # THE DEVICE-WIDE REPEAT CURVE, from `shared/ui.py`, on UP and DOWN
        # only.  Two `ui.Repeat` instances and no `ui.Axis`, because `Axis`
        # reads `badge.held(...)` inside itself and an editor built on it cannot
        # be stepped off the device at all.  The subtraction is the whole axis.
        self._up = ui.Repeat()
        self._down = ui.Repeat()
        self._up.block()
        self._down.block()
        # M1's drain, applied to a browse screen.  `badge.pressed()` is an edge
        # against the previous poll and the previous poll at boot is empty, so
        # the launcher press that started this app is still live on frame one
        # and would type a letter before the wearer saw the screen.  Held until
        # all three command keys are up.
        self._blocked = True

    # -- input -------------------------------------------------------------

    def _commands(self, buttons):
        """A, B and C as edges, or nothing at all while the boot press is down."""
        if self._blocked:
            if (buttons.held("A") or buttons.held("B")
                    or buttons.held("C")):
                return (False, False, False)
            self._blocked = False
        return (buttons.pressed("A"), buttons.pressed("B"),
                buttons.pressed("C"))

    def frame(self, now_ms, buttons):
        """One frame of input.  Returns nothing; the view reads this object."""
        model = self.model
        self.trial = None
        # UP and DOWN through the ramp; A and C do NOT auto-repeat, which is B4
        # read literally -- the curve is on the scroll keys only.  It matters
        # more on QWERTY than it ever did on the grid: eleven wrapped columns
        # are up to five steps apart where seven were three.  If a hand test
        # says that is tiring, the fix is `ui.Repeat(ui.CHARACTER_REPEAT)` in
        # THIS file, so both apps change together and the comparison stays
        # honest.  It cannot change a press count either way.
        step = self._down.step(buttons.held("DOWN"), now_ms)
        step -= self._up.step(buttons.held("UP"), now_ms)
        if step:
            model.move_row(step)
            self.presses += step if step > 0 else -step
        left, commit, right = self._commands(buttons)
        if left:
            model.move_column(-1)
            self.presses += 1
        if right:
            model.move_column(1)
            self.presses += 1
        if not commit:
            return
        self.presses += 1
        outcome = model.press()
        if outcome == keyboard.COMMITTED:
            # DONE ends a TRIAL, not the app.  The field clears and the counter
            # resets in place, with the caret left where the wearer's thumb
            # left it, so the next string can be typed immediately.  Nothing is
            # written and no screen is pushed -- there is no second screen to
            # push.  This is a judgement call and `kb/README.md` flags it:
            # `identity` commits the name and pops back to its menu, and a
            # bench with no menu has to mean something else by DONE.
            self.trials += 1
            self.trial = self.last_trial = (model.text, self.presses)
            model.text = ""
            self.presses = 0
        elif outcome == keyboard.ABANDONED:
            # I2's labelled route out that commits nothing.  It ends the managed
            # loop and hands control back to `launch()`, which is the launcher
            # -- not `machine.reset()`, which is what HOME does and what makes
            # leaving through HOME indistinguishable from crashing.
            self.exit = True

    def on_exit(self):
        """Real, and called from the HOME IRQ as well as a normal return.

        There is nothing to flush, because there is nothing to save.  It exists
        so the app has the hook every app on this badge owes, and so the marker
        the browser lane reads is printed on both routes out.
        """
        return None


class KeyboardView:
    """All the drawing, and the only place a pixel is named.

    Takes the Badgeware APIs as arguments rather than reading them as globals,
    the way `identity_view` does, so the geometry can be exercised without a
    panel.  `ui.Chrome()` is constructed here and therefore AFTER the seam has
    called `badge.mode(...)`, which rebinds `screen` -- a chrome built before
    the mode call would size itself to the wrong canvas.
    """

    def __init__(self, board, screen_api, image_api, color_api, font_api,
                 rect_api):
        self.board = board
        self.screen = screen_api
        self.image = image_api
        self.rect = rect_api
        self.chrome = ui.Chrome()
        chrome = self.chrome
        scale = chrome.scale
        self.scale = scale
        self.font_size = chrome.font_size

        # `identity_view`'s palette, so the bench looks like the app it is a
        # bench for rather than like a third product.
        self.dark = color_api.rgb(9, 14, 24)
        self.white = color_api.rgb(255, 255, 255)
        self.black = color_api.rgb(0, 0, 0)
        self.accent = color_api.rgb(62, 207, 142)
        self.grey = color_api.rgb(120, 130, 145)
        self.red = color_api.rgb(245, 80, 96)
        self.band = color_api.rgb(0, 0, 0, 210)

        self.pad = scale
        self.text_x = TEXT_X * scale
        self.caret_w = CARET_W * scale
        # One logical pixel of air over and under a row of type, so the gutter
        # keeps its physical size if the panel ever flips resolution.
        self.step = chrome.text_h + 2 * scale
        self.head_h = HEAD_ROWS * self.step + 2 * self.pad
        rows = board.ROWS
        self.cell_h = (chrome.content_h - self.head_h) // len(rows)
        # Bottom-aligned against the bar, so the slack from an inexact division
        # lands between the header and the board instead of under it.
        self.board_y = chrome.content_h - self.cell_h * len(rows)
        self.cells = tuple(self._pixels(row) for row in board.LAYOUT)

    def _pixels(self, row):
        """A row of `(x, w)` unit runs, in pixels, tiled with no seams.

        INTEGER ARITHMETIC THROUGHOUT.  `identity` records the same source
        resolving a softkey centre to 27 on the badge and 28 in the playground
        because a float rounded differently, which cost the browser oracle its
        claim to describe the device.  Rounding here is `(a + b // 2) // b` and
        cannot diverge.

        Each cell's right edge is the NEXT boundary rather than
        `round(w * width / units)`, so rounding error accumulates into cell
        widths of 14 and 15 px rather than into gaps between them.
        """
        width = self.chrome.width
        units = self.board.UNITS
        out = []
        for x, w in row:
            left = (x * width + units // 2) // units
            right = ((x + w) * width + units // 2) // units
            out.append((left, right - left))
        return tuple(out)

    # -- primitives --------------------------------------------------------

    def _text(self, message, x, y, pen=None):
        if pen is not None:
            self.screen.pen = pen
        self.screen.text(message, x, y, font_size=self.font_size)

    def _width(self, message):
        if not message:
            return 0
        return int(self.screen.measure_text(message,
                                            font_size=self.font_size)[0])

    def _cell(self, cell, x, y, cell_w, selected):
        """One key.  Bounded and ELLIPSES, exactly like a softkey label.

        The renderer drops out-of-bounds glyphs SILENTLY -- that is how
        `profile` shipped an editor whose entry point was invisible on the
        physical device -- so a label that outgrew its cell would simply not be
        there.  Bounding it makes the failure visible instead, and
        `kb/tests/test_kb_sameness.py::BoardContractTests::
        test_every_label_fits_its_cell_in_both_apps` measures every label in
        both apps so it never gets that far.
        """
        screen = self.screen
        if selected:
            screen.pen = self.accent
            screen.rectangle(x, y, cell_w, self.cell_h)
        screen.pen = self.black if selected else self.white
        screen.text(self.board.label(cell),
                    self.rect(x, y, cell_w, self.cell_h),
                    font_size=self.font_size,
                    align=(self.image.CENTER, self.image.MIDDLE),
                    overflow=self.image.ELLIPSES)

    # -- the screen --------------------------------------------------------

    def draw(self, app):
        screen = self.screen
        model = app.model
        chrome = self.chrome
        screen.pen = self.dark
        screen.clear()
        screen.font = chrome.font

        self._text(self.board.TITLE, self.text_x, self.pad, self.accent)
        # The counter turns RED when the field is full, and that is the whole
        # of the REFUSED feedback: a full field that silently eats presses is
        # how a name gets truncated without anybody noticing, and a permanent
        # colour beats a timed toast at telling you so (I5 -- a live key's
        # meaning is on screen the WHOLE time, never on a timer).
        counter = "%d/%d" % (len(model.text), model.limit)
        self._text(counter, chrome.width - self.text_x - self._width(counter),
                   self.pad, self.red if model.full() else self.grey)

        y = self.pad + self.step
        typed = model.text
        self._text(typed, self.text_x, y, self.white)
        # A BLOCK caret after the text rather than an underline under it: at one
        # logical pixel an underline is invisible at LORES, and the block also
        # shows the wearer that an empty field is still taking input.
        screen.pen = self.accent
        screen.rectangle(self.text_x + self._width(typed), y, self.caret_w,
                         chrome.text_h)
        presses = "%dP" % app.presses
        self._text(presses, chrome.width - self.text_x - self._width(presses),
                   y, self.grey)

        row, column, _goal = model.caret()
        rows = self.board.ROWS
        for index in range(len(self.cells)):
            line = self.cells[index]
            cells = rows[index]
            y = self.board_y + index * self.cell_h
            for position in range(len(line)):
                x, cell_w = line[position]
                self._cell(cells[position], x, y, cell_w,
                           index == row and position == column)
        # Drawn LAST, because "no content in the band" is unshippable: the
        # board's bottom row is 13 px from the foot of the canvas.
        chrome.bar(self.board.BAR, ink=self.white, panel=self.band)
