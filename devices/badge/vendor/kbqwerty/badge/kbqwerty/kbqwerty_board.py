"""The board `kbqwerty` types on: iOS's three planes, on five buttons.

THE ONLY HAND-WRITTEN FILE IN THIS APP.  Everything else under
`kbqwerty/badge/kbqwerty/` is a generated copy of a canonical module that
`kbgrid` gets byte for byte (`python3 scripts/sync_ui.py --check` proves it),
and that property is UNCHANGED by this rework -- see section 5 for the price
that was paid to keep it.

=========================================================================
1.  WHAT THE OWNER ASKED FOR, TRANSCRIBED
=========================================================================

Three planes, taken off three iOS screenshots.  The LAYOUT and the BEHAVIOUR
only: none of iOS's theme, graphics, rounded keys or colour.

    LETTERS   Q W E R T Y U I O P
              A S D F G H J K L                  (inset half a key)
              [shift] Z X C V B N M [back]
              [123]   [space]   [done]

    NUMBERS   1 2 3 4 5 6 7 8 9 0
              - / : ; ( ) $ & @ "
              [#+=] . , ? ! ' [back]
              [ABC]   [space]   [done]

    SYMBOLS   [ ] { } # % ^ * + =
              _ \\ | ~ < > € £ ¢ •
              [123] . , ? ! ' [back]
              [ABC]   [space]   [done]

    letters --[123]--> numbers --[#+=]--> symbols
    numbers --[ABC]--> letters
    symbols --[123]--> numbers,  symbols --[ABC]--> letters

TWO DEVIATIONS FROM THE TRANSCRIPTION, both forced and both recorded in
`kb/README.md`'s deviations register:

  * `¥` IS NOT ON THE SYMBOL PLANE.  `font.sins` cannot draw it -- see
    section 3.  `¢` is in the slot instead.
  * ROW 4 HAS A FOURTH KEY, `BACK`.  With the softkey bar gone (section 4)
    the board is the only surface left, so the labelled way out that commits
    nothing has to be a cell or I2 is unsatisfiable.  iOS's own fourth row
    has four slots too -- the globe key sits where BACK sits here.

=========================================================================
2.  TWENTY UNITS, AND WHY THAT IS THE WHOLE GEOMETRY ARGUMENT
=========================================================================

A key is 2 units, so a half key is 1 and the board is 20 units wide.  160 / 20
is EXACTLY 8 px, so `kb_shell.KeyboardView._pixels` -- `(x * 160 + 10) // 20`
-- resolves every boundary with no rounding drift at all and every letter key
is exactly 16 px.  The old 22-unit staggered board divided 160 by 22 and got
ragged 14 and 15 px keys; this one cannot.

    row 0   10 keys x 2u, offset 0             x = 0 .. 20
    row 1    9 keys x 2u, offset 1             x = 1 .. 19
    row 2   3u + 7 keys x 2u + 3u   (letters)  x = 0 .. 20
            5u + 5 keys x 2u + 5u   (digits)   x = 0 .. 20
    row 3   3u + 4u + 8u + 5u                  x = 0 .. 20

THE HALF-KEY INSET ON ROW 1 COSTS NOTHING IN KEY WIDTH, which is the thing
the brief was right to worry about and wrong to fear.  The row has NINE keys,
not ten, so the two 8 px shoulders come out of the missing tenth key rather
than out of the other nine: every letter on every plane is the same 16 px.

LEGIBILITY, MEASURED.  `font.sins` at scale 1 advances 6 px for an uppercase
glyph and 9 px for `%`, the widest glyph on any of the three planes.  In a
16 px cell that is 5 px of clear background each side (3.5 for `%`), and a
16 px pitch against a 6 px advance leaves 10 px of background between one
key's ink and the next -- ten times the 1 px gap inside a word, which is what
makes a row read as keys rather than as a string.  The cap ink is 7 px, i.e.
2.6 mm, i.e. 22.6 arcmin at 400 mm, above this project's 15 arcmin floor.
Note what did NOT happen: a bitmap face at scale 1 is a fixed size, so the
bigger cell buys SPACING, never bigger type.

=========================================================================
3.  THE FONT DECIDED THE SYMBOL PLANE.  ONE GLYPH HAD TO GO.
=========================================================================

Measured in the pinned WASM runtime against the real `font.sins`, by advance
AND by counting ink pixels in a rendered buffer -- an advance alone cannot
tell a space from a missing glyph.

`¥` (U+00A5) IS THE ONLY CHARACTER IN ALL THREE PLANES THE FONT CANNOT DRAW.
Advance 0, ink 0: rendering "A¥A" is byte-identical to rendering "AA".  It
would not even be a blank box -- it would be an empty cell the caret could
still land on, which is worse, because nothing on the screen would say why.
It is missing from ALL 37 ROM faces, not just `sins`, so no display face
anywhere on this badge could rescue it.

    ¥  ->  ¢  (U+00A2, advance 6, 12 ink px, present in all 37 faces)

`¢` keeps the slot a CURRENCY symbol, so row 1 of the symbol plane still
reads "the currency run, then a bullet" the way the screenshot does, and the
row keeps its ten columns with no re-flow.  Measured alternates, if the owner
would rather have a non-currency mark there: `°` 5 px, `™` 8 px, `©` 9 px,
`…` 7 px, `«` `»` 6 px.  REJECTED: `·` (U+00B7) is in the font but draws a
SINGLE pixel.

NO ARROW EXISTS ANYWHERE IN THE ROM, so the shift key and the delete key are
LETTERED.  `⇧` `↑` `▲` `⌫` `⌦` all measure advance 0 and ink 0, and so do
`§ ± × ÷ µ →`, which were probed as stand-ins.  Hence "abc"/"ABC" on shift
(18 px in a 24 px cell) and "DEL" on delete (18 px).  "CAPS" is 24 px in that
24 px cell -- an exact fill, which `_cell` would ellipsise -- and "SHIFT" is
28 px and does not fit at all.

EVERYTHING ELSE DRAWS, verified glyph by glyph with real ink: all 26
uppercase, all 26 LOWERCASE (which the inverted shift needs), 0-9, the whole
of `- / : ; ( ) $ & @ " . , ? ! '`, the whole of `[ ] { } # % ^ * + = _ \\ |
~ < >`, and `€` (8 px), `£` (7 px), `•` (4 px).

ONE HONEST FLAG ABOUT `•`.  It is a real glyph, but its ink is a 2x2 px dot:
0.75 mm, about 6.4 arcmin at 400 mm, under this project's own 15 arcmin
floor.  It will read as a speck on the panel.  It is kept because iOS's
bullet is a dot too and because it draws; `°` (5 px, 3 px tall) is the swap
if the owner wants it visible.

Reproduce with `node identity/host/measure_faces.mjs` for the per-face
ladder; the per-glyph ink probe is described in `kb/README.md` section 3.

=========================================================================
4.  THE BUTTON HINTS ARE NOT KEYS, AND THE SHIFT LATCHES
=========================================================================

THE HINT STRIP.  A, B and C still move left, commit and move right; the owner
now wants those three meanings visible while typing.  They are descriptive
hardware-button hints, not selectable board cells, so the strip draws simple
vector arrows/check below the board and never enters `ROWS`, `LAYOUT` or the
caret model.  `BAR` remains three empty strings because the text-softkey API is
still not the surface being used and the KB_BOOT marker must not claim three
selectable text actions.

The strip is 22 px tall at HIRES (11 px at LORES), INCLUDING its top border.
Most of that cost comes from the BACK/SPACE/DONE row: at LORES the three
recognition rows move from 22 px to 21 px while the action row moves to 14 px.
The board keeps its accepted top edge, so the header does not shift and the
letter keys lose only one logical pixel each.  The chevrons and check are 15 px
tall at HIRES; the check is shifted 15 px right to match the owner's mock-up.
Ten columns still fit because a unit is 8 px; the hint strip does not
participate in horizontal geometry.

THE SHIFT IS INVERTED AND IT LATCHES.  A badge types a NAME, so the letters
are UPPERCASE by default and the shift key switches to lowercase -- the
opposite of a phone.

LATCHING rather than one-shot, and the arithmetic is the argument: a one-shot
shift charges one extra press for EVERY lowercase letter, so "mcdonald" would
cost eight extra presses plus the walking between them; a latch charges one
press per CASE CHANGE, which for a name is one.  Nothing on a badge types a
single lowercase letter in the middle of capitals.

THE STATE IS VISIBLE TWICE, and the second one is the strong one:

  1.  the key names the case the NEXT press will produce -- "abc" while the
      board is upper, "ABC" while it is lower;
  2.  THE WHOLE BOARD REDRAWS IN THE ACTIVE CASE.  Thirty-two keys changing
      shape is not a state indicator anyone can miss, and it is free.

NOT indicated by filling the key: `kb_shell._cell` already uses the accent
fill for the CARET, so a filled shift key would look like the cursor.

The latch SURVIVES a plane switch: go to the number plane for a hyphen and
come back and you are still in lowercase.  A name is typed in one case and
the hyphen in the middle of it should not silently reset the board.

=========================================================================
5.  THE PRICE OF KEEPING `kbgrid` BYTE-FROZEN
=========================================================================

READ THIS BEFORE CHANGING ANYTHING BELOW.

Three planes and no softkey bar are both VIEW changes.  `kb_shell.
KeyboardView` freezes its pixel geometry in `__init__` (`self.cells` is built
once from `board.LAYOUT`) and draws `chrome.bar(...)` unconditionally at the
end of `draw`, so neither could be done from a board module by data alone.

The obvious fix is to teach `shared/kb_shell.py` about planes.  That file is
copied BYTE FOR BYTE into both apps by `scripts/sync_ui.py`, so teaching it
anything moves `kbgrid`'s bytes -- and `kbgrid` is the CONTROL in a
comparison the owner is still running.  Forking the file is worse, not
better: `launch()` and `pg_runtime.launch_app` can start a second app in one
interpreter and sub-modules land in `sys.modules` under their BARE names, so
two different `kb_shell.py` files would mean whichever app booted first wins
and the second one silently runs the other's shell.  That collision is
harmless TODAY only because the two copies are identical.

So the board ADOPTS THE SHELL instead.  `PlaneView` below subclasses
`kb_shell.KeyboardView`, and the module rebinds `kb_shell.KeyboardView` to it
at import time so the seam -- which is also byte-frozen -- constructs the
subclass without naming it.

THE SUBCLASS IS BOARD-AGNOSTIC AND DEGRADES TO THE BASE.  It keys entirely
off `getattr(board, "PLANES", None)`, so if `kbgrid` is launched into the
same interpreter afterwards it gets a `PlaneView` that is the base class in
every observable respect.  `kb/tests/test_kbqwerty_board.py::AdoptionTests`
asserts that, and `playground/e2e/kb-layouts.spec.ts` boots both apps in one
runtime to prove it where it actually matters.

WHAT DID NOT CHANGE, and it is the whole point: `shared/kb_shell.py`,
`shared/kb_seam.py`, `shared/ui.py` and `identity_keyboard.py` are untouched,
`scripts/sync_ui.py --check` still passes, and every file in `kbgrid/` is
byte-identical to what it was.

WHAT IS HONESTLY WORSE.  The two apps' CHROME -- header, field, caret, the
`n/12` counter, the press counter -- is no longer identical by CONSTRUCTION,
because `PlaneView.draw` re-states the header block instead of inheriting it.
It is now identical by TEST: `test_kb_sameness::ChromeTests` pins every
constant the two draws share.  That is a real weakening of the sameness
guarantee and `kb/README.md` says so in its own words.

=========================================================================
6.  THE CARET, WHICH IS `identity`'s WITH TWO CHANGES
=========================================================================

`PlaneModel` subclasses `identity_keyboard.GridModel`.  `find`, `width`,
`cell`, `full`, `text`, `limit` and all five outcome constants are the
shipped code, and `press` DELEGATES to the shipped `press` for every cell
that is not a mode key.

  * THE LANDING RULE, as on the old staggered board: the caret carries a goal
    X-POSITION in doubled units rather than a column index, `move_row` lands
    on the key whose drawn CENTRE is nearest that goal and leaves the goal
    alone, and `move_column` adopts the new key's centre.  Doubled units so
    the goal is always an `int`: caret tuples are dictionary keys in the route
    search, and `identity` records single-precision divergence between
    CPython and the device, which would make a published press count depend
    on which machine produced it.

  * THE PLANE SWITCH uses the SAME rule.  Pressing a mode key swaps the rows
    and the centre table and then re-lands on the nearest centre to the
    UNTOUCHED goal, so the key stays under the thumb: `[123]` on the letter
    plane and `[ABC]` on the number plane are both row 3 column 0, and
    switching back and forth never moves the caret.

`caret()` IS STILL A THREE-TUPLE.  The seam and the shell both unpack it as
`row, column, goal`, and both are byte-frozen.  The plane and the case are
therefore carried by `state()` / `resume()` instead, which the route search
and the tests use -- the same role `GridModel.restore` already plays, and
like `restore` the app itself never calls them.

NOTHING IS STRANDED, and it had to be checked rather than assumed.  A board
whose rows have different key counts can hide a key: if no goal the caret can
hold is ever nearest to some key's centre, that key is reachable only by
walking sideways along its own row.  `P` is the one at risk -- row 1's
rightmost centre is 36 and `P`'s is 38, and a goal of 36 ties between `O` and
`P` and breaks LEFTMOST onto `O`.  `P` survives because the wide `DEL` key on
row 2 has centre 37, and a caret carrying 37 lands on `P`.
`test_kbqwerty_board::test_no_cell_is_stranded_off_the_vertical_axis` walks
every reachable state on every plane and asserts the landing set covers all
of them.
"""

