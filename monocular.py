from more_itertools import peekable
import re

class Monocular:
    def __init__(self, base_array, base_key="base"):

        # buffers between frame and scope
        self.frame_buffers = [".", "/"]
        self.buffer_chars = "".join(set("".join(self.frame_buffers)))
        self.illegal_chars = "".join(set(self.buffer_chars + "<>()#"))
        self.sequence_regex = re.compile("[^{}]+".format(self.buffer_chars))
        self.buffers_regex = re.compile("[{}]+".format(self.buffer_chars))

        assert self._valid_key(base_key)

        # key for both the base frame and the base array
        self.base = base_key

        # frame-key -> frame
        self.frame = {}
        # array-key -> array
        self.array = {}
        # array-key -> frame-key
        self.fkey_of = {}
        # frame-key -> frame-key which the frame was added relative to
        self.parent_fkey = {}
        # frame-key -> frame relative to parent frame
        self.relative_frame = {}
        # monoidal function for joining continuous spans of array elements
        self.monoid = {}

        self.frame[base_key] = tuple(
            (t,) for t in zip(
                range(0, len(base_array)),
                range(1, len(base_array) + 1),
            )
        )
        self.array[base_key] = base_array
        self.fkey_of[base_key] = base_key
        self.parent_fkey[base_key] = None
        if type(base_array) is type("string"):
            self.monoid[base_key] = lambda *chs: "".join(chs)

    def view(self, scope, prefix=None, suffix=None):

        # assemble pieces
        raw_pieces = iter(scope.split(" "))
        pieces = ()
        while True:
            piece = next(raw_pieces, None)
            if piece is None: break
            if "(" in piece:
                depth = 1
                paren_piece = piece,
                while depth > 0:
                    in_piece = next(raw_pieces)
                    if "(" in in_piece: depth += 1
                    if ")" in in_piece: depth -= 1
                    paren_piece += in_piece,
                piece = " ".join(paren_piece)
            pieces += piece,

        centers = ()
        for piece in pieces:
            if piece[-1] == "<":
                prefix = (piece[:-1], ".")
            elif piece[0] == ">":
                suffix = (piece[1:], ".")
            else:
                centers += piece,

        glasses = ()
        for center in centers:
            pre = None
            suf = None
            if center == "#":
                assert suffix is not None
                center = suffix[0]
            elif suffix is not None:
                buffer = suffix[1]
                for buf in self.buffers:
                    if center.endswith(buf):
                        buffer = buf
                        break
                suf = (suffix, buffer)
            if prefix is not None:
                buffer = prefix[1]
                for buf in self.buffers:
                    if center.startswith(buf):
                        buffer = buf
                        break
                pre = (prefix, buffer)
            glasses += (pre, center, suf),

        iters = ()
        for pre, glass, suf in glasses:
            if "(" in center:
                iters += self.view(glass[1:-1], prefix=pre, suffix=suf),
            else:
                if pre is not None:
                    glass = pre[0] + pre[1] + center
                if suf is not None:
                    glass = center + suf[1] + suf[0]
                iters += self.view_glass(glass),

        # return each scope iterable simultaniously with respect to viewpoint
        return iters[0] if len(iters) == 1 else zip(*iters)

    def viewt(self, *args, **kwargs):

        return tuple(self.view(*args, **kwargs))

    def view_glass(self, glass):

        sequence = self.sequence_regex.findall(glass)
        buffers = self.buffers_regex.findall(glass)
        akey = sequence[-1]
        fkey = self.fkey_of[akey]
        it = self.array[akey]
        # pass the iterable through each frame in the scope
        for e, (viewpoint, buffer) in enumerate(reversed(list(zip(sequence[:-1], buffers)))):
            kwargs = {}
            if buffer == "/" or e == 0:
                kwargs["singular"] = True
            it = self._view_peekable(peekable(it), viewpoint, fkey, akey, **kwargs)
            fkey = viewpoint
        return it

    def _view_peekable(self, it, viewpoint, fkey, akey, singular=False):

        index = 0
        for cell in self.frame[viewpoint]:
            frame = self.frame[fkey]
            visible = ()
            for lo_bound, hi_bound in cell:
                section = ()

                # find first cell that is visible
                while index < len(frame) and frame[index][-1][-1] <= lo_bound:
                    index += 1
                    next(it)

                # add all visible elements
                while index < len(frame):
                    lo, hi = frame[index][0][0], frame[index][-1][-1]
                    if lo >= hi_bound:
                        break
                    if hi > hi_bound:
                        # if element is visible in next cell, don't pop it
                        section += it.peek(),
                        break
                    section += next(it),
                    index += 1

                # only use monoid without singularity if we are at back of scope
                if akey in self.monoid and self.fkey_of[akey] == fkey:
                    visible += self.monoid[akey](*section),
                else:
                    visible += section

            # determine final output, based on monoid and/or singularity
            final = None
            if singular:
                assert len(visible) == 1
                final = visible[0]
            else:
                final = visible

            yield final

    def new_frame(self, fkey, viewpoint, rel_frame):

        assert self._valid_key(fkey)
        assert fkey not in self.frame

        fixed_rel_frame = ()
        for cell in rel_frame:
            fixed_cell = None
            if type(cell[0]) is type(1):
                # cell contins only one range
                fixed_cell = (cell,)
            else:
                # cell has multiple ranges; not continuous
                fixed_cell = tuple(tuple(rng) for rng in cell)
            fixed_rel_frame += fixed_cell,

        self.relative_frame[fkey] = fixed_rel_frame

        true_cells = ()
        for cell in fixed_rel_frame:
            # get all parent ranges that are within current cell
            vp_cells = sum((self.frame[viewpoint][lo:hi] for lo, hi in cell), ())
            vp_ranges = sum(vp_cells, ())

            true_ranges = ()
            cur_lo, cur_hi = vp_ranges[0]
            for vp_lo, vp_hi in vp_ranges[1:]:
                if cur_hi == vp_lo:
                    # merge ranges
                    cur_hi = vp_hi
                else:
                    # ranges cannot be merged; begin new current range
                    true_ranges += (cur_lo, cur_hi),
                    cur_lo, cur_hi = vp_lo, vp_hi

            # add final range; cell is completed
            true_ranges += (cur_lo, cur_hi),
            true_cells += true_ranges,

        self.frame[fkey] = true_cells
        self.parent_fkey[fkey] = viewpoint

    def new_frame_filter(self, fkey, scope, pred, merge=False, **kwargs):

        cells = []
        for e, item in enumerate(self.view(scope)):
            if pred(item):
                if merge and len(cells) >= 1 and cells[-1][-1] == e:
                    # merge adjacent ranges
                    cells[-1] = (cells[-1][0], e+1)
                else:
                    cells.append((e, e+1))

        self.new_frame(fkey, self._viewpoint_of_scope(scope), cells, **kwargs)

    def _viewpoint_of_scope(self, scope):

        seq = scope.split(".")
        return self.fkey_of[seq[0]] if len(seq) == 1 else seq[0]

    def new_array(self, akey, viewpoint, array):

        assert self._valid_key(akey)
        assert akey not in self.array

        if type(array) is type([]):
            # ensure array is immutable
            array = tuple(array)
        self.array[akey] = array
        self.fkey_of[akey] = viewpoint
        if type(array) is type("string"):
            self.monoid[akey] = lambda *chs: "".join(chs)

    def _valid_key(self, key):

        for ch in self.illegal_chars:
            if ch in key:
                return False
        return True

