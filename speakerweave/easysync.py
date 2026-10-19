"""Easy sync: lining up the timing of every speaker by ear, two at a time.

Two speakers tick together. The click seems to come from the one that plays first,
so that one gets delay until the click sounds like one, from between the two. Then
the next pair, until every speaker has been matched. At the end the speaker with
the least delay is set to 0 and the same amount comes off all the others, so the
whole system plays as early as it can.

The pairs form a chain through the speakers in random order: each pair is one
speaker already matched and one new one. Holding back a matched speaker holds back
every speaker matched so far by the same amount, so earlier pairs stay matched.
Subwoofers come last, after the speakers that can play a click.
"""
from __future__ import annotations

import random

from .dsp import MAX_DELAY_MS
from .model import OFF, is_shaker, is_sub


def _low(spk) -> bool:
    return is_sub(spk.role) or (spk.lp_on and spk.lp_freq <= 250)


class EasySync:
    def __init__(self, project, rng=None, from_zero: bool = False):
        """from_zero: every speaker starts at 0.0 ms delay, a clean start (Cancel still puts
        the old delays back)."""
        self.project = project
        rng = rng or random.Random()
        mains, subs = [], []
        for dev in project.devices:
            if not dev.enabled:
                continue
            for spk in dev.speakers:
                if spk.role == OFF or spk.mute or is_shaker(spk.role) or spk.channel >= dev.channels:
                    continue
                (subs if _low(spk) else mains).append(spk)
        rng.shuffle(mains)
        rng.shuffle(subs)
        self.speakers = {spk.id: spk for spk in mains + subs}
        self.order = [spk.id for spk in mains + subs]
        self.low = {spk.id: _low(spk) for spk in mains + subs}
        self.start = {spk.id: spk.delay_ms for spk in mains + subs}
        if from_zero:
            for spk in mains + subs:
                spk.delay_ms = 0.0
        self.index = 0

    # ------------------------------------------------------------ where we are
    @property
    def pairs(self) -> int:
        return max(0, len(self.order) - 1)

    def pair(self) -> tuple:
        """(matched speaker id, new speaker id) of the current pair."""
        return self.order[self.index], self.order[self.index + 1]

    def matched(self) -> list:
        """Speakers matched so far: everything before the new speaker of this pair."""
        return self.order[:self.index + 1]

    def low_pair(self) -> bool:
        """A subwoofer is in this pair: both play the low thump, so they can be compared."""
        a, b = self.pair()
        return self.low[a] or self.low[b]

    def delay(self, spk_id: str) -> float:
        return self.speakers[spk_id].delay_ms

    # ------------------------------------------------------------ changing
    def hold_back(self, spk_id: str, ms: float) -> list:
        """Adds ms of delay to one speaker of the pair (less with a negative ms).
        Returns the ids whose delay changed."""
        a, b = self.pair()
        group = self.matched() if spk_id == a else [b]
        other = [b] if spk_id == a else self.matched()
        if ms < 0 and min(self.delay(i) for i in group) + ms < 0:
            # no speaker can play earlier than 0: hold back the other side instead
            group, ms = other, -ms
        for i in group:
            spk = self.speakers[i]
            spk.delay_ms = round(min(max(spk.delay_ms + ms, 0.0), MAX_DELAY_MS), 2)
        return list(group)

    def set_delay(self, spk_id: str, ms: float) -> list:
        """The delay typed in for one speaker of the pair. Only the difference to the other
        side counts, so this moves it by the difference (see hold_back). Returns the ids
        whose delay changed."""
        change = float(ms) - self.delay(spk_id)
        if abs(change) < 1e-9:
            return []
        return self.hold_back(spk_id, change)

    def next(self) -> bool:
        """On to the next pair. False when this was the last one."""
        if self.index + 1 < self.pairs:
            self.index += 1
            return True
        return False

    def back(self) -> bool:
        if self.index > 0:
            self.index -= 1
            return True
        return False

    def finish(self) -> dict:
        """The speaker with the least delay plays at 0, everything else that much
        earlier as well. Returns {speaker id: delay}."""
        if not self.order:
            return {}
        least = min(self.delay(i) for i in self.order)
        for i in self.order:
            spk = self.speakers[i]
            spk.delay_ms = round(max(spk.delay_ms - least, 0.0), 2)
        return {i: self.delay(i) for i in self.order}

    def cancel(self) -> list:
        """Every delay back as it was before Easy sync."""
        for i, ms in self.start.items():
            self.speakers[i].delay_ms = ms
        return list(self.start)