import identity_keyboard as keyboard
import kb_shell


TITLE = "QWERTY"

# `identity_keyboard`'s four verbs, unchanged, so `press` can stay the shipped
# one for every cell that is not a mode key.
SPACE = keyboard.SPACE
BACK = keyboard.BACK
DEL = keyboard.DEL
DONE = keyboard.DONE

# The four MODE cells.  Tokens rather than labels, because `SHIFT`'s label
# changes with the state it reports and `NUM`'s label is "123", which would
# otherwise be indistinguishable from three digit cells in a `find`.
SHIFT = "SHIFT"
NUM = "NUM"
SYM = "SYM"
ABC = "ABC"
MODES = (SHIFT, NUM, SYM, ABC)

LETTERS, NUMBERS, SYMBOLS = 0, 1, 2

# Where each switch key goes.  `SHIFT` is not here: it changes the CASE, not
# the plane, and the two are separate axes so that returning from the number
# plane restores the case you left in.
SWITCHES = {NUM: NUMBERS, SYM: SYMBOLS, ABC: LETTERS}


UPPER_ROWS = (
    ("Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"),
    ("A", "S", "D", "F", "G", "H", "J", "K", "L"),
    (SHIFT, "Z", "X", "C", "V", "B", "N", "M", DEL),
    (NUM, BACK, SPACE, DONE),
)

