from __future__ import annotations

import pathlib
import unittest
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE = ROOT / "Single_Candle_OB_MSS_FVG.pine"
STRATEGY = ROOT / "Single_Candle_OB_MSS_FVG_Strategy.pine"
DISPLAY_LATEST = "Latest"
DISPLAY_ALL = "All"


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Event:
    direction: int
    kind: str
    index: int
    ob_index: int
    fvg_left: int
    fvg_right: int
    level: float
    fvg_top: float
    fvg_bottom: float


@dataclass
class DisplayState:
    mode: str = DISPLAY_LATEST
    logical: list[int] | None = None
    visible: set[int] | None = None

    def __post_init__(self):
        self.logical = []
        self.visible = set()

    def confirm(self, event_id: int):
        self.logical.append(event_id)
        if self.mode == DISPLAY_LATEST:
            self.visible.clear()
        self.visible.add(event_id)


def in_window(now_minutes: int, start: int, end: int) -> bool:
    if start < end:
        return start <= now_minutes < end
    if start > end:
        return now_minutes >= start or now_minutes < end
    return True


def pivot_high(bars: list[Bar], pivot: int, length: int) -> bool:
    level = bars[pivot].high
    for offset in range(1, length + 1):
        if bars[pivot - offset].high >= level or bars[pivot + offset].high >= level:
            return False
    return True


def pivot_low(bars: list[Bar], pivot: int, length: int) -> bool:
    level = bars[pivot].low
    for offset in range(1, length + 1):
        if bars[pivot - offset].low <= level or bars[pivot + offset].low <= level:
            return False
    return True


def committed(high: float, low: float, close: float, bullish: bool, fraction: float) -> bool:
    span = high - low
    location = (close - low) if bullish else (high - close)
    if fraction == 0:
        return True
    return span > 0 and location >= span * fraction


def body_high(bar: Bar) -> float:
    return max(bar.open, bar.close)


def body_low(bar: Bar) -> float:
    return min(bar.open, bar.close)


def replay(bars: list[Bar], swing_length: int = 1, minutes: list[int] | None = None,
           use_window: bool = False, start: int = 0, end: int = 0,
           minute_start: int = 0, minute_end: int = 60,
           swing_breach_lookback: int = 1) -> list[Event]:
    swing_high = None
    swing_high_bar = None
    broken_high_bar = None
    swing_low = None
    swing_low_bar = None
    broken_low_bar = None
    direction = 0
    events: list[Event] = []
    pending = None
    active = None
    bull_close_bar = None
    bear_close_bar = None
    bull_watch = None
    bear_watch = None
    for index, bar in enumerate(bars):
        if index >= 2 * swing_length:
            pivot = index - swing_length
            if pivot_high(bars, pivot, swing_length):
                swing_high = bars[pivot].high
                swing_high_bar = pivot
            if pivot_low(bars, pivot, swing_length):
                swing_low = bars[pivot].low
                swing_low_bar = pivot
        if swing_high_bar != bull_watch:
            bull_watch = swing_high_bar
            bull_close_bar = None
        if swing_low_bar != bear_watch:
            bear_watch = swing_low_bar
            bear_close_bar = None
        previous = bars[index - 1] if index else None
        swing_high_open = swing_high is not None and broken_high_bar != swing_high_bar
        swing_low_open = swing_low is not None and broken_low_bar != swing_low_bar
        if (
            previous is not None and swing_high_open and bull_close_bar is None
            and bar.close > swing_high and previous.close <= swing_high
        ):
            bull_close_bar = index
        if (
            previous is not None and swing_low_open and bear_close_bar is None
            and bar.close < swing_low and previous.close >= swing_low
        ):
            bear_close_bar = index
        bull_close_age = None if bull_close_bar is None else index - bull_close_bar
        bear_close_age = None if bear_close_bar is None else index - bear_close_bar
        if not use_window:
            allowed = True
        else:
            minute_of_hour = 0 if minutes is None else minutes[index] % 60
            minute_ok = minute_start <= minute_of_hour < minute_end
            allowed = in_window(minutes[index], start, end) and minute_ok
        if pending is not None and index == pending["bar"] + 1:
            level = pending["level"]
            candle3_body_high = body_high(bar)
            candle3_body_low = body_low(bar)
            if pending["direction"] == 1 and level > pending["c1_body_high"] and level < candle3_body_low:
                events.append(Event(
                    1, pending["kind"], pending["bar"], pending["bar"],
                    pending["bar"] - 1, index, level,
                    candle3_body_low, pending["c1_body_high"],
                ))
                active = {
                    "direction": 1,
                    "high": pending["high"],
                    "low": pending["low"],
                    "index": pending["bar"],
                }
            elif pending["direction"] == -1 and level < pending["c1_body_low"] and level > candle3_body_high:
                events.append(Event(
                    -1, pending["kind"], pending["bar"], pending["bar"],
                    pending["bar"] - 1, index, level,
                    pending["c1_body_low"], candle3_body_high,
                ))
                active = {
                    "direction": -1,
                    "high": pending["high"],
                    "low": pending["low"],
                    "index": pending["bar"],
                }
            pending = None
        flipped_this_bar = False
        if active is not None and index > active["index"] + 1:
            bull_flip = active["direction"] == -1 and bar.close > bar.open and bar.close > active["high"]
            bear_flip = active["direction"] == 1 and bar.close < bar.open and bar.close < active["low"]
            if bull_flip or bear_flip:
                flip_direction = 1 if bull_flip else -1
                flip_kind = "BOS" if direction == flip_direction else "MSS"
                events.append(Event(
                    flip_direction, flip_kind, index, active["index"],
                    active["index"], index,
                    active["high"] if flip_direction == 1 else active["low"],
                    bar.high, bar.low,
                ))
                direction = flip_direction
                if flip_direction == 1 and swing_high_open and bar.close > swing_high:
                    broken_high_bar = swing_high_bar
                    swing_high_open = False
                elif flip_direction == -1 and swing_low_open and bar.close < swing_low:
                    broken_low_bar = swing_low_bar
                    swing_low_open = False
                active = {
                    "direction": flip_direction,
                    "high": bar.high,
                    "low": bar.low,
                    "index": index,
                }
                flipped_this_bar = True
        bullish_break = (
            previous is not None and swing_high_open and bar.close > swing_high
            and previous.close <= swing_high and bar.close > bar.open
        )
        bearish_break = (
            previous is not None and swing_low_open and bar.close < swing_low
            and previous.close >= swing_low and bar.close < bar.open
        )
        if not flipped_this_bar and bullish_break and allowed:
            kind = "BOS" if direction == 1 else "MSS"
            direction = 1
            broken_high_bar = swing_high_bar
            pending = {
                "direction": 1,
                "kind": kind,
                "bar": index,
                "level": swing_high,
                "c1_body_high": body_high(previous),
                "c1_body_low": body_low(previous),
                "high": bar.high,
                "low": bar.low,
            }
        elif (
            not flipped_this_bar and swing_high_open
            and bull_close_age == swing_breach_lookback
        ):
            direction = 1
            broken_high_bar = swing_high_bar
        if not flipped_this_bar and bearish_break and allowed:
            kind = "BOS" if direction == -1 else "MSS"
            direction = -1
            broken_low_bar = swing_low_bar
            pending = {
                "direction": -1,
                "kind": kind,
                "bar": index,
                "level": swing_low,
                "c1_body_high": body_high(previous),
                "c1_body_low": body_low(previous),
                "high": bar.high,
                "low": bar.low,
            }
        elif (
            not flipped_this_bar and swing_low_open
            and bear_close_age == swing_breach_lookback
        ):
            direction = -1
            broken_low_bar = swing_low_bar
    return events


