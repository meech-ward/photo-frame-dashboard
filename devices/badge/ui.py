"""Badge interaction standard: softkey bar, scroll keys, repeat, bounded saves.

THIS FILE IS THE CANONICAL COPY.  EDIT IT HERE AND NOWHERE ELSE.

Each app installs to its own directory and only that directory goes on
`sys.path`, so the device HAS NO SHARED LIBRARY LOCATION - there is no
/system/lib, and `pg_runtime` inserts exactly one path.  An app could import
from another app's directory (the pattern glyph2x uses for glyph's player), but
that makes one app refuse to start unless another is installed, which is a bad
trade for a badge whose HOME key can launch anything in any order.

So vendoring is FORCED, not preferred - and the answer is to make the copies
generated rather than merely watched:

    python3 scripts/sync_ui.py            # refresh every vendored copy
    python3 scripts/sync_ui.py --check    # fail if any has drifted

The copies are byte-identical to this file, which is why they carry this notice
too: if you are reading it in an app directory, your edit belongs in
`shared/ui.py` and will be overwritten here.

The five buttons are not five equivalent inputs. Physically they are a
directional pair split across two bezels plus a centre action key:

    A (bottom left)  B (bottom centre)  C (bottom right)
                                        UP   (right bezel, upper)
                                        DOWN (right bezel, lower)

So A/C are the horizontal axis, UP/DOWN the vertical axis, B the action.
Everything here derives from measured physical geometry: the on-screen label
for a button is drawn directly above (or beside) the button it names, because
that spatial correspondence is the whole reason a softkey bar works.

Measured on the physical unit (screen 60x45 mm, buttons 5 mm square, so one
logical pixel is exactly 0.375 mm). Positions are stored as FRACTIONS of the
screen so the layout survives a LORES/HIRES flip, per docs/design/constraints.md.
"""

import time


# Physical button centres, as a fraction of screen width / height.
# A 8mm, B 25mm, C 45mm from the screen's left edge (+2.5mm to centre) / 60mm.
SOFTKEY_FX = (0.175, 0.45833, 0.79167)
# UP 10mm, DOWN 30mm from the screen's top edge (+2.5mm to centre) / 45mm.
SCROLL_FY = (0.27778, 0.72222)

# Auto-repeat. Physical buttons have no OS key repeat, so we build it:
# a deliberate first delay so a single tap is never mistaken for a hold,
# then an accelerating ramp so a long list is a single sweep.
#
# 20 items/s is the terminal cap because that is the overshoot break-even:
# simple visual reaction time is 200-250 ms, so overshoot = rate x 0.25 s.
# At 20/s that is 5 items — one corrective tap burst. Faster buys distance you
# immediately pay back in corrections.
#
# All four are MILLISECONDS and are compared against `time.ticks_ms()`. Do not
# drive these from `badge.ticks`: on hardware a tap ran the ramp to saturation
# and advanced ~10 items per press, which is what a unit mismatch looks like.
REPEAT_DELAY_MS = 350
REPEAT_SLOW_MS = 150
REPEAT_FAST_MS = 50
REPEAT_RAMP_MS = 1200

# Picking a letter is not the same act as skimming a list: there are only 41
# characters, every one is a decision, and overshooting costs a correction.
# Slower to start, and a much lower terminal rate.
CHARACTER_REPEAT = (400, 220, 90, 1500)

# Dragging a sticker wants to reach full speed almost immediately: the canvas
# is only 160 px wide, so a 1.2 s ramp means you never actually get there. Short
# delay, short ramp, high terminal rate — combined with the step scaling below
# it crosses the whole canvas in about half a second while a tap stays deliberate.
PLACE_REPEAT = (250, 60, 20, 400)
# Placement step, in logical pixels. A tap moves PLACE_MIN_STEP and a sustained
# hold reaches PLACE_MAX_STEP. The floor is 6 rather than 1 on the owner's
# hands-on verdict: single-pixel nudges read as the app loading rather than as
# precision. Overshoot is cheap here because the sticker can simply be moved
# again, which is not true of a list selection.
PLACE_MIN_STEP = 6
PLACE_MAX_STEP = 16