# The same board in the other case, built rather than written out: two hand-
# written copies of QWERTY are two things that can disagree, and the way that
# bug presents is one letter that types the wrong case.
def _lowered(rows):
    out = []
    for row in rows:
        out.append(tuple(cell.lower() if len(cell) == 1 else cell
                         for cell in row))
    return tuple(out)


LOWER_ROWS = _lowered(UPPER_ROWS)

NUMBER_ROWS = (
    ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"),
    ("-", "/", ":", ";", "(", ")", "$", "&", "@", "\""),
    (SYM, ".", ",", "?", "!", "'", DEL),
    (ABC, BACK, SPACE, DONE),
)

# `¢` stands where the screenshot has `¥`; section 3 has the measurement and
# the reason.  The backslash is escaped, not doubled: the cell types one.
SYMBOL_ROWS = (
    ("[", "]", "{", "}", "#", "%", "^", "*", "+", "="),
    ("_", "\\", "|", "~", "<", ">", "€", "£", "¢", "•"),
    (NUM, ".", ",", "?", "!", "'", DEL),
    (ABC, BACK, SPACE, DONE),
)


# One key is two units, so a half-key inset is one unit and nothing in any
# layout is ever a fraction.
KEY_UNITS = 2

# The product keyboard is HIRES, so these dimensions are stated in the pixels
# the owner reviews.  `_hires_px` halves them for the retired LORES bench while
# preserving the same physical size; keeping them here makes the mock-up's
# three exact measurements testable rather than hidden in vector arithmetic.
HIRES_SCALE = 2
HINT_H_HIRES = 22
HINT_ICON_H_HIRES = 15
HINT_CHECK_SHIFT_HIRES = 15