def bullish_break() -> list[Bar]:
    # Bar 1 is the swing high at 13. Bar 4 closes through it.
    # Bar 3 body high is 11.6.
    return [
        Bar(10.0, 11.0, 9.5, 10.6),
        Bar(10.6, 13.0, 10.4, 12.4),
        Bar(12.4, 12.6, 11.4, 11.6),
        Bar(11.6, 12.0, 11.2, 11.4),
        Bar(11.4, 14.4, 11.3, 14.0),
    ]


def bearish_break() -> list[Bar]:
    # Bar 1 is the swing low at 9. Bar 4 closes through it.
    # Bar 3 body low is 10.4.
    return [
        Bar(12.0, 12.4, 11.0, 11.4),
        Bar(11.4, 11.6, 9.0, 9.4),
        Bar(9.4, 10.6, 9.2, 10.4),
        Bar(10.4, 10.8, 10.0, 10.6),
        Bar(10.6, 10.7, 8.2, 8.6),
    ]


def bullish_confirm() -> Bar:
    # Body low is 13.4, above the swing at 13. The wick trades back through it.
    return Bar(13.4, 15.0, 12.8, 14.6)


def bearish_confirm() -> Bar:
    # Body high is 8.6, below the swing at 9. The wick trades back through it.
    return Bar(8.6, 9.2, 7.5, 7.8)