def test():

    # random sentences courtesy of https://randomwordgenerator.com/sentence.php
    m = Monocular("She only paints with bold colors; she does not like pastels. "
                + "I checked to make sure that he was still alive.\n"
                + "Abstraction is often one floor above you. "
                + "Please wait outside of the house.",
                  base_key="chars")

    m.new_frame_filter("words", "chars", lambda c: c.isalpha(), merge=True)
    m.new_frame_filter("tokens", "chars", lambda c: c not in " \t\n", merge=True)
    m.new_frame("sents", "chars", [(0, 60), (61, 108), (109, 150), (141, 184)])
    m.new_frame("clauses", "chars", [(0, 33), (34, 60), (61, 108), (109, 150), (141, 184)])
    m.new_frame_filter("lower_words", "words.chars", lambda w: w.lower() == w)
    m.new_frame_filter("anti_lower_words", "words.chars", lambda w: w.lower() != w)
    m.new_frame_filter("lines", "chars", lambda c: c != "\n", merge=True)

    for full_line, line in m.view("lines.chars lines.(clauses< # words >chars)"):
        print(full_line)
        for full_clause, clause in line:
            print(full_clause)
            print(words)

    for ix_line, line in enumerate(m.view("lines.clauses.words.chars")):
        for ix_clause, clause in enumerate(line):
            for ix_word, word in enumerate(clause):
                print("L{}.C{}.W{} : {}".format(ix_line, ix_clause, ix_word, word))

if __name__ == "__main__":
    test()