def _hires_px(pixels, scale):
    """Scale one HIRES measurement without truncating odd-sized icons."""
    return (pixels * scale + HIRES_SCALE - 1) // HIRES_SCALE


UNITS = 20


def _run(offset, count, key=KEY_UNITS):
    """`count` plain keys in a row, starting at `offset`, in units."""
    return tuple((offset + index * key, key) for index in range(count))


# The verb row is the same on all three planes, so the switch key, SPACE and
# DONE never move under the thumb.  BACK second rather than first because the
# owner's transcription puts the plane switch leftmost and because BACK is
# still where a wrap from the top row can land harmlessly (B7).
VERB_LAYOUT = ((0, 3), (3, 4), (7, 8), (15, 5))

LETTER_LAYOUT = (
    _run(0, 10),
    _run(1, 9),
    ((0, 3),) + _run(3, 7) + ((17, 3),),
    VERB_LAYOUT,
)

# The number and symbol planes are the same shape as each other, which is what
# lets `[#+=]` and `[123]` sit on the same pixels and toggle.
DIGIT_LAYOUT = (
    _run(0, 10),
    _run(0, 10),
    ((0, 5),) + _run(5, 5) + ((15, 5),),
    VERB_LAYOUT,
)


def _centres(layout):
    """Twice each cell's centre x, per row, in units.

    DOUBLED so a half-unit centre is still an `int`: a cell at `x` of width
    `w` is centred on `x + w/2`, and `2x + w` says the same thing without ever
    leaving the integers.
    """
    return tuple(tuple(2 * x + w for x, w in row) for row in layout)


# The three planes, in switch order.  Each entry is
# `(name, (upper rows, lower rows), layout, centres)`; on the two planes that
# have no case the two row tuples are the same object.
PLANES = (
    ("ABC", (UPPER_ROWS, LOWER_ROWS), LETTER_LAYOUT, _centres(LETTER_LAYOUT)),
    ("123", (NUMBER_ROWS, NUMBER_ROWS), DIGIT_LAYOUT, _centres(DIGIT_LAYOUT)),
    ("#+=", (SYMBOL_ROWS, SYMBOL_ROWS), DIGIT_LAYOUT, _centres(DIGIT_LAYOUT)),
)


def plane_rows(plane, upper=True):
    return PLANES[plane][1][0 if upper else 1]


def plane_layout(plane):
    return PLANES[plane][2]


def plane_centres(plane):
    return PLANES[plane][3]


def identify(rows):
    """`(plane, upper)` for a rows tuple, or the default if it is not one.

    The shell constructs the model with `rows=board.ROWS`, and the ablations
    and tests construct it with a plane's rows directly.  Deriving the plane
    from the rows rather than trusting a separate argument is what stops a
    model whose `centres` describe a different plane from the one it is
    drawing -- which would land the caret on the wrong key and be invisible
    until somebody pressed B.
    """
    for plane in range(len(PLANES)):
        variants = PLANES[plane][1]
        if rows == variants[0]:
            return plane, True
        if rows == variants[1]:
            return plane, False
    return LETTERS, True