# Flash saves stall up to 185 ms (measured). Never write inside a scrub, but
# never defer indefinitely either.
#
# THERE IS AN EXIT CALLBACK, AND THIS COMMENT USED TO DENY IT.  `launch()` in
# the firmware registers HOME as an IRQ whose handler calls the app module's
# `on_exit` and then resets, and it calls `on_exit` again on a normal return, so
# an app does get told it is being closed.  `pet` and `glyph_review` both flush
# from there today.  What has not changed is the CONCLUSION: an unbounded
# debounce still loses data, because `on_exit` is a backstop and not a
# guarantee.
#
#   - The crash path never calls it.  An exception inside the frame loop reaches
#     `fatal_error()`, which draws its modal and calls `machine.reset()` without
#     going near `on_exit`.
#   - When it does run it is microseconds ahead of `machine.reset()`, so a save
#     that stalls at the 185 ms tail is racing the reset that is already queued
#     behind it.
#   - It runs in IRQ context, where the app is mid-frame and may itself be
#     part-way through the very write `on_exit` is about to start.
#
# So: flush from `on_exit` as well, never instead.  The ceiling below is what
# actually keeps the data.
SAVE_DEBOUNCE_MS = 400
SAVE_MAX_DEFER_MS = 1000

# A softkey label is centred on its button, and the real constraint is not the
# zone boundary — it is the gap to the NEXT LABEL'S INK. Centres are 45 px apart
# (A to B), so two 44 px labels leave a 1 px gutter and read as one phrase. A
# uniform 34 px cap keeps at least 11 px (4.1 mm) of clear space between any two
# labels and satisfies both pairwise constraints with one assertion.
#
# font.sins advances 6 px per uppercase glyph (5 for I/T, 7 for M/W, 3 for
# space) — read from the renderer's own rule, advance = (glyph.width + 1).
# So 5 characters is the authoring rule; 6 requires measuring. SELECT (35),
# DELETE (35) and SHUFFLE (42) do not fit. USE, DEL and MIX do.
#
# The BOX is a physical quantity (34 x 0.375 = 12.75 mm) and survives the
# resolution flip as LABEL_MAX_PX * scale — 68 px at HIRES, the same 12.75 mm.
# The AUTHORING RULE does not survive it: that is a fact about one bitmap face.
#
# Both were re-derived by MEASURING INK rather than assuming advances: every
# label triple the app draws, rendered into a real bar and scanned per column.
# Worst inter-label gap, always BACK/APPLY/JUMP:
#
#   LORES sins@1          20 px = 7.50 mm
#   HIRES salty@1 (was)   52 px = 9.75 mm
#   HIRES MonaSans@17     46 px = 8.63 mm   <- 15% MORE clear space than LORES
#
# At HIRES the average uppercase advance is 10.4 px against a 68 px box, so SIX
# characters is the authoring rule and seven needs measuring: SELECT (57),
# DELETE (57) and REMOVE (65) all fit where LORES caps at five, and SHUFFLE (68)
# is the first that does not. The widest label the app actually draws is SPACE
# at 51 px, 75% of the box, so the ellipsis never fires at either resolution.
LABEL_MAX_PX = 34

# Ruler-measured panel, in millimetres (docs/engineering-findings.md). Anything
# that must keep its PHYSICAL size across a resolution flip derives from this
# rather than from a pixel literal.
PANEL_MM = (60.0, 45.0)

