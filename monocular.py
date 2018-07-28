from more_itertools import peekable

class Monocular:
    def __init__(self, base_array, base_key="base"):

        assert "." not in base_key

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
        # frame-key -> depth of frame from base
        self.depth = {}
        # frame-key -> frame relative to parent frame
        self.relative_frame = {}
        # frame-key -> generation gap to oldest ancestor for whom the relative frame still has no gaps
        # (i.e., each cell in the relative frame contains exactly one range)
        self.continuity_height = {}
        # frame-key -> generation gap to oldest ancestor for whom the relative frame is one-to-one
        self.singularity_height = {}
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
        self.depth[base_key] = 0
        self.continuity_height[base_key] = 0
        self.singularity_height[base_key] = 0
        if type(base_array) is type("string"):
            self.monoid[base_key] = lambda *chs: "".join(chs)

    def view(self, *scopes, prefix=None, suffix=None):

        # add prefix and suffix to each scope
        if prefix is not None:
            scopes = (prefix + "." + scope for scope in scopes)
        if suffix is not None:
            scopes = (scope + "." + suffix for scope in scopes)

        # return each scope iterable simultaniously with respect to viewpoint
        iters = tuple(map(self._view_scope, scopes))
        return iters[0] if len(iters) == 1 else zip(*iters)

    def viewt(self, *args, **kwargs):

        return tuple(self.view(*args, **kwargs))

    def _view_scope(self, scope):

        sequence = scope.split(".")
        akey = sequence[-1]
        fkey = self.fkey_of[akey]
        it = self.array[akey]
        # pass the iterable through each frame in the scope
        for viewpoint in reversed(sequence[:-1]):
            it = self._view_peekable(peekable(it), viewpoint, fkey, akey)
            fkey = viewpoint
        return it

    def _view_peekable(self, it, viewpoint, fkey, akey):

        index = 0
        singular = self._view_is_singular(viewpoint, fkey, akey)
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
            if singular and akey in self.monoid:
                final = self.monoid[akey](*visible)
            elif singular:
                assert len(visible) == 1
                final = visible[0]
            else:
                final = visible

            yield final

    def _view_is_singular(self, fr, to, akey):

        diff = self.depth[fr] - self.depth[to]
        # assert parentage direction
        if diff < 0:
            return False
        parent = fr
        for _ in range(diff):
            parent = self.parent_fkey[parent]
        # assert direct parentage
        if parent != to:
            return False

        # based on singularity
        if diff <= self.singularity_height[fr]:
            return True
        # based on continuity
        if akey in self.monoid and diff <= self.continuity_height[fr]:
            return True

        return False

    def new_frame(self, fkey, viewpoint, rel_frame):

        assert "." not in fkey
        assert fkey not in self.frame

        fixed_rel_frame = ()
        singular = True
        self.continuity_height[fkey] = 1
        for cell in rel_frame:
            fixed_cell = None
            if type(cell[0]) is type(1):
                # cell contins only one range
                fixed_cell = (cell,)
            else:
                # cell has multiple ranges; not continuous
                fixed_cell = tuple(tuple(rng) for rng in cell)
                self.continuity_height[fkey] = 0
            fixed_rel_frame += fixed_cell,
            if fixed_cell[-1][-1] - fixed_cell[0][0] != 1:
                # cell corresponds to more than one parent cell; not one-to-one
                singular = False

        self.relative_frame[fkey] = fixed_rel_frame
        self.singularity_height[fkey] = self.singularity_height[viewpoint] + 1 if singular else 0

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
        self.depth[fkey] = self.depth[viewpoint] + 1

        # determine how far continuity reaches
        if self.continuity_height[fkey] >= 1:
            # ranges relative to current ancestor
            cur_ranges = tuple(cell[0] for cell in fixed_rel_frame)
            current = fkey
            parent = viewpoint
            while parent in self.relative_frame:
                if self.continuity_height[parent] < 1:
                    # no local continuity
                    break

                par_ranges = [cell[0] for cell in self.relative_frame[parent]]
                groups = [par_ranges[lo:hi] for lo, hi in cur_ranges]

                continuous = True
                new_cur_ranges = ()
                for group in groups:
                    if all(b == c for (a, b), (c, d) in zip(group, group[1:])):
                        # all ranges merge into one
                        new_cur_ranges += (group[0][0], group[-1][-1]),
                    else:
                        # gap between ranges
                        continuous = False
                        break

                if not continuous:
                    break

                self.continuity_height[fkey] += 1
                cur_ranges = new_cur_ranges
                current = parent
                parent = self.parent_fkey[current]

    def new_frame_filter(self, fkey, scope, pred, merge=False, **kwargs):

        cells = []
        for e, item in enumerate(self._view_scope(scope)):
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

        assert "." not in akey
        assert akey not in self.array

        if type(array) is type([]):
            # ensure array is immutable
            array = tuple(array)
        self.array[akey] = array
        self.fkey_of[akey] = viewpoint
        if type(array) is type("string"):
            self.monoid[akey] = lambda *chs: "".join(chs)

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

    for ix_line, line in enumerate(m.view("lines.clauses.words.chars")):
        for ix_clause, clause in enumerate(line):
            for ix_word, word in enumerate(clause):
                print("L{}.C{}.W{} : {}".format(ix_line, ix_clause, ix_word, word))

if __name__ == "__main__":
    test()