# `G`: the home row's left index reach, and the cell a typist's hand is
# already on.  Both axes wrap, so no cell is a corner and the opening cell is
# a genuinely free parameter -- `python3 kb/host/kb_press_counts.py --open`
# scores all of them on the fitted half of the corpus.
OPENS_AT = (1, 4)

# NO SOFTKEY BAR.  Three empty slots rather than a deleted attribute: the
# board still presents the shell's whole surface, `chrome.bar` already treats
# an empty label as an inert key that draws nothing, and the KB_BOOT marker
# reports `keys=||` so the browser lane can assert the bar is gone rather than
# assume it.  Section 4 has the owner's instruction and the arithmetic.
BAR = ("", "", "")

# Only the two switch keys need a label that is not their token.  SHIFT's is a
# function of the case and is in `label()`; `ABC`, `SPACE`, `BACK`, `DEL` and
# `DONE` all draw as themselves and all fit (18, 30, 24, 18, 24 px against
# 24, 64, 32, 24/40 and 40 px cells).
LABELS = {NUM: "123", SYM: "#+="}

# What the shift key says while the board is upper, and while it is lower.
# It names the case the NEXT press produces, so the label is an instruction
# rather than a status word -- and it is the only two-way readout that fits
# the 24 px cell ("CAPS" is 24 px exactly and would ellipsise, "SHIFT" is 28).
SHIFT_TO_LOWER = "abc"
SHIFT_TO_UPPER = "ABC"


# --------------------------------------------------------------------------
# the visible plane
# --------------------------------------------------------------------------

# THE PUBLISHED PLANE.  `kb_seam.update` prints `board.ROWS[row][column]` in
# its KB_CELL marker and `KeyboardApp.__init__` reads `board.ROWS` to build the
# model, and both files are byte-frozen (section 5).  So the module keeps
# `ROWS`, `LAYOUT` and `CENTRES` pointing at whatever plane is on screen, and
# `PlaneView.draw` republishes before the seam reads them.  Indexing plane 0's
# nine-cell row 1 with a column from plane 1's ten-cell row 1 would be an
# IndexError in the seam -- i.e. a crash, not a wrong label -- so this is
# load-bearing rather than tidy.
PLANE = LETTERS
UPPER = True
ROWS = UPPER_ROWS
LAYOUT = LETTER_LAYOUT
CENTRES = _centres(LETTER_LAYOUT)


def publish(plane, upper):
    """Point the module-level board at the plane that is on screen."""
    global PLANE, UPPER, ROWS, LAYOUT, CENTRES
    PLANE = plane
    UPPER = upper
    ROWS = plane_rows(plane, upper)
    LAYOUT = plane_layout(plane)
    CENTRES = plane_centres(plane)


def label(cell):
    """What the view draws in a cell.  Never wider than the cell.

    `kb/tests/test_kbqwerty_board.py` measures every label on every plane, in
    both cases, against its cell's pixel width at `font.sins`, because the
    renderer drops out-of-bounds glyphs SILENTLY -- which is how `profile`
    shipped an editor whose entry point was invisible on the physical device.
    """
    if cell == SHIFT:
        return SHIFT_TO_LOWER if UPPER else SHIFT_TO_UPPER
    return LABELS[cell] if cell in LABELS else cell


def glyph(cell):
    """The character a cell types, or "" for a verb or a mode key."""
    if cell in MODES:
        return ""
    return keyboard.glyph(cell)


def boards():
    """Every distinct `(plane, upper, rows)` this board can show.

    Two entries for the letter plane and one each for the others, so a caller
    that wants "all the keys there are" cannot miss the lowercase half.
    """
    out = []
    for plane in range(len(PLANES)):
        upper_rows, lower_rows = PLANES[plane][1]
        out.append((plane, True, upper_rows))
        if lower_rows is not upper_rows:
            out.append((plane, False, lower_rows))
    return tuple(out)


def bank():
    """Every character this board can type, in reading order over the planes.

    Derived from the planes rather than written down beside them: a bank and a
    board that are two lists are two lists that can disagree, and the way that
    bug presents is a glyph nobody can reach.
    """
    out = ""
    for _plane, _upper, rows in boards():
        for row in rows:
            for cell in row:
                character = glyph(cell)
                if character and character not in out:
                    out += character
    return out


# --------------------------------------------------------------------------
# the caret
# --------------------------------------------------------------------------

SWITCHED = "switched"
SHIFTED = "shifted"