# The softkey bar is a band under three physical buttons, so its height is a
# millimetre quantity, not a typographic one. 4.875 mm is what the shipping
# LORES bar already is (13 logical px), and the formula reproduces that value
# exactly. Sizing it from the font instead would give HIRES a 3.4 mm bar —
# thinner than the 5 mm buttons it labels — and would tie a physical affordance
# to whichever face the chrome happens to use.
BAR_MM = 4.875

# HIRES typography. The badge ships three VECTOR faces on its /system partition
# (MonaSans-Medium, DynaPuff-Medium, IndieFlower-Regular) which render from real
# outlines at an arbitrary point size, so HIRES does not have to pick between
# "half the millimetres" and "a physically taller bitmap face". 17 pt gives an
# 11 px cap = 2.06 mm = 17.7 arcmin at 400 mm: 21% physically SMALLER than the
# LORES bitmap type and still above the 15 arcmin bar this project uses. This is the
# one dial. 20 pt (13 px, 20.9 arcmin) is the retreat if hands-on says 17 is too
# small; do not go below 15, which lands where the old HIRES face already sat.
CHROME_FACE = "MonaSans-Medium"
CHROME_PT = 17

# The nickname is read by a STRANGER at about a metre, not by the wearer at
# 400 mm, so it is the one thing that must not get smaller. Auto-fit inside
# these bounds against the width budget: short names get bigger than any pixel
# font could draw them, and a 12-character worst case scales down instead of
# running off the canvas the way LORES does. Pixel fonts take integer scales
# only, so this is something LORES simply cannot do.
DISPLAY_PT = (26, 48)


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


# ONE OUTLINE FACE PER NAME, FOR THE INTERPRETER'S LIFE.  See `_load_vector`.
#
# WHY A DICT AND NOT A SINGLE SLOT: the memo is keyed on the argument because
# that is the only key that cannot be wrong.  It can hold at most as many
# entries as there are distinct names asked for, and this repository asks for
# exactly one, `CHROME_FACE` -- the module has a single `_load_vector` call
# site.  `test_ui_face_memo.CallSiteTests` pins that, so an unbounded dict of
# 74 KB objects stays a one-entry dict in fact as well as in intent.
_FACES = {}


def _load_vector(name):
    """The named .af outline face, or None if this unit does not carry it.

    The vector faces are NOT on ROM: `font.<name>` only ever opens
    /rom/fonts/<name>.ppf, and these live on the FAT /system partition that
    ships inside the firmware image. `font.load` finds them because the native
    resolver walks {/rom/fonts, /system/assets/fonts, /fonts, /assets, ""}, so
    the bare short name is the correct address and no path is hardcoded here.

    Missing raises OSError('Font "X" not found!'), which is a survivable
    condition rather than a crash: a badge whose /system was rebuilt without
    them still boots, on the bitmap fallback.

    MEMOISED 2026-08-23, AND THE MEMO IS NOW THE POINT OF THIS FUNCTION.
    `font.load` is ~66 KB of flash read for a fresh 74 KB object and the native
    side caches NOTHING: measured on the reference badge, four calls returned
    four distinct objects at 111.27 / 111.41 / 111.68 / 111.30 ms with 73,728 B
    retained every time. `ui.Chrome()` at HIRES is 112.1 ms of which 111.3 is
    this one call, and `setup` builds `Chrome` TWICE -- once in its entry
    seam and once in `kb_shell.KeyboardView` -- so opening the keyboard to edit
    a name paid a SECOND 111 ms stall and a second 73.7 KB (`VAL-020-CH`).

    SHARING IS SAFE because the object is read-only in the way that matters:
    one `Chrome` already uses this same face at two point sizes (`font_size`
    and `display_size` are Chrome's, not the face's), so a second consumer is
    not a new kind of consumer.

    WHAT THE RETENTION ACTUALLY COSTS, which was the open product question:
    approximately nothing. Every `Chrome` in this repository is stored on a
    module global or a long-lived view attribute and none is ever dropped, so
    the face was already retained for the app's life before the memo. What the
    memo removes is the second, PEAK allocation -- and at HIRES that peak lands
    on top of a 307,200 B backdrop and a 953 KB mark sheet.

    A MISSING FACE IS MEMOISED TOO, as None. The /system partition does not
    change under a running app, so a second probe would read the same absence,
    fail the same way and print the same line; caching it means a badge without
    the faces pays the failure once instead of once per `Chrome`.

    ONE CONSEQUENCE FOR TEST HARNESSES, and it cost seven red tests to find.
    This is MODULE state, so it outlives whatever a harness thinks of as a boot:
    a suite that simulates a badge with no `.af` files caches a `None` that every
    later test in the same process then reads. A harness whose job is a fresh app
    boot must clear it -- `settings/tests/view_harness.install()` is the worked
    example, one line beside the builtins it hoists.
    """
    if name in _FACES:
        return _FACES[name]
    try:
        face = font.load(name)
    except OSError as err:
        print("NAMEBADGE_FONT vector={} missing={}".format(name, err))
        face = None
    _FACES[name] = face
    return face


