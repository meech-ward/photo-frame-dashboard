"""The grid keyboard: a caret over a ragged board of cells.

THE LAW OF THIS FILE: it imports NOTHING, the same rule `identity_catalogue`
lives under.  There is no clock here, no file, no random source, and above all
no Badgeware global -- every entry point takes its input as a plain signed
integer, so the whole keyboard can be driven from CPython.

WHY THAT SENTENCE IS THE POINT OF THE MODULE, not a nicety.  `shared/ui.py`'s
`Axis.delta()` reads `badge.held(...)` inside itself, so an editor built on
`ui.Axis` cannot be stepped off the device AT ALL -- it imports cleanly, passes
any test that only imports it, and raises `NameError` on the first real key.
The shipped grid keyboard does exactly that (`namebadge/badge/namebadge/
keyboard_grid.py:35-36` constructs two `ui.Axis` instances in `__init__`), which
is why its press counts had to be re-derived by a separate host script that
models the navigation a second time -- and a second model is a second thing that
can be wrong.  Here `identity/host/press_counts.py` drives THIS class, so the
number in the README and the code on the badge cannot disagree.

The controller owns the `ui.Repeat` pair and hands the result over:

    step = repeat_down.step(held_down, now) - repeat_up.step(held_up, now)
    grid.move_row(step)

`ui.Repeat.step(is_held, now)` already takes its input as arguments and is pure;
it is only the `Axis` wrapper around it that is not.

WHAT THIS BOARD CHANGES ABOUT THE SHIPPED ONE, and why.

1.  THE GOAL COLUMN.  `keyboard_grid.handle` clamps with
    `self.column = limit - 1` and then FORGETS the column it clamped, so from
    column 7 a press of UP onto the three-cell action row and a press of DOWN
    back lands you on column 2.  That fails B3's ten-second test -- "press UP
    once, then DOWN once; you are byte-identically where you started" -- which
    is also the test that decides whether a screen is browsing at all.  Here the
    caret remembers the column it WANTED (`self.goal`); a short row clamps what
    is drawn without destroying it, so every vertical move is invertible.  Any
    text editor's "goal column" is the same idea and for the same reason.

2.  SEVEN COLUMNS, NOT TEN.  Both axes wrap, so the board is a torus and the
    cost of a letter is the two cyclic distances.  Ten columns costs up to five
    horizontal steps; seven costs up to three, at the price of one more row.
    Over 1000 held-out generated names, the same construction at seven columns
    measures 47.88 presses and at ten measures 51.79 -- and seven is the best of
    every width from four to thirteen (`press_counts.py --ablate`).

3.  THE CARET OPENS IN THE MIDDLE OF THE LETTER BLOCK, not on `A`.  On a torus
    no cell is a corner, so the opening cell is a free parameter, and the middle
    one is nearest to a random first letter: 47.88 against 48.57 on the same
    names, and 20.12 against 21.04 on short first names.  It has a second,
    unmeasured argument: a caret at `A` looks like the end of the board and
    hides the fact that every edge wraps, while a caret in the middle shows all
    four directions live.  The bill for it is names starting near `A`: `ADA`
    costs 16 presses here against the shipped grid's 12, which is the
    phrase-flip `namebadge/README.md` already warns about, made concrete.

4.  BACK IS A CELL.  The shipped grid's only exits are DONE and the HOME reset,
    so there is no labelled route out that commits nothing and it fails I2 as
    written.  A grid needs A and C for its horizontal axis, so the way out
    cannot live on the bar; it lives on the board, sorted first, where the wrap
    from the top row lands (B7's wrong-way-first test).

WHAT IS DELIBERATELY THE SAME.  The bank is `namebadge`'s, glyph for glyph, so
the two boards can be compared without an argument about what they can type;
and a vertical move still lands on `min(goal, width - 1)` rather than on the
spatially nearest cell.  The nearest-cell rule is truer to I1 -- DOWN would then
never also move you sideways -- but it measured 0.86 presses per name worse,
because clamping is what makes DONE, the last cell of the last row, the default
landing place for a caret that is anywhere right of the second column.  Both
rules are implemented in the host counter so the trade can be re-measured
rather than re-argued.
"""