class PlaneModel(keyboard.GridModel):
    """`identity`'s caret, with a nearest-centre landing rule and three planes.

    The class is a `GridModel`, not a copy of one, so `press()` is the shipped
    code for every cell that is not a mode key and the host counter drives
    this board through the same functions it drives the grid through.
    """

    def __init__(self, text="", limit=keyboard.DEFAULT_LIMIT, rows=None,
                 opens_at=OPENS_AT):
        # Before the base constructor, which calls `self.width()` and lands the
        # caret: the plane, its rows and its centre table must be in step from
        # the first line or the caret lands against the wrong geometry.
        #
        # THE DEFAULT IS THE LETTER PLANE, NOT THE PUBLISHED ONE.  A caret with
        # no rows given opens where the BOARD opens, so a route search and a
        # test get the same answer whatever happens to be on screen -- the
        # published mirror is a consequence of the live model, and taking a
        # default from it would make a press count depend on module state.
        # `KeyboardApp` passes `board.ROWS` explicitly and therefore does follow
        # the mirror, which is right: it is building a model for what is shown.
        if rows is None:
            rows = plane_rows(LETTERS, True)
        self.plane, self.upper = identify(rows)
        self.centres = plane_centres(self.plane)
        keyboard.GridModel.__init__(self, text=text, limit=limit,
                                    rows=plane_rows(self.plane, self.upper),
                                    opens_at=opens_at)
        # The base class set `goal = column`, which is the unit this subclass
        # does not use.  Restated in centre units, which also establishes the
        # invariant every move below preserves.
        self.goal = self.centres[self.row][self.column]

    # -- state ---------------------------------------------------------------

    def state(self):
        """The WHOLE of the caret, plane and case included.

        `caret()` cannot carry them: `kb_shell.KeyboardView.draw` and
        `kb_seam.update` both unpack it as `row, column, goal` and both files
        are byte-frozen.  Like `GridModel.restore`, this pair exists for the
        route search and the tests; the app never calls either.
        """
        return (self.plane, self.upper, self.row, self.column, self.goal)

    def resume(self, state):
        plane, upper, row, column, goal = state
        self.plane = plane
        self.upper = upper
        self.rows = plane_rows(plane, upper)
        self.centres = plane_centres(plane)
        self.row = row
        self.column = column
        self.goal = goal

    def locate(self, token):
        """`(plane, upper, row, column)` for a token, over every plane.

        First match in switch order.  Returns None for a token no plane
        carries, which is what makes an unreachable character a loud KeyError
        in the counter rather than a silent misprint.
        """
        for plane, upper, rows in boards():
            for row in range(len(rows)):
                line = rows[row]
                for column in range(len(line)):
                    if line[column] == token:
                        return (plane, upper, row, column)
        return None

    def switches_to(self, token):
        """The mode cells to press, in order, to bring `token` into view.

        `()` if it is already on the visible plane, which is the answer for
        SPACE, BACK, DEL and DONE from anywhere -- they are on all three
        planes, and a route that walked back to the letters for a space would
        be measuring a board nobody has to use.  None if no plane carries it.

        Discovered by DRIVING THIS MODEL: each candidate switch key is found
        with the shipped `find`, pressed with the real `press`, and the mode it
        lands in is read back off the object.  There is no second description
        of the switch graph anywhere, which is the same rule
        `kb/host/kb_press_counts.py` is built on.
        """
        if self.find(token) is not None:
            return ()
        if self.locate(token) is None:
            return None
        keep = self.state()
        try:
            here = (self.plane, self.upper)
            seen = {here: ()}
            frontier = [here]
            while frontier:
                following = []
                for mode in frontier:
                    for cell in MODES:
                        self.resume((mode[0], mode[1], 0, 0, 0))
                        at = self.find(cell)
                        if at is None:
                            continue
                        self.resume((mode[0], mode[1], at[0], at[1], 0))
                        self.press()
                        landed = (self.plane, self.upper)
                        if landed in seen:
                            continue
                        route = seen[mode] + (cell,)
                        seen[landed] = route
                        if self.find(token) is not None:
                            return route
                        following.append(landed)
                frontier = following
        finally:
            self.resume(keep)
        return None

    # -- movement ------------------------------------------------------------

    def _nearest(self, row, goal):
        """The column of `row` whose drawn centre is closest to `goal`.

        Ties break LEFTMOST via the strict comparison, and the tie-break has to
        be deterministic rather than merely consistent-looking: it is what
        makes UP-then-DOWN an identity on a board where rows of nine and ten
        keys put two cells exactly equidistant from a goal.
        """
        line = self.centres[row]
        best, gap = 0, None
        for column in range(len(line)):
            distance = line[column] - goal
            if distance < 0:
                distance = -distance
            if gap is None or distance < gap:
                best, gap = column, distance
        return best

    def move_row(self, step):
        """UP is negative, DOWN is positive.  Wraps.  The goal is untouched.

        Signed, because `ui.Repeat.step` returns a COUNT: a key held at the top
        of the ramp yields more than one step in a frame and a model that only
        understood +-1 would drop the rest.
        """
        if not step:
            return
        self.row = (self.row + step) % len(self.rows)
        self.column = self._nearest(self.row, self.goal)

    def move_column(self, step):
        """A is negative, C is positive.  Wraps over THIS row's width."""
        if not step:
            return
        self.column = (self.column + step) % self.width()
        self.goal = self.centres[self.row][self.column]

    # -- the primary action --------------------------------------------------

    def _retarget(self, plane, upper):
        """Swap the board under the caret and re-land on the same GOAL.

        The same rule `move_row` uses, for the same reason: the goal is a
        position on the SCREEN, so re-landing on the nearest centre to it is
        what keeps the switch key under the thumb.  `[123]` on the letter plane
        and `[ABC]` on the number plane are both row 3 column 0.
        """
        self.plane = plane
        self.upper = upper
        self.rows = plane_rows(plane, upper)
        self.centres = plane_centres(plane)
        if self.row >= len(self.rows):
            self.row = len(self.rows) - 1
        self.column = self._nearest(self.row, self.goal)

    def press(self):
        """B.  The shipped `press` for everything except a mode key.

        The two mode outcomes are new words rather than reuses of the five
        shipped ones.  `KeyboardApp.frame` acts only on COMMITTED and
        ABANDONED and ignores everything else, so a new word costs the frozen
        shell nothing -- and reusing TYPED would have told a caller that the
        text changed when it did not.
        """
        cell = self.cell()
        if cell == SHIFT:
            self._retarget(self.plane, not self.upper)
            return SHIFTED
        if cell in SWITCHES:
            self._retarget(SWITCHES[cell], self.upper)
            return SWITCHED
        return keyboard.GridModel.press(self)