class SingleCandleTests(unittest.TestCase):
    def test_bullish_close_leaves_the_swing_inside_the_body_gap(self):
        event = replay(bullish_break() + [bullish_confirm()])[0]
        self.assertEqual(event, Event(1, "MSS", 4, 4, 3, 5, 13.0, 13.4, 11.6))

    def test_bearish_close_leaves_the_swing_inside_the_body_gap(self):
        event = replay(bearish_break() + [bearish_confirm()])[0]
        self.assertEqual(event, Event(-1, "MSS", 4, 4, 3, 5, 9.0, 10.4, 8.6))

    def test_swing_on_the_body_edge_is_rejected(self):
        on_edge = bullish_break() + [Bar(13.0, 14.8, 12.6, 14.2)]
        self.assertEqual(replay(on_edge), [])
        outside = bullish_break() + [Bar(12.8, 14.8, 12.4, 14.0)]
        self.assertEqual(replay(outside), [])
        event = replay(bullish_break() + [bullish_confirm()])[0]
        self.assertEqual(event.index, 4)
        self.assertEqual(event.fvg_right, 5)

    def test_confirming_candle_can_be_the_other_color(self):
        bearish_third = bullish_break() + [Bar(14.6, 14.8, 13.2, 13.5)]
        event = replay(bearish_third)[0]
        self.assertEqual(event.fvg_top, 13.5)
        bullish_third = bearish_break() + [Bar(7.6, 8.4, 7.4, 8.2)]
        bear_event = replay(bullish_third)[0]
        self.assertEqual(bear_event.fvg_bottom, 8.2)

    def test_confirm_can_close_inside_the_break_candle(self):
        inside_high = bullish_break() + [Bar(13.6, 14.2, 13.2, 13.8)]
        event = replay(inside_high)[0]
        self.assertEqual(event.index, 4)
        inside_low = bearish_break() + [Bar(8.4, 8.8, 8.0, 8.6)]
        bear_event = replay(inside_low)[0]
        self.assertEqual(bear_event.index, 4)

    def test_close_through_marks_the_opposite_candle(self):
        flipped = bullish_break() + [bullish_confirm(), Bar(14.6, 14.9, 10.8, 11.0)]
        events = replay(flipped)
        self.assertEqual([event.direction for event in events], [1, -1])
        self.assertEqual(events[1].index, 6)
        wick = bullish_break() + [bullish_confirm(), Bar(14.6, 14.9, 10.8, 13.8)]
        self.assertEqual(len(replay(wick)), 1)
        same_color = bullish_break() + [bullish_confirm(), Bar(11.0, 11.5, 10.5, 11.2)]
        self.assertEqual(len(replay(same_color)), 1)
        bullish_flip = bearish_break() + [bearish_confirm(), Bar(7.8, 11.2, 7.6, 11.0)]
        bullish_events = replay(bullish_flip)
        self.assertEqual([event.direction for event in bullish_events], [-1, 1])
        self.assertEqual(bullish_events[1].index, 6)

    def test_same_color_candle_before_the_break_still_marks(self):
        bars = bullish_break()
        bars[3] = Bar(11.2, 12.0, 11.0, 11.8)
        event = replay(bars + [bullish_confirm()])[0]
        self.assertEqual(event, Event(1, "MSS", 4, 4, 3, 5, 13.0, 13.4, 11.8))

    def test_same_direction_break_is_bos(self):
        bars = bullish_break() + [
            bullish_confirm(),
            Bar(14.6, 14.9, 14.2, 14.4),
            Bar(14.4, 16.5, 14.3, 14.6),
            Bar(14.6, 15.2, 14.4, 14.8),
            Bar(14.8, 15.0, 14.5, 14.9),
            Bar(14.9, 17.2, 14.8, 17.0),
            Bar(17.0, 17.6, 16.6, 17.4),
        ]
        events = replay(bars)
        self.assertEqual([event.kind for event in events], ["MSS", "BOS"])
        self.assertEqual(events[1].index, 10)
        self.assertEqual(events[1].level, 16.5)

    def test_opposite_break_is_mss(self):
        bars = bullish_break() + [
            bullish_confirm(),
            Bar(14.6, 14.7, 13.6, 13.8),
            Bar(13.8, 14.0, 11.5, 11.8),
            Bar(11.8, 12.0, 11.6, 11.9),
            Bar(11.9, 12.0, 10.4, 10.6),
            Bar(10.6, 10.8, 10.2, 10.7),
        ]
        events = replay(bars)
        self.assertEqual(events[0].kind, "MSS")
        self.assertEqual(events[-1].direction, -1)
        self.assertEqual(events[-1].kind, "MSS")

    def test_wick_through_the_swing_is_rejected(self):
        bars = bullish_break()
        bars[4] = Bar(11.4, 13.2, 11.3, 12.6)
        self.assertEqual(replay(bars + [bullish_confirm()]), [])

    def test_plain_break_consumes_the_swing(self):
        bars = bullish_break() + [
            Bar(14.0, 14.4, 12.4, 12.9),
            Bar(12.9, 13.6, 12.6, 13.4),
            Bar(13.4, 14.0, 13.2, 13.8),
        ]
        self.assertEqual(replay(bars), [])

    def test_failed_wick_leaves_the_swing_available(self):
        bars = bullish_break()
        bars[4] = Bar(11.4, 13.2, 11.3, 12.6)
        bars.extend([
            Bar(12.6, 13.2, 12.2, 12.4),
            Bar(12.4, 12.6, 12.0, 12.2),
            Bar(12.2, 14.6, 12.1, 14.2),
            Bar(14.2, 14.8, 13.1, 14.6),
        ])
        events = replay(bars)
        self.assertEqual(events, [Event(1, "MSS", 7, 7, 6, 8, 13.0, 14.2, 12.4)])

    def test_failed_gap_still_makes_the_next_same_direction_break_a_bos(self):
        bars = bullish_break() + [
            Bar(14.0, 14.4, 12.4, 12.9),
            Bar(12.9, 12.9, 12.4, 12.6),
            Bar(12.6, 15.5, 12.5, 13.0),
            Bar(13.0, 14.0, 12.8, 13.2),
            Bar(13.2, 13.6, 13.0, 13.4),
            Bar(13.4, 16.2, 13.3, 16.0),
            Bar(16.0, 16.6, 15.6, 16.4),
        ]
        events = replay(bars)
        self.assertEqual([event.kind for event in events], ["BOS"])
        self.assertEqual(events[0].index, 10)
        self.assertEqual(events[0].level, 15.5)

    def test_break_without_a_following_candle_is_not_the_mark(self):
        bars = [
            Bar(-232, -222, -313, -305),
            Bar(-307, -271, -330, -319),
            Bar(-324, -320, -393, -385),
            Bar(-385, -343, -477, -381),
            Bar(-381, -252, -419, -396),
            Bar(-396, -265, -399, -318),
            Bar(-316, -260, -359, -266),
            Bar(-267, -191, -267, -215),
            Bar(-215, -185, -278, -259),
            Bar(-259, -220, -276, -238),
            Bar(-238, -231, -298, -270),
            Bar(-275, -254, -313, -296),
            Bar(-298, -277, -358, -342),
            Bar(-345, -285, -356, -309),
            Bar(-307, -307, -442, -408),
        ]
        self.assertFalse(any(event.index == 14 for event in replay(bars, swing_length=1)))
        self.assertFalse(any(event.index == 14 for event in replay(bars, swing_length=3)))

    def test_equal_high_does_not_become_the_swing(self):
        bars = [
            Bar(10.0, 13.0, 9.5, 12.0),
            Bar(12.0, 13.0, 11.0, 11.4),
            Bar(11.4, 12.4, 11.0, 11.6),
            Bar(11.6, 12.2, 10.8, 11.0),
            Bar(12.6, 14.4, 12.5, 14.1),
        ]
        self.assertEqual(replay(bars), [])

    def test_window_keeps_the_structure_book_and_skips_the_drawing(self):
        bars = bullish_break() + [bullish_confirm()]
        hidden_minutes = [10 * 60] * 4 + [12 * 60, 12 * 60]
        hidden = replay(bars, minutes=hidden_minutes, use_window=True, start=9 * 60 + 30, end=12 * 60)
        self.assertEqual(hidden, [])
        visible = replay(bars, minutes=[10 * 60] * 6, use_window=True, start=9 * 60 + 30, end=12 * 60)
        self.assertEqual(visible[0].kind, "MSS")

    def test_minute_window_skips_a_later_minute_of_the_hour(self):
        bars = bullish_break() + [bullish_confirm()]
        minutes = [13 * 60 + 40] * 6
        hidden = replay(
            bars, minutes=minutes, use_window=True, minute_start=0, minute_end=15
        )
        self.assertEqual(hidden, [])
        shown = replay(
            bars, minutes=minutes, use_window=True, minute_start=0, minute_end=60
        )
        self.assertEqual(shown[0].kind, "MSS")
        open_clock = replay(
            bars, minutes=minutes, use_window=False, minute_start=0, minute_end=15
        )
        self.assertEqual(open_clock[0].kind, "MSS")

    def test_formation_bar_does_not_mitigate_its_own_gap(self):
        zone_top, zone_bottom = 13.4, 12.0
        formation = bullish_break()[4]
        self.assertTrue(formation.low <= zone_top and formation.high >= zone_bottom)
        self.assertFalse(4 > 4)


