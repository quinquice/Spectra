from more_itertools import peekable
import spacy

class Textocular(Monocular):
    def __init__(self, base_array, base_key="base"):

        assert type(base_array) is type("string")

        super().__init__(base_array, base_key)