# --------------------------------------------------------------------------
# cells
# --------------------------------------------------------------------------

# A cell holding one character types that character.  These four hold verbs
# instead, and are the only cells `press` treats specially.
SPACE = "SPACE"
BACK = "BACK"
DEL = "DEL"
DONE = "DONE"

# Sorted by how much they commit, left to right, which is the same order the
# softkey bar puts A, B and C in.  DONE last is not only tidiness: a vertical
# move clamps to `width - 1`, so the last cell of this row is where a caret
# anywhere right of column 1 lands, and after the last letter of a name DONE is
# what the wearer wants.  BACK first is B7: lists wrap, so the first UP from the
# top row of the board lands here, and the cell it lands on must be harmless.
ACTIONS = (BACK, DEL, DONE)

# The board.  Every glyph row is seven cells wide and the bank simply fills in
# reading order, so the only short row in each group is its last -- which is a
# rule the wearer can see rather than a shape someone chose.
#
# The bank is `namebadge.keyboard_grid.ROWS` glyph for glyph: 26 letters, 10
# digits and `- . & '`, plus SPACE.  Nothing was dropped to make the board
# smaller, because a keyboard that wins on presses by refusing to type
# "O'BRIEN" has not won anything.
ROWS = (
    ("A", "B", "C", "D", "E", "F", "G"),
    ("H", "I", "J", "K", "L", "M", "N"),
    ("O", "P", "Q", "R", "S", "T", "U"),
    ("V", "W", "X", "Y", "Z", SPACE),
    ("0", "1", "2", "3", "4", "5", "6"),
    ("7", "8", "9", "-", ".", "&", "'"),
    ACTIONS,
)

# The middle cell of the letter block: the middle row of rows 0-3 and the middle
# column of seven.  `K`.  See note 3 in the module docstring for what it buys
# and who pays for it.
OPENS_AT = (1, 3)

# The bar this screen needs.  A GRID KEYBOARD HAS A HORIZONTAL AXIS, so by I1
# and B2 A is left and C is right, and the labelled way out moves onto the
# board.  That is a real disagreement with `identity_model.softkeys(TEXT)`,
# which M1 pinned to ("BACK", "TYPE", "DONE") before any keyboard existed;
# `test_identity_keyboard` states the disagreement and the exact change the
# controller milestone owes.  Two direction keys cannot address a two-
# dimensional board, so with A and C spent on BACK and DONE the "grid" collapses
# onto one axis -- which is the shape `namebadge` ships as `badge_dial` and
# measured at 99 presses for "SAM MEECH" against the grid's 37.
BAR = ("LEFT", "TYPE", "RIGHT")

# "SPACE" measures 30 px at font.sins and the widest glyph cell on a 160 px
# canvas is 22 px, so the cell says SPC.  Same arithmetic as SMOOTH -> FLOW in
# `identity_model.HOME_MOTION_LABELS`: the stored token is the durable thing and
# the label is whatever fits.  The three action cells are a third of the width
# each and need no abbreviation.
LABELS = {SPACE: "SPC"}

# What `press` did, for the controller to act on.  Strings rather than an enum
# because MicroPython has no enum and a string prints itself in a traceback.
TYPED = "typed"
DELETED = "deleted"
REFUSED = "refused"
COMMITTED = "committed"
ABANDONED = "abandoned"

# `identity_model.NAME_MAX`, restated rather than imported: importing it would
# make the keyboard refuse to load without the schema, and the caller passes the
# real cap anyway (`line2` is longer than a name).  A test asserts they agree.
DEFAULT_LIMIT = 12


def label(cell):
    """What the view draws in a cell.  Never longer than the cell."""
    return LABELS[cell] if cell in LABELS else cell


def glyph(cell):
    """The character a cell types, or "" if it is a verb."""
    if cell == SPACE:
        return " "
    if cell in ACTIONS:
        return ""
    return cell


def bank(rows=ROWS):
    """Every character the board can type, in reading order.

    Derived from the board rather than written down beside it: a bank and a
    board that are two lists are two lists that can disagree, and the way that
    bug presents is a glyph nobody can reach.
    """
    out = ""
    for row in rows:
        for cell in row:
            out += glyph(cell)
    return out