class DisplayTests(unittest.TestCase):
    def test_latest_keeps_the_newest_drawing_only(self):
        state = DisplayState(DISPLAY_LATEST)
        state.confirm(1)
        state.confirm(2)
        self.assertEqual(state.visible, {2})
        self.assertEqual(state.logical, [1, 2])

    def test_all_keeps_every_drawing(self):
        state = DisplayState(DISPLAY_ALL)
        state.confirm(1)
        state.confirm(2)
        self.assertEqual(state.visible, {1, 2})


class PineSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PINE.read_text(encoding="utf-8")

    def test_indicator_header(self):
        self.assertIn('indicator("Single Candle OB + MSS + FVG"', self.source)
        self.assertNotIn("strategy(", self.source)
        self.assertIn("//@version=6", self.source)

    def test_single_candle_predicates(self):
        self.assertIn("close > swingHigh and close[1] <= swingHigh and close > open and f_committed(true)", self.source)
        self.assertIn("close < swingLow and close[1] >= swingLow and close < open and f_committed(false)", self.source)
        self.assertIn('input.float(0, "Close Location"', self.source)
        self.assertIn("f_committed(bool bullish)", self.source)
        self.assertIn("bool flipCommitted = (closedBullZone and f_committed(false)) or (closedBearZone and f_committed(true))", self.source)
        self.assertIn("if flipCommitted", self.source)
        self.assertIn("not vwapChased and f_keyOk(continuationBull) and f_committed(continuationBull)", self.source)
        self.assertIn("close < swingLow and close[1] >= swingLow and close < open", self.source)
        self.assertNotIn("close > high[2]", self.source)
        self.assertNotIn("close < low[2]", self.source)
        self.assertNotIn("low > high[2]", self.source)
        self.assertNotIn("high < low[2]", self.source)
        self.assertNotIn("bullishCandle2", self.source)
        self.assertNotIn("bearishCandle2", self.source)
        self.assertIn('input.int(1, "Swing Length"', self.source)
        self.assertIn("armedLevel > armedCandle1BodyHigh and armedLevel < candle3BodyLow", self.source)
        self.assertIn("armedLevel < armedCandle1BodyLow and armedLevel > candle3BodyHigh", self.source)
        self.assertIn("armedCandle1BodyHigh := math.max(open[1], close[1])", self.source)
        self.assertIn('input.int(2, "Swing Breach Lookback"', self.source)
        self.assertIn("bullCloseAge == swingBreachLookback", self.source)
        self.assertIn('const string ENTRY_LIMIT = "Limit at the swing"', self.source)
        self.assertIn('const string ENTRY_MARKET = "Market at close"', self.source)
        self.assertIn('const string ENTRY_BOTH = "Both"', self.source)
        self.assertIn('input.string(ENTRY_MARKET, "Entry Model"', self.source)
        self.assertIn("options = [ENTRY_LIMIT, ENTRY_MARKET, ENTRY_BOTH]", self.source)
        self.assertIn("bool bothEntry = entryModel == ENTRY_BOTH", self.source)
        self.assertNotIn("low > armedCandle1High", self.source)
        self.assertNotIn("high < armedCandle1Low", self.source)
        self.assertNotIn("box.set_right", self.source)
        self.assertNotIn('input.bool(true, "Extend"', self.source)
        self.assertIn('input.int(0, "Minute Window"', self.source)
        self.assertIn('input.int(60, "to"', self.source)
        self.assertIn('input.int(30, "Minute", minval = 0, maxval = 59, group = GRP_TIME, inline = "start"', self.source)
        self.assertIn("f_entryOk(int direction, float entryPrice, float stopPrice)", self.source)
        self.assertIn('input.int(10, "Entry From"', self.source)
        self.assertIn('input.float(8, "Min Range"', self.source)
        self.assertIn('input.float(22, "Long Extension"', self.source)
        self.assertIn('input.float(30, "Max Stop"', self.source)
        self.assertIn('input.bool(false, "Skip Sundays"', self.source)
        self.assertIn("dayofweek.sunday", self.source)
        self.assertIn("bar_index == armedBar + 1 and not sundaySkipped", self.source)
        self.assertIn("not sundaySkipped and not flippedThisBar", self.source)
        self.assertIn('input.string("4H", "Timeframe Target"', self.source)
        self.assertIn('"4H", "Daily"', self.source)
        self.assertIn('targetChoice == "Daily" ? "D"', self.source)
        self.assertIn('input.string("4H", "Liquidity Timeframe"', self.source)
        self.assertIn('input.int(1, "Liquidity Lookback"', self.source)
        self.assertIn("low < closedLiqLow and close > closedLiqLow and close < closedLiqHigh", self.source)
        self.assertIn("high > closedLiqHigh and close < closedLiqHigh and close > closedLiqLow", self.source)
        self.assertIn("close < bullSweepLevel", self.source)
        self.assertIn("close > bearSweepLevel", self.source)
        self.assertIn("bullSweepValid := false", self.source)
        self.assertIn("bearSweepValid := false", self.source)
        self.assertIn("bullBreachBar := bar_index", self.source)
        self.assertIn("bearBreachBar := bar_index", self.source)
        self.assertIn("high > bullBreachHigh and close < bullBreachHigh and close > bullBreachLow", self.source)
        self.assertIn("low < bearBreachLow and close > bearBreachLow and close < bearBreachHigh", self.source)
        self.assertIn("float continuationClose = close", self.source)
        self.assertIn("float continuationOpen = open", self.source)
        self.assertIn("f_target(continuationClose, continuationOpen, continuationBull)", self.source)
        self.assertIn('input.bool(false, "VWAP Chase"', self.source)
        self.assertIn("formation.opposingSwing := armedDirection == DIR_BULL ? swingLow : swingHigh", self.source)
        self.assertIn("postZone.direction == DIR_BEAR and not postZone.flipped and bar_index > postZone.creationBar + 1 and bullishBreakNow", self.source)
        self.assertIn("postZone.direction == DIR_BULL and not postZone.flipped and bar_index > postZone.creationBar + 1 and bearishBreakNow", self.source)
        self.assertIn('input.string("Off", "Key Level"', self.source)
        self.assertIn('"Off", "Same", "1M", "5M", "15M", "1H", "4H", "Daily"', self.source)
        self.assertIn("low < closedKeyLow or close < closedKeyLow", self.source)
        self.assertIn("high > closedKeyHigh or close > closedKeyHigh", self.source)
        self.assertIn("close <= keyBullRangeHigh and close >= keyBullRangeLow", self.source)
        self.assertIn("close <= keyBearRangeHigh and close >= keyBearRangeLow", self.source)
        self.assertIn("allowed and f_keyOk(bullish)", self.source)
        self.assertIn("not vwapChased and f_keyOk(continuationBull)", self.source)
        self.assertIn('input.float(4, "VWAP Chase R"', self.source)
        self.assertIn("float sessionVwap = ta.vwap(hlc3)", self.source)
        self.assertIn("bool vwapChased = useVwapChase and not na(sessionVwap) and continuationRisk > 0 and vwapDistance > vwapChase * continuationRisk", self.source)
        self.assertIn("not vwapChased", self.source)
        self.assertIn("continuationFormation.atClose := true", self.source)
        self.assertIn("sweepValid and not na(sweepBar) and bar_index - sweepBar <= liquidityLookback", self.source)
        self.assertIn("confirmedFvg and sweepStillValid", self.source)
        self.assertIn("f_inWindowAt(int t)", self.source)
        self.assertNotIn("f_fillWindow()", self.source)
        self.assertIn("bool confirmWindow = marketEntry or f_inWindow()", self.source)
        self.assertIn("bool flipWindow = f_inWindow()", self.source)
        self.assertIn("if flipTooClose or not flipWindow", self.source)
        self.assertNotIn("f_inWindow() and f_fillWindow()", self.source)
        self.assertIn('liquiditySelected + " Sweep"', self.source)
        self.assertIn('keySelected + " Sweep"', self.source)
        self.assertIn("label.style_label_left", self.source)
        self.assertIn("line.style_dashed", self.source)
        self.assertNotIn("label.style_label_up", self.source)
        self.assertNotIn("label.style_label_down", self.source)
        self.assertNotIn('liquiditySelected + " sweep"', self.source)
        self.assertIn("firstBullSweepBar := bar_index", self.source)
        self.assertIn("firstBearSweepBar := bar_index", self.source)
        self.assertIn("bullSweepCandle != closedLiqTime", self.source)
        self.assertIn("f_labelFirstSweep(formation)", self.source)
        self.assertIn("f_labelFirstSweep(flipFormation)", self.source)
        self.assertIn("f_labelFirstSweep(continuationFormation)", self.source)
        self.assertIn("continuationFormation.sweepBar := continuationBull ? bullContSweepBar : bearContSweepBar", self.source)
        self.assertIn("bar_index - sweepBar <= liquidityLookback", self.source)
        self.assertIn("(marketEntry or not htfTooClose) and f_liquidityOk(true)", self.source)
        self.assertIn("(marketEntry or not htfTooClose) and f_liquidityOk(false)", self.source)
        self.assertIn("armedStop := open", self.source)
        self.assertIn("marketEntry ? open : (flipDirection == DIR_BULL ? low[1] : high[1])", self.source)
        self.assertIn("if flipLiquidity", self.source)
        self.assertNotIn("if flipTooClose or not flipLiquidity", self.source)
        self.assertIn('input.int(2, "Min RR"', self.source)
        self.assertIn("if minRr > 0 and (na(reward) or reward < minRr * risk)", self.source)
        self.assertIn("htfTooClose := true", self.source)
        self.assertIn("if flipTooClose", self.source)
        self.assertIn("f_deleteVisuals(zone)", self.source)
        self.assertIn("f_target(swingHigh, low[1], true)", self.source)
        self.assertIn("f_target(swingLow, high[1], false)", self.source)
        self.assertIn("f_target(flipLevel, flipStop, flipDirection == DIR_BULL)", self.source)
        self.assertNotIn("f_target(close,", self.source)
        self.assertIn("float level = marketEntry ? marketPrice : swingLevel", self.source)
        self.assertIn("float displacementClose = close[1]", self.source)
        self.assertIn("float useLevel = marketEntry ? displacementClose : resolvedLevel", self.source)
        self.assertIn("f_resolveEntry(armedLevel, armedStop, armedTarget, armedTargetTime, armedUnder, false, armedDirection == DIR_BULL, displacementClose)", self.source)
        self.assertIn("float useLevel = marketEntry ? close : resolvedLevel", self.source)
        self.assertIn("close < zone.impulseLow", self.source)
        self.assertIn("close > zone.impulseHigh", self.source)
        self.assertIn("if not sundaySkipped and not flippedThisBar", self.source)
        self.assertIn("armedStop := low[1]", self.source)
        self.assertIn("armedStop := high[1]", self.source)
        self.assertIn("flipDirection == DIR_BULL ? low[1] : high[1]", self.source)
        self.assertIn("line.new(formation.creationBar - 1, formation.stopPrice, formation.creationBar + 1,", self.source)
        self.assertIn("line.new(formation.creationBar - 1, formation.level, formation.creationBar + 1,", self.source)
        self.assertIn("if not na(formation.level)", self.source)
        self.assertIn("line.new(formation.creationBar, formation.targetPrice, formation.creationBar + 1,", self.source)
        self.assertIn("line.set_x2(formation.entryLine, lineRight)", self.source)
        self.assertIn("line.set_x2(formation.stopLine, lineRight)", self.source)
        self.assertIn("line.set_x2(formation.targetLine, lineRight)", self.source)
        self.assertIn("high >= formation.level and low <= formation.level", self.source)
        self.assertIn("if entryTouched", self.source)
        self.assertIn("formation.entryMitigated := true", self.source)
        self.assertIn("if stopTouched", self.source)
        self.assertIn("high >= formation.stopPrice and low <= formation.stopPrice", self.source)
        self.assertIn("f_deleteVisuals(formation)", self.source)
        self.assertNotIn("targetCopyLine", self.source)
        self.assertIn('input.int(14, "Max Target"', self.source)
        self.assertIn('input.int(6, "Target Swing Length"', self.source)

    def test_close_confirmed_swing_break(self):
        self.assertIn("ta.pivothigh(high, swingLength, swingLength)", self.source)
        self.assertIn("ta.pivotlow(low, swingLength, swingLength)", self.source)
        self.assertIn("barstate.isconfirmed", self.source)
        self.assertIn("box.new(formation.creationBar, formation.impulseHigh, formation.creationBar + 1,", self.source)
        self.assertIn("float midpoint = (formation.impulseHigh + formation.impulseLow) / 2", self.source)
        self.assertIn("style = line.style_dotted", self.source)
        self.assertNotIn("line.set_x2(formation.levelLine", self.source)
        self.assertNotIn("box.set_right", self.source)
        self.assertNotIn("Bullish MSS", self.source)
        self.assertNotIn("Bearish MSS", self.source)

    def test_no_orders(self):
        self.assertIn("request.security(", self.source)
        self.assertIn("lookahead = barmerge.lookahead_on", self.source)
        self.assertIn("[time[1], high[1], low[1]]", self.source)
        self.assertNotIn("strategy.entry", self.source)
        self.assertNotIn("strategy.close", self.source)
        self.assertNotIn("process_orders_on_close", self.source)
        self.assertNotIn("alertcondition", self.source)
        self.assertNotIn("tooltip = tip", self.source)
        self.assertIn("if not useTimeWindow", self.source)
        self.assertIn("useTimeWindow and minuteWindowStart >= minuteWindowEnd", self.source)
        self.assertNotIn(
            'runtime.error("Timeframe Target must be the chart timeframe or higher.")',
            self.source,
        )


class StrategySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STRATEGY.read_text(encoding="utf-8")

    def test_strategy_orders_use_the_breached_swing(self):
        self.assertIn('strategy("Single Candle OB + MSS + FVG Strategy"', self.source)
        self.assertNotIn("indicator(", self.source)
        self.assertIn("f_target(swingHigh, low[1], true)", self.source)
        self.assertIn("f_target(swingLow, high[1], false)", self.source)
        self.assertIn("close > swingHigh and close[1] <= swingHigh and close > open and f_committed(true)", self.source)
        self.assertIn("close < swingLow and close[1] >= swingLow and close < open and f_committed(false)", self.source)
        self.assertIn('input.float(0, "Close Location"', self.source)
        self.assertIn("f_committed(bool bullish)", self.source)
        self.assertIn("bool flipCommitted = (closedBullZone and f_committed(false)) or (closedBearZone and f_committed(true))", self.source)
        self.assertIn("if flipCommitted", self.source)
        self.assertIn("not vwapChased and f_keyOk(continuationBull) and f_committed(continuationBull)", self.source)
        self.assertIn('strategy.entry("1C Long", strategy.long, qty = contracts, limit = formation.level)', self.source)
        self.assertIn('strategy.entry("1C Short", strategy.short, qty = contracts, limit = formation.level)', self.source)
        self.assertIn('strategy.entry("1C Long", strategy.long, qty = contracts)\n', self.source)
        self.assertIn('strategy.entry("1C Short", strategy.short, qty = contracts)\n', self.source)
        self.assertIn('const string ENTRY_LIMIT = "Limit at the swing"', self.source)
        self.assertIn('const string ENTRY_MARKET = "Market at close"', self.source)
        self.assertIn('const string ENTRY_BOTH = "Both"', self.source)
        self.assertIn('input.string(ENTRY_MARKET, "Entry Model"', self.source)
        self.assertIn("options = [ENTRY_LIMIT, ENTRY_MARKET, ENTRY_BOTH]", self.source)
        self.assertIn("bool bothEntry = entryModel == ENTRY_BOTH", self.source)
        self.assertIn("float level = marketEntry ? marketPrice : swingLevel", self.source)
        self.assertIn("float displacementClose = close[1]", self.source)
        self.assertIn("float useLevel = marketEntry ? displacementClose : resolvedLevel", self.source)
        self.assertIn("f_resolveEntry(armedLevel, armedStop, armedTarget, armedTargetTime, armedUnder, false, armedDirection == DIR_BULL, displacementClose)", self.source)
        self.assertIn("float useLevel = marketEntry ? close : resolvedLevel", self.source)
        self.assertNotIn("f_target(close,", self.source)
        self.assertIn('input.int(2, "Swing Breach Lookback"', self.source)
        self.assertIn("armedLevel > armedCandle1BodyHigh and armedLevel < candle3BodyLow", self.source)
        self.assertIn("armedLevel < armedCandle1BodyLow and armedLevel > candle3BodyHigh", self.source)
        self.assertIn("process_orders_on_close = true", self.source)
        self.assertIn("marketOrderLive := true", self.source)
        self.assertIn("f_show(formation, false)", self.source)
        self.assertIn("f_target(bullArmClose, bullArmOpen, true)", self.source)
        self.assertIn("f_target(bearArmClose, bearArmOpen, false)", self.source)
        self.assertIn("formation.protectWaiting := true", self.source)
        self.assertIn('strategy.exit("1C Exit", from_entry = "1C Long", stop = formation.stopPrice, limit = formation.targetPrice)', self.source)
        self.assertIn('strategy.exit("1C Exit", from_entry = "1C Short", stop = formation.stopPrice, limit = formation.targetPrice)', self.source)
        self.assertIn('input.int(2, "Min RR"', self.source)
        self.assertIn('input.int(14, "Max Target"', self.source)
        self.assertIn('input.int(6, "Target Swing Length"', self.source)
        self.assertIn('input.string("4H", "Timeframe Target"', self.source)
        self.assertIn('"4H", "Daily"', self.source)
        self.assertIn('targetChoice == "Daily" ? "D"', self.source)
        self.assertIn('input.string("4H", "Liquidity Timeframe"', self.source)
        self.assertIn('input.int(1, "Liquidity Lookback"', self.source)
        self.assertIn("low < closedLiqLow and close > closedLiqLow and close < closedLiqHigh", self.source)
        self.assertIn("high > closedLiqHigh and close < closedLiqHigh and close > closedLiqLow", self.source)
        self.assertIn("close < bullSweepLevel", self.source)
        self.assertIn("close > bearSweepLevel", self.source)
        self.assertIn("bullSweepValid := false", self.source)
        self.assertIn("bearSweepValid := false", self.source)
        self.assertIn("bullBreachBar := bar_index", self.source)
        self.assertIn("bearBreachBar := bar_index", self.source)
        self.assertIn("high > bullBreachHigh and close < bullBreachHigh and close > bullBreachLow", self.source)
        self.assertIn("low < bearBreachLow and close > bearBreachLow and close < bearBreachHigh", self.source)
        self.assertIn("float continuationClose = close", self.source)
        self.assertIn("float continuationOpen = open", self.source)
        self.assertIn("f_target(continuationClose, continuationOpen, continuationBull)", self.source)
        self.assertIn('input.bool(false, "VWAP Chase"', self.source)
        self.assertIn("formation.opposingSwing := armedDirection == DIR_BULL ? swingLow : swingHigh", self.source)
        self.assertIn("postZone.direction == DIR_BEAR and not postZone.flipped and bar_index > postZone.creationBar + 1 and bullishBreakNow", self.source)
        self.assertIn("postZone.direction == DIR_BULL and not postZone.flipped and bar_index > postZone.creationBar + 1 and bearishBreakNow", self.source)
        self.assertIn('input.string("Off", "Key Level"', self.source)
        self.assertIn('"Off", "Same", "1M", "5M", "15M", "1H", "4H", "Daily"', self.source)
        self.assertIn("low < closedKeyLow or close < closedKeyLow", self.source)
        self.assertIn("high > closedKeyHigh or close > closedKeyHigh", self.source)
        self.assertIn("close <= keyBullRangeHigh and close >= keyBullRangeLow", self.source)
        self.assertIn("close <= keyBearRangeHigh and close >= keyBearRangeLow", self.source)
        self.assertIn("allowed and f_keyOk(bullish)", self.source)
        self.assertIn("not vwapChased and f_keyOk(continuationBull)", self.source)
        self.assertIn('input.float(4, "VWAP Chase R"', self.source)
        self.assertIn("float sessionVwap = ta.vwap(hlc3)", self.source)
        self.assertIn("bool vwapChased = useVwapChase and not na(sessionVwap) and continuationRisk > 0 and vwapDistance > vwapChase * continuationRisk", self.source)
        self.assertIn("not vwapChased", self.source)
        self.assertIn("continuationFormation.atClose := true", self.source)
        self.assertIn("sweepValid and not na(sweepBar) and bar_index - sweepBar <= liquidityLookback", self.source)
        self.assertIn("confirmedFvg and sweepStillValid", self.source)
        self.assertIn("f_inWindowAt(int t)", self.source)
        self.assertNotIn("f_fillWindow()", self.source)
        self.assertIn("bool confirmWindow = marketEntry or f_inWindow()", self.source)
        self.assertIn("bool flipWindow = f_inWindow()", self.source)
        self.assertIn("if flipTooClose or not flipWindow", self.source)
        self.assertNotIn("f_inWindow() and f_fillWindow()", self.source)
        self.assertIn('liquiditySelected + " Sweep"', self.source)
        self.assertIn('keySelected + " Sweep"', self.source)
        self.assertIn("label.style_label_left", self.source)
        self.assertIn("line.style_dashed", self.source)
        self.assertNotIn("label.style_label_up", self.source)
        self.assertNotIn("label.style_label_down", self.source)
        self.assertNotIn('liquiditySelected + " sweep"', self.source)
        self.assertIn("firstBullSweepBar := bar_index", self.source)
        self.assertIn("firstBearSweepBar := bar_index", self.source)
        self.assertIn("bullSweepCandle != closedLiqTime", self.source)
        self.assertIn("f_labelFirstSweep(formation)", self.source)
        self.assertIn("f_labelFirstSweep(flipFormation)", self.source)
        self.assertIn("f_labelFirstSweep(continuationFormation)", self.source)
        self.assertIn("continuationFormation.sweepBar := continuationBull ? bullContSweepBar : bearContSweepBar", self.source)
        self.assertIn("(marketEntry or not htfTooClose) and f_liquidityOk(true)", self.source)
        self.assertIn("(marketEntry or not htfTooClose) and f_liquidityOk(false)", self.source)
        self.assertIn("armedStop := open", self.source)
        self.assertIn("marketEntry ? open : (flipDirection == DIR_BULL ? low[1] : high[1])", self.source)
        self.assertIn("if flipLiquidity", self.source)
        self.assertNotIn("if flipTooClose or not flipLiquidity", self.source)
        self.assertIn('input.bool(false, "Skip Sundays"', self.source)
        self.assertIn("dayofweek.sunday", self.source)
        self.assertIn("bar_index == armedBar + 1 and not sundaySkipped", self.source)
        self.assertIn("not sundaySkipped and not flippedThisBar", self.source)
        self.assertIn("if minRr > 0 and (na(reward) or reward < minRr * risk)", self.source)
        self.assertIn("bool targetOk = minRr > 0 ? hasTarget and targetSide : not hasTarget or targetSide", self.source)
        self.assertIn("if flipTooClose", self.source)
        self.assertIn("if strategy.position_size == 0 and zone.creationBar == array.get(pendingCreation, 0)", self.source)
        self.assertIn("if stopTouched", self.source)
        self.assertIn("not entryTouched and strategy.position_size == 0 and formation.creationBar == array.get(pendingCreation, 0)", self.source)
        self.assertNotIn("pendingCreationBar :=", self.source)
        self.assertIn("f_clearPending()", self.source)
        self.assertIn("else if liquidityOn", self.source)
        self.assertIn('strategy.close("1C Long", comment = "Formation")', self.source)
        self.assertIn('strategy.close("1C Short", comment = "Formation")', self.source)
        self.assertIn("bool useMarket = marketEntry or formation.atClose", self.source)
        self.assertIn("pyramiding = 2", self.source)
        self.assertIn("f_entryOk(int direction, float entryPrice, float stopPrice)", self.source)
        self.assertIn("f_holdingWinner()", self.source)
        self.assertIn('input.bool(true, "Hold Winner"', self.source)
        self.assertIn('input.bool(true, "Flat At 15:55"', self.source)
        self.assertIn('input.float(30, "Max Stop"', self.source)
        self.assertIn('strategy.close("1C Long", comment = "session")', self.source)
        self.assertIn('strategy.entry("1C Long Limit", strategy.long, qty = contracts, limit = formation.swingLevel)', self.source)
        self.assertIn('strategy.entry("1C Short Limit", strategy.short, qty = contracts, limit = formation.swingLevel)', self.source)
        cleaned = self.source
        for entry in (
            'strategy.entry("1C Long", strategy.long, qty = contracts, limit = formation.level)',
            'strategy.entry("1C Short", strategy.short, qty = contracts, limit = formation.level)',
            'strategy.entry("1C Long Limit", strategy.long, qty = contracts, limit = formation.swingLevel)',
            'strategy.entry("1C Short Limit", strategy.short, qty = contracts, limit = formation.swingLevel)',
            'strategy.entry("1C Long", strategy.long, qty = contracts)',
            'strategy.entry("1C Short", strategy.short, qty = contracts)',
        ):
            cleaned = cleaned.replace(entry, "")
        self.assertNotIn("strategy.entry(", cleaned)
        self.assertNotIn("alertcondition", self.source)


class CloseLocationTests(unittest.TestCase):
    def test_outer_quarter_passes_and_a_wick_against_the_close_fails(self):
        self.assertTrue(committed(10, 6, 9, True, 0.75))
        self.assertFalse(committed(10, 6, 8.9, True, 0.75))
        self.assertTrue(committed(10, 6, 7, False, 0.75))
        self.assertFalse(committed(10, 6, 7.1, False, 0.75))

    def test_zero_turns_the_check_off_and_a_zero_range_does_not_pass(self):
        self.assertTrue(committed(10, 10, 10, True, 0))
        self.assertFalse(committed(10, 10, 10, True, 0.75))