def reset():
    """Put the published mirror back to a cold start: LETTERS, uppercase."""
    publish(LETTERS, True)


def Model(*args, **kwargs):
    """The board entry point the SHARED seam calls, and the only cold start.

    `kb_shell.KeyboardApp.__init__` calls `board.Model(..., rows=board.ROWS)`
    exactly once per app, so this call IS the launch -- and it is the one
    moment the mirror must be ignored rather than followed.

    THE BUG THIS CLOSES. `publish()` mutates module globals and nothing reset
    them, so in the playground -- where app modules stay resident between
    launches -- a session that ended on the symbol plane handed the next one a
    symbol board, and a session that ended in lowercase handed the next one
    lowercase. On a keyboard whose whole premise is that a badge name is
    usually capitals.

    HARDWARE DOES NOT HAVE THE FAULT, and the difference is the point:
    `badgeware.launch()` deletes every module the app imported from
    `sys.modules` on the way out, so the next launch re-imports this file and
    the globals are genuinely fresh. The playground's compat layer keeps them
    resident. That makes this a browser-versus-badge divergence rather than a
    device defect -- the same class as the playground compiling picovector
    single-core while the badge runs it dual-core. The owner tries these
    keyboards in the PLAYGROUND, which is exactly where he would meet it, and a
    keyboard opening in the wrong case reads as a bug in the layout rather than
    in the harness.

    A function rather than the bare `Model = PlaneModel` alias because the fix
    has to live on THIS side of the seam: `shared/kb_shell.py` is vendored
    byte-for-byte into `kbgrid` too, and `kbgrid` is the control in a
    comparison the owner is running. Its bytes may not move.

    Plane switching still goes through `PlaneModel._retarget`, which SHOULD
    follow the mirror: it is rebuilding a model for what is on screen.
    """
    reset()
    kwargs["rows"] = ROWS
    return PlaneModel(*args, **kwargs)


def row_geometry(height, head_h, hint_y, rows, scale):
    """`(board_y, row_heights)` with most hint cost paid by the verb row.

    The existing board top is retained.  Taking one logical pixel from each
    recognition row leaves their accepted physical size almost unchanged;
    everything else needed to clear the hint strip comes from the final action
    row, where the labels are short and recognition is not the task.
    """
    full_h = (height - head_h) // rows
    board_y = height - full_h * rows
    key_h = full_h - scale
    action_h = hint_y - board_y - key_h * (rows - 1)
    return board_y, (key_h,) * (rows - 1) + (action_h,)


# --------------------------------------------------------------------------
# the view the board brings with it
# --------------------------------------------------------------------------

# Reload-safe: if this module is re-executed, subclass the ORIGINAL shell view
# rather than the subclass installed by the previous run.
_BASE_VIEW = getattr(kb_shell.KeyboardView, "_PLAIN", kb_shell.KeyboardView)