class Repeat:
    """Hold-to-repeat with an accelerating ramp, for one logical direction.

    Fed the current held state each frame; yields the number of steps to apply.
    Timing comes from `time.ticks_ms()` supplied by the caller — never from
    `badge.ticks`, whose unit is not worth assuming for something this
    sensitive.
    """

    def __init__(self, tuning=None):
        self.delay, self.slow, self.fast, self.ramp = tuning or (
            REPEAT_DELAY_MS,
            REPEAT_SLOW_MS,
            REPEAT_FAST_MS,
            REPEAT_RAMP_MS,
        )
        self.since = 0
        self.next_at = 0
        self.active = False
        self.blocked = False
        # 0.0 on the initial tap, rising to 1.0 once the ramp is saturated.
        # Callers use it to scale a step: a tap uses the caller's minimum,
        # while a sustained hold sweeps toward its maximum.
        self.progress = 0.0

    def block(self):
        """Ignore this button until it is released and pressed again.

        Without this, the same press that opens a screen immediately acts on
        it — press UP on the badge and you land in the menu already scrolled
        one item down.
        """
        self.blocked = True
        self.active = False

    def step(self, is_held, now):
        if self.blocked:
            if is_held:
                return 0
            self.blocked = False
        if not is_held:
            self.active = False
            self.progress = 0.0
            return 0
        if not self.active:
            # Edge: fire once immediately, then wait out the initial delay.
            self.active = True
            self.since = now
            self.next_at = time.ticks_add(now, self.delay)
            self.progress = 0.0
            return 1
        if time.ticks_diff(now, self.next_at) < 0:
            return 0
        elapsed = time.ticks_diff(now, self.since) - self.delay
        if elapsed < 0:
            elapsed = 0
        ramp = elapsed / self.ramp
        if ramp > 1.0:
            ramp = 1.0
        # Ease-out so the acceleration is felt early and then settles.
        eased = 1.0 - (1.0 - ramp) * (1.0 - ramp)
        self.progress = eased
        interval = self.slow + (self.fast - self.slow) * eased
        self.next_at = time.ticks_add(now, int(interval))
        return 1


class Axis:
    """A pair of Repeats driving one axis.

    Positive is down and right, matching the physical layout: DOWN sits below
    UP on the right bezel, C sits right of A along the bottom.
    """

    def __init__(self, minus_button, plus_button, tuning=None):
        self.minus_button = minus_button
        self.plus_button = plus_button
        self.minus = Repeat(tuning)
        self.plus = Repeat(tuning)
        self.suppress()

    def suppress(self):
        """Swallow whatever is currently held; call on entering a screen."""
        self.minus.block()
        self.plus.block()

    def delta(self, now):
        down = self.minus.step(badge.held(self.minus_button), now)
        up = self.plus.step(badge.held(self.plus_button), now)
        return up - down

    def speed(self):
        """How far into the acceleration ramp this axis is, 0.0 to 1.0."""
        return self.minus.progress if self.minus.active else self.plus.progress