# --------------------------------------------------------------------------
# the caret
# --------------------------------------------------------------------------

class GridModel:
    """A caret over `rows`, and the text it has typed.

    Nothing here reads a clock, a file, or a Badgeware global, and nothing here
    draws.  `move_row` and `move_column` take a SIGNED STEP COUNT rather than a
    direction, because that is what `ui.Repeat.step` returns: a held key at the
    top of the ramp yields more than one step in a frame, and a model that only
    understood +-1 would silently drop the rest.
    """

    def __init__(self, text="", limit=DEFAULT_LIMIT, rows=ROWS,
                 opens_at=OPENS_AT):
        self.rows = rows
        # A cap below 1 would make the board unable to type anything and every
        # press a REFUSED, which is a screen the wearer cannot leave except
        # through BACK.  Clamped rather than trusted: the caller reads it from a
        # repaired state, but this class is also driven by the host counter and
        # by tests.
        self.limit = limit if limit > 0 else 1
        self.text = text[:self.limit] if isinstance(text, str) else ""
        row, column = opens_at
        self.row = row % len(self.rows)
        self.column = column % self.width(self.row)
        # The column the caret is REACHING for, which survives a short row.
        # `self.column` is what is drawn; this is what the next vertical move
        # aims at.  Keeping both is what makes UP-then-DOWN an identity.
        self.goal = self.column

    # -- the board ---------------------------------------------------------

    def width(self, row=None):
        return len(self.rows[self.row if row is None else row])

    def cell(self):
        """The token under the caret."""
        return self.rows[self.row][self.column]

    def find(self, cell):
        """Where a token is, or None.  The first match wins, so a board that
        repeats a token addresses only its first copy."""
        for row in range(len(self.rows)):
            line = self.rows[row]
            for column in range(len(line)):
                if line[column] == cell:
                    return (row, column)
        return None

    def caret(self):
        """(row, column, goal) -- the whole of the caret's state.

        The goal is part of it on purpose.  A route planner that ignored it
        would think two carets drawn on the same cell were interchangeable, and
        they are not: the next vertical move goes somewhere different.
        """
        return (self.row, self.column, self.goal)

    def restore(self, caret):
        """Put the caret back, goal and all.

        Here for the route search in `identity/host/press_counts.py`, which
        walks the caret's state graph and has to be able to back up.  The app
        never calls it: a controller only ever moves the caret one step at a
        time, and a screen that could teleport its own highlight is a screen
        whose position the wearer cannot keep track of.
        """
        row, column, goal = caret
        self.row, self.column, self.goal = row, column, goal

    # -- movement ----------------------------------------------------------

    def move_row(self, step):
        """UP is negative, DOWN is positive.  Wraps at both ends.

        The column is not carried across literally: a row shorter than the goal
        clamps what is drawn to its last cell.  The goal itself is untouched, so
        stepping back off a short row returns the caret to where it was.
        """
        if not step:
            return
        self.row = (self.row + step) % len(self.rows)
        width = self.width()
        self.column = self.goal if self.goal < width else width - 1

    def move_column(self, step):
        """A is negative, C is positive.  Wraps at both ends of the row.

        Wrapping over the CURRENT row's width, not the board's widest, so the
        four cells of a short row are four steps around and not seven with
        three of them invisible.
        """
        if not step:
            return
        self.column = (self.column + step) % self.width()
        self.goal = self.column

    # -- the primary action ------------------------------------------------

    def press(self):
        """B.  Returns one of the five outcome constants; never raises.

        Every branch returns a word rather than a bool because the caller has
        five different jobs: redraw, redraw and flash, pop the screen, commit
        and pop, or nothing.  A bool would collapse REFUSED into DELETED, and
        REFUSED is the one the wearer needs told about -- a full field that
        silently eats presses is how a name ends up truncated without anyone
        noticing.
        """
        cell = self.cell()
        if cell == DONE:
            return COMMITTED
        if cell == BACK:
            return ABANDONED
        if cell == DEL:
            if not self.text:
                return REFUSED
            self.text = self.text[:-1]
            return DELETED
        if len(self.text) >= self.limit:
            return REFUSED
        self.text += glyph(cell)
        return TYPED

    def full(self):
        return len(self.text) >= self.limit