class PlaneView(_BASE_VIEW):
    """`kb_shell.KeyboardView` plus planes and hardware-button hints.

    BOARD-AGNOSTIC ON PURPOSE.  Everything below keys off `board.PLANES`, so a
    board without one -- `kbgrid`'s -- gets the base class's behaviour
    unchanged.  That matters because this class is installed over
    `kb_shell.KeyboardView` for the whole interpreter (section 5), and
    `launch()` can start `kbgrid` after this app in the same session.
    """

    _PLAIN = _BASE_VIEW

    def __init__(self, board, screen_api, image_api, color_api, font_api,
                 rect_api):
        _BASE_VIEW.__init__(self, board, screen_api, image_api, color_api,
                            font_api, rect_api)
        self.planes = getattr(board, "PLANES", None)
        if self.planes is None:
            return
        chrome = self.chrome
        # Keep the old top edge and reclaim most of the hint strip from the
        # action row.  Equal-height rows would shrink every recognition key
        # even though only BACK/SPACE/DONE can give up space without making
        # letters harder to scan.  `hint_h` includes its top border.
        rows = len(board.LAYOUT)
        self.hint_h = _hires_px(HINT_H_HIRES, self.scale)
        self.hint_y = chrome.height - self.hint_h
        self.board_y, self.row_heights = row_geometry(
            chrome.height, self.head_h, self.hint_y, rows, self.scale)
        self.row_y = tuple(
            self.board_y + sum(self.row_heights[:index])
            for index in range(rows))
        self.cell_h = self.row_heights[0]
        # One pixel table per plane, resolved once.  The base class builds one
        # from `board.LAYOUT` in its constructor and never rebuilds it, which
        # is the whole reason this subclass exists.
        self.plane_cells = tuple(
            tuple(self._pixels(row) for row in board.plane_layout(index))
            for index in range(len(self.planes)))
        self.cells = self.plane_cells[0]

    def _stroke(self, x1, y1, x2, y2):
        """A physically one-logical-pixel vector stroke at either mode."""
        for offset in range(self.scale):
            self.screen.line(x1, y1 + offset, x2, y2 + offset)

    def _draw_button_hints(self):
        """Chevron / accept / chevron under A, B and C, outside the model."""
        screen = self.screen
        scale = self.scale
        screen.pen = self.band
        screen.rectangle(0, self.hint_y, self.chrome.width, self.hint_h)
        screen.pen = self.grey
        screen.rectangle(0, self.hint_y, self.chrome.width, scale)
        cy = self.hint_y + self.hint_h // 2
        left, middle, right = self.chrome.softkey_x

        # `_stroke` adds `scale - 1` pixels below each segment.  Shortening the
        # raw bottom by that amount makes the final raster exactly 15 px tall
        # at HIRES, including stroke thickness, rather than a nominal 15 that
        # becomes 16 on panel.
        icon_h = _hires_px(HINT_ICON_H_HIRES, scale)
        top = cy - icon_h // 2
        bottom = top + icon_h - scale
        chevron_dx = 2 * scale
        middle += _hires_px(HINT_CHECK_SHIFT_HIRES, scale)

        screen.pen = self.white
        self._stroke(left + chevron_dx, top, left - chevron_dx, cy)
        self._stroke(left - chevron_dx, cy, left + chevron_dx, bottom)

        check_left = middle - icon_h // 2
        check_right = check_left + icon_h - 1
        check_knee = middle - scale
        self._stroke(check_left, cy + scale, check_knee, bottom)
        self._stroke(check_knee, bottom, check_right, top)

        self._stroke(right - chevron_dx, top, right + chevron_dx, cy)
        self._stroke(right + chevron_dx, cy, right - chevron_dx, bottom)

    def draw(self, app):
        if self.planes is None:
            return _BASE_VIEW.draw(self, app)
        screen = self.screen
        model = app.model
        chrome = self.chrome
        # BEFORE ANYTHING IS DRAWN, and before the seam reads `board.ROWS` for
        # its KB_CELL marker later in the same frame.
        self.board.publish(model.plane, model.upper)
        self.cells = self.plane_cells[model.plane]

        screen.pen = self.dark
        screen.clear()
        screen.font = chrome.font

        # THE HEADER BLOCK, restated from `KeyboardView.draw` rather than
        # inherited, because the base draws the board and the bar in the same
        # method.  `test_kb_sameness::ChromeTests` pins every constant it
        # shares with the base so the two cannot drift apart unnoticed.
        self._text(self.board.TITLE, self.text_x, self.pad, self.accent)
        counter = "%d/%d" % (len(model.text), model.limit)
        self._text(counter, chrome.width - self.text_x - self._width(counter),
                   self.pad, self.red if model.full() else self.grey)

        y = self.pad + self.step
        typed = model.text
        self._text(typed, self.text_x, y, self.white)
        screen.pen = self.accent
        screen.rectangle(self.text_x + self._width(typed), y, self.caret_w,
                         chrome.text_h)
        presses = "%dP" % app.presses
        self._text(presses, chrome.width - self.text_x - self._width(presses),
                   y, self.grey)

        row, column, _goal = model.caret()
        rows = model.rows
        for index in range(len(self.cells)):
            line = self.cells[index]
            cells = rows[index]
            self.cell_h = self.row_heights[index]
            y = self.row_y[index]
            for position in range(len(line)):
                x, cell_w = line[position]
                self._cell(cells[position], x, y, cell_w,
                           index == row and position == column)
        self._draw_button_hints()


# THE ADOPTION.  `kb_seam` constructs `kb_shell.KeyboardView` by name and is
# byte-frozen, so this is how the board's own view reaches the screen.
kb_shell.KeyboardView = PlaneView