class Saver:
    """Debounced, bounded persistence. Update the screen first, write later."""

    def __init__(self, write):
        self._write = write
        self._dirty_since = 0
        self._touched_at = 0
        self._dirty = False

    def touch(self, now):
        if not self._dirty:
            self._dirty = True
            self._dirty_since = now
        self._touched_at = now

    def poll(self, now):
        """Call once per frame. Returns True if a write happened this frame."""
        if not self._dirty:
            return False
        quiet = time.ticks_diff(now, self._touched_at) >= SAVE_DEBOUNCE_MS
        overdue = time.ticks_diff(now, self._dirty_since) >= SAVE_MAX_DEFER_MS
        if not (quiet or overdue):
            return False
        self._dirty = False
        self._write()
        return True

    def flush(self):
        if self._dirty:
            self._dirty = False
            self._write()


class Chrome:
    """Screen furniture: the softkey bar and the scroll-key affordances."""

    def __init__(self, fallback=None, display_fallback=None):
        """`fallback`/`display_fallback` override the HIRES BITMAP faces only.

        They change nothing when the vector face loads, which is every badge
        whose /system carries the .af outlines and every playground build that
        stages them — so the default is the shipping path and these arguments
        are about the DEGRADED one.

        The defaults below are the Name Badge's, and they are right for the
        Name Badge: it is sizing DISPLAY type, where `bacteria` and `ignore`
        buy height. They are wrong for a TEXT-DENSE app, and
        `docs/engineering-findings.md` says so with numbers -- `09:00 - 10:00`
        is 140 px in `bacteria` against MonaSans@18's 94 on a 320 px canvas.
        The Settings tile hit the same wall: DECLINE measures 90 px in
        `bacteria` against the 68 px softkey box this file computes, so the
        bitmap path would clip the very label the HIRES rework exists to
        rescue. It passes `font.smart`, which is the shortest ROM face still
        taller than `sins` and the one Schedule picked for the same job.
        "Pick the HIRES bitmap fallback by the job, not from one recipe" --
        and never fall back BOLDER.
        """
        self.width = screen.width
        self.height = screen.height
        # Chrome is drawn at an integer scale so it keeps its PHYSICAL size when
        # an app opts into HIRES. Fractions alone would place the bar correctly
        # and render it at half the millimetres, dropping font.sins' 7 px cap to
        # ~11 arcmin at arm's length — below the 15 arcmin bar (a CHOSEN one;
        # see ARCMIN_FLOOR in identity/tests/hires_metrics.py).
        self.scale = max(1, self.width // 160)
        # HIRES is 1:1, so a 12 px bitmap font renders at 12 PHYSICAL px against
        # the 24 that LORES gets from pixel-doubling — which is why everything
        # looked tiny the moment the flag was flipped. Both bitmap answers are
        # wrong: integer-scaling sins by 2 throws away the sharpness that is the
        # only reason to run HIRES, and swapping in a physically taller bitmap
        # face (salty/more, which is what shipped) restores the size by spending
        # it on a heavy display face — bold, bulky, harder to read, and still
        # only 320x240 worth of chunk.
        #
        # HIRES instead draws VECTOR outlines at a fractional point size. That
        # is the actual unlock: real high-resolution type that is physically
        # SMALLER than the LORES bitmap and sharper at the same time.
        #
        # font_size is picovector's one dial: 0 means "the font's default", i.e.
        # nearest-neighbour scale 1 for a pixel font, so LORES keeps the exact
        # pixel path it has today and every call site can be written once.
        self.font_size = 0
        self.display_size = 0
        # One-entry memo for `fit_display`; see it for why it has to exist.
        self._fit_key = None
        self._fit = None
        if self.scale > 1:
            face = _load_vector(CHROME_FACE)
            if face is not None:
                self.font = self.display_font = face
                self.font_size = CHROME_PT
                self.display_size = DISPLAY_PT[1]
                # MANDATORY, not cosmetic: picovector defaults antialias to OFF
                # (image.hpp: antialias_t _antialias = OFF) and vector glyphs
                # below ~16 pt SHATTER without it. X2 and X4 measure the same,
                # so there is no cheaper middle setting. Set on `screen` only —
                # skins render into their own buffer and keep their hard edges.
                screen.antialias = image.X4
            else:
                # No vector face on this unit. Fall back FINER, not bolder: both
                # are light single-weight ROM faces at the size the heavy ones
                # were chosen for, which is the half of the old fix that was
                # right. bacteria is a 12 px cap against salty's 9, ignore
                # matches more's 17 px cap without more's ink.
                self.font = fallback if fallback is not None else font.bacteria
                self.display_font = (display_fallback
                                     if display_fallback is not None
                                     else font.ignore)
        else:
            self.font = font.sins             # 12 px tall, 6 px advance
            self.display_font = font.badgewaremax
        # Round, never truncate. `int()` biases every position down by up to a
        # pixel and makes the result depend on float precision: the same source
        # resolved A to 27 on the badge and 28 in the playground, so the browser
        # oracle no longer described the device. Rounding gives the measured
        # ruler centres (28, 73, 127) and (33, 87) on both.
        self.softkey_x = tuple(int(self.width * f + 0.5) for f in SOFTKEY_FX)
        self.scroll_y = tuple(int(self.height * f + 0.5) for f in SCROLL_FY)
        # Zone boundaries sit at the midpoints between physical button centres.
        a, b, c = self.softkey_x
        self.zones = ((0, (a + b) // 2), ((a + b) // 2 + 1, (b + c) // 2), ((b + c) // 2 + 1, self.width - 1))
        screen.font = self.font
        _, text_h = screen.measure_text("A", font_size=self.font_size)
        self.text_h = int(text_h)
        # Physical band first, never shorter than the type it carries.
        self.bar_h = max(self.text_h + 1, int(BAR_MM * self.width / PANEL_MM[0] + 0.5))
        self.bar_y = self.height - self.bar_h
        # Content area excludes the bar; chrome-free screens use the full height.
        self.content_h = self.bar_y
        self.label_w = LABEL_MAX_PX * self.scale

    def bar(self, labels, ink=None, panel=None):
        """Draw the three softkey labels, each centred on its own button.

        Each label is laid out inside its own bounded rect with ELLIPSES, so an
        oversized label degrades visibly instead of vanishing. The default
        overflow is CLIP with no ellipsis, which is exactly how a third of the
        shipping app's hint string disappeared on the physical device.
        """
        screen.font = self.font
        screen.pen = panel if panel is not None else color.rgb(0, 0, 0, 210)
        screen.rectangle(0, self.bar_y, self.width, self.bar_h)
        screen.pen = color.rgb(255, 255, 255, 64)
        screen.rectangle(0, self.bar_y - 1, self.width, 1)
        screen.pen = ink if ink is not None else color.rgb(255, 255, 255)
        # TOLERATE A SHORT SEQUENCE, because the failure mode of not doing so
        # is the worst kind this file can produce.  `labels[index]` over
        # `range(3)` raises IndexError MID-FRAME -- after the panel and the
        # hairline above have already been painted -- so a caller that passes
        # two labels does not get a wrong bar, it gets a half-drawn one and a
        # traceback.  On the launcher that is a badge which needs USB to
        # recover; in an app it is a crash on the frame a wearer pressed a key.
        #
        # Every caller today passes exactly three, so nothing triggers it.  It
        # is guarded anyway because the cost is one line and the contract is
        # already forgiving in the same direction: an empty slot draws nothing
        # and its key is inert, so a missing slot and an empty one should mean
        # the same thing rather than one being fine and the other fatal.
        for index in range(3):
            label = labels[index] if index < len(labels) else ""
            if not label:
                # An empty slot draws nothing and its key is inert. A filler
                # label would teach the wearer that the key does something.
                continue
            x = self.softkey_x[index] - self.label_w // 2
            low, high = self.zones[index]
            x = _clamp(x, low, high - self.label_w)
            screen.text(
                label,
                rect(x, self.bar_y, self.label_w, self.bar_h),
                font_size=self.font_size,
                align=(image.CENTER, image.MIDDLE),
                overflow=image.ELLIPSES,
            )

    def fit_display(self, text, budget):
        """Point size for `text` in the display face, filling `budget` px wide.

        Returns (size, width, height). At LORES the size is the sentinel 0 and
        the measurement is simply what the pixel font does — a pixel face takes
        integer scales only, so there is nothing to fit and the caller's layout
        is unchanged. At HIRES the outline face is fitted to the string: a short
        name gets bigger than any bitmap font on this device can draw, and a
        twelve-character one shrinks to fit instead of running off the canvas.

        MEMOISED on (text, budget), because the three keyboards and the confirm
        screen all call it straight out of `draw()`, i.e. once a frame, for an
        answer that can only change on a keypress. One entry is enough: a frame
        only ever draws one editor. `screen.font` is still assigned on the
        cached path — every caller relies on this leaving the display face
        selected and then draws with it.
        """
        screen.font = self.display_font
        key = (text, budget)
        if self._fit_key == key:
            return self._fit
        if not self.display_size:
            width, height = screen.measure_text(text)
            fit = (0, int(width), int(height))
            self._fit_key, self._fit = key, fit
            return fit
        # Widest size that fits, else the floor. Binary search rather than a
        # descending scan: 26..48 is 23 candidates, so the scan costs up to 23
        # `measure_text` calls on the keystroke frame — the one frame where the
        # wearer is waiting on it. The width of a string in an outline face is
        # monotonic in point size, which is what makes the halving valid, and
        # it is verified rather than assumed (`namebadge/host/chrome_type.mjs`).
        low, high = DISPLAY_PT
        width, height = screen.measure_text(text, font_size=high)
        if width <= budget:
            fit = (high, int(width), int(height))
        else:
            lo, hi, best = low, high, None
            while hi - lo > 1:
                mid = (lo + hi) // 2
                probe = screen.measure_text(text, font_size=mid)
                if probe[0] <= budget:
                    lo, best = mid, probe
                else:
                    hi = mid
            if best is None:
                best = screen.measure_text(text, font_size=lo)
            fit = (lo, int(best[0]), int(best[1]))
        self._fit_key, self._fit = key, fit
        return fit

    def scroll_hints(self, can_up, can_down):
        """Chevrons on the right edge, at the exact height of the real buttons.

        The affordance sits beside the button that drives it; that adjacency is
        the point. Drawn as triangles because ROM fonts have no arrow glyphs.
        """
        x = self.width - 4
        screen.pen = color.rgb(255, 255, 255, 200)
        if can_up:
            y = self.scroll_y[0]
            screen.triangle(x, y + 2, x + 3, y + 2, x + 1, y - 2)
        if can_down:
            y = self.scroll_y[1]
            screen.triangle(x, y - 2, x + 3, y - 2, x + 1, y + 2)

    def position(self, index, total):
        """A slim progress rail on the right edge, spanning the content area."""
        if total <= 1:
            return
        x = self.width - 2
        screen.pen = color.rgb(255, 255, 255, 60)
        screen.rectangle(x, 0, 2, self.content_h)
        span = self.content_h
        thumb = span // 8
        if thumb < 4:
            thumb = 4
        top = (span - thumb) * index // (total - 1)
        screen.pen = color.rgb(255, 255, 255, 230)
        screen.rectangle(x, top, 2, thumb)


class ListView:
    """A virtualised vertical list. UP/DOWN move the selection; nothing else."""

    def __init__(self, chrome, row_h=None):
        self.chrome = chrome
        # A row is the type plus one logical pixel of air above and below, so
        # the gutter keeps its physical size when the resolution flips. At HIRES
        # that is a 21 px row against LORES's 14 logical (28 physical): the rows
        # are physically tighter, which is exactly what the extra resolution is
        # for — ten skins visible instead of seven, in finer type.
        self.row_h = row_h if row_h else chrome.text_h + 2 * chrome.scale
        self.rows = chrome.content_h // self.row_h
        self.index = 0
        self.top = 0
        # Retained row plates, HIRES only — see `draw`. One slot per visible
        # row, addressed by `index % rows`, so the window's own arithmetic is
        # the eviction policy: scrolling by one row reuses the slot the row
        # that just left the window was using. Bounded at `rows` entries
        # (~97 KB for the ten-row skin list) with no per-frame allocation.
        self._plates = [None] * self.rows if chrome.font_size else None

    def move(self, delta, total):
        if total <= 0:
            return False
        before = self.index
        self.index = (self.index + delta) % total
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + self.rows:
            self.top = self.index - self.rows + 1
        # Keep the window valid after a wrap.
        self.top = _clamp(self.top, 0, max(0, total - self.rows))
        return self.index != before

    def _plate(self, label):
        """`label` rasterised once, white, on transparent, at row pitch."""
        chrome = self.chrome
        text_w, text_h = screen.measure_text(label, font_size=chrome.font_size)
        width = int(text_w) + 2 * chrome.scale
        # Normally the row pitch, but never shorter than the line box: a plate
        # is the only place a tall glyph could be CLIPPED, where drawing
        # straight onto the screen would simply let it spill.
        height = max(self.row_h, int(text_h) + chrome.scale)
        plate = image(width, height, bytearray(width * height * 4))
        plate.antialias = image.X4
        plate.font = chrome.font
        plate.pen = color.rgb(255, 255, 255)
        plate.text(label, 0, chrome.scale, font_size=chrome.font_size)
        return plate

    def draw(self, total, label_for, accent):
        """The visible window. At HIRES the unselected rows come from plates.

        A list is the most text this app draws in one frame, and at HIRES that
        text is vector outlines: ten rows measured 4.9x the bitmap build they
        replace, on the two screens a wearer holds DOWN on. But a row's ink is
        a pure function of its string, and scrolling by one row changes exactly
        ONE of the ten — so the rows are rasterised once each and blitted
        thereafter, which is the same discipline the nickname plate already
        uses. The selected row is still drawn directly: it is one row, and its
        ink is the accent's opposite rather than white.

        LORES keeps the direct path untouched and byte-identical. Bitmap glyphs
        are cheap enough that plating them would buy nothing and would risk the
        chunky look that is the whole point of that build.
        """
        chrome = self.chrome
        screen.font = chrome.font
        plates = self._plates
        for row in range(self.rows):
            index = self.top + row
            if index >= total:
                break
            y = row * self.row_h
            label = label_for(index)
            if index == self.index:
                screen.pen = accent
                screen.rectangle(0, y, chrome.width - 3, self.row_h)
                screen.pen = color.rgb(0, 0, 0)
                screen.text(label, 3, y + chrome.scale, font_size=chrome.font_size)
            elif plates is None:
                screen.pen = color.rgb(255, 255, 255)
                screen.text(label, 3, y + chrome.scale, font_size=chrome.font_size)
            else:
                slot = index % self.rows
                held = plates[slot]
                if held is None or held[0] != label:
                    held = (label, self._plate(label))
                    plates[slot] = held
                screen.blit(held[1], vec2(3, y))
        self.chrome.position(self.index, total)
        self.chrome.scroll_hints(total > 1, total > 1)
