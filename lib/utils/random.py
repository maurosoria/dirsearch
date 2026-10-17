# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import math
import random
import string


class StealthWordGenerator:
    """Mutable calibration RNG/history owned by a fuzzer or standalone scanner.

    Calls within one owner are sequential. Different targets must not share an
    instance; generated words are not checkpoint state or dictionary entries.
    """

    separators = ("-", "_")
    common_directories = frozenset(("admin", "backup", "api", "test"))
    word_bank = (
        "cyberfluxion", "luminastra", "aerolithic", "peltorian",
        "chronometral", "syncorance", "neosphereic", "cryptogenoid",
        "polysystive", "megastatary", "hyperlogism", "omnitechant",
        "exovalable", "tectomatence", "quantgraphify", "dynasecize",
        "vibrmorphate", "plasmnetous", "xenotechity", "mechnomium",
        "cybermetrical", "lumiphonate", "aerologize", "peltogenable",
        "chronosystive", "syntechant", "neonomable", "cryptovalence",
        "polycorant", "megasphereic", "hypernetoid", "omnimatary",
        "exosecize", "tectgraphate", "quantmorphify", "dynastatous",
        "vibrmetrity", "plasmfluxium", "xenolithism", "mechnasian",
        "cybercorance", "luminetence", "aerosystant", "peltotechity",
        "chrononomium", "synvalism", "neocoroid", "cryptosphereary",
        "polymathate", "meganetize", "hypersecify", "omnigraphive",
        "exostatable", "tectmorphance", "quantfluxence", "dynalithant",
        "vibrmetrent", "plasmphonate", "xenologize", "mechnomify",
        "cybervalive", "lumicorable", "aerosystance", "peltotechent",
        "chrononomant", "synvality", "neocorium", "cryptosphereism",
        "polymathoid", "meganetary", "hypersecate", "omnigraphize",
        "exostatify", "tectmorphive", "quantfluxable", "dynalithance",
        "vibrmetrence", "plasmphonant", "xenologent", "mechnomtra",
        "cyberfluxian", "lumilithic", "aerometral", "peltophonous",
        "chronographity", "synstatium", "neologism", "polysphereary",
        "megatronate", "hypermatize", "omnisecify", "exocorive",
        "tectnetable", "quantvalance", "dynanomence", "vibrtechant",
        "plasmsysent", "xenonasal", "mechnomous", "cybermetrity",
        "lumiphonary", "aerographize", "peltostative", "chronologable",
        "synmorphance", "neogenent", "cryptosphereant", "polytronent",
        "megamatous", "hypersystic", "omnisecian", "exocoral",
        "tectnetous", "quantvality", "dynanomium", "vibrtechism",
        "plasmsysoid", "xenonastive", "mechnomable", "cyberfluxance",
        "lumilithical", "aerometrous", "peltophonium", "chronography",
        "synstatize", "neologify", "cryptogenive", "polyspherable",
        "megatronance", "hypermatence", "omnisecant", "exocorent",
        "tectnetant", "quantvalent", "dynanomity", "vibrtechium",
        "plasmsysism", "xenonasoid", "mechnomary", "cyberfluxate",
        "lumilithize", "aerometrify", "peltophonic", "chronographal",
        "synstatous", "neologity", "cryptogenium", "polysphereism",
        "megatronoid", "hypermatary", "omnisecate", "exocortra",
        "tectnetion", "quantvalian", "dynanomic", "vibrtechal",
        "plasmsysous", "xenonasity", "cyberfluxize", "lumilithify",
        "aerometrive", "peltophonable", "chronographance",
        "synstatence", "neologant", "cryptogenent", "polyspherentra",
        "megatronion", "hypermatian", "omnisecic",
    )

    _onsets = (
        "l", "m", "n", "p", "r", "s", "t", "v", "c",
        "cl", "cr", "pl", "pr", "st", "tr", "vr",
    )
    _nuclei = ("a", "e", "i", "o", "u", "ae", "ai", "ia", "io", "ou")
    _codas = ("l", "m", "n", "r", "s", "t", "v", "c", "nt", "rn", "st")
    _suffixes = (
        "al", "an", "ar", "en", "ic", "in", "or", "um",
        "ian", "ion", "ium", "ora", "ory",
    )

    def __init__(
        self,
        seed: int | str | bytes | bytearray | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if seed is not None and rng is not None:
            raise ValueError("seed and rng are mutually exclusive")

        self._rng = rng or random.Random(seed)
        self._seen = set()
        self._short_word_bank = tuple(word for word in self.word_bank if len(word) <= 10)

    def generate(self, omit: str | Iterable[str] | None = None) -> str:
        omitted = self._normalize_omit(omit)

        for _ in range(1000):
            word_count = self._rng.randint(2, 3)
            separator = self._rng.choice(self.separators)
            candidate = self._candidate_from_bank(word_count, separator)

            if not self._is_valid(candidate, omitted):
                continue

            self._seen.add(candidate)
            return candidate

        raise RuntimeError("Unable to generate a stealth calibration word")

    def _candidate_from_bank(self, word_count: int, separator: str) -> str:
        word_bank = self._short_word_bank if word_count == 3 else self.word_bank
        try:
            words = self._rng.sample(word_bank, word_count)
        except ValueError:
            words = [
                self._pseudo_word(*(7, 13) if word_count == 2 else (5, 9))
                for _ in range(word_count)
            ]

        return separator.join(words)

    def _pseudo_word(self, min_length: int, max_length: int) -> str:
        for _ in range(100):
            pieces = [
                self._rng.choice(self._onsets),
                self._rng.choice(self._nuclei),
                self._rng.choice(self._codas),
            ]

            if self._rng.random() < 0.75:
                pieces.extend(
                    (
                        self._rng.choice(self._onsets),
                        self._rng.choice(self._nuclei),
                    )
                )

            pieces.append(self._rng.choice(self._suffixes))
            word = "".join(pieces)
            if min_length <= len(word) <= max_length and word not in self.common_directories:
                return word

        return "loravian"

    def _is_valid(self, candidate: str, omitted: set[str]) -> bool:
        if candidate in self._seen or candidate in omitted:
            return False
        if not 15 <= len(candidate) <= 30:
            return False
        if candidate[0] in self.separators or candidate[-1] in self.separators:
            return False
        if "--" in candidate or "__" in candidate or "-_" in candidate or "_-" in candidate:
            return False
        if any(
            not ("a" <= character <= "z" or character in self.separators)
            for character in candidate
        ):
            return False
        if self._shannon_entropy(candidate) >= 3.95:
            return False

        words = candidate.replace("_", "-").split("-")
        return (
            len(words) in (2, 3)
            and all(word and word not in self.common_directories for word in words)
        )

    @staticmethod
    def _normalize_omit(omit: str | Iterable[str] | None) -> set[str]:
        if omit is None:
            return set()
        if isinstance(omit, str):
            return {omit}
        return set(omit)

    @staticmethod
    def _shannon_entropy(value: str) -> float:
        length = len(value)
        return -sum(
            (count / length) * math.log2(count / length)
            for count in Counter(value).values()
        )


def rand_string(n, omit=None):
    seq = string.ascii_lowercase + string.ascii_uppercase + string.digits

    if omit:
        seq = list(set(seq) - set(omit))

    return "".join(random.choice(seq) for _ in range(n))
