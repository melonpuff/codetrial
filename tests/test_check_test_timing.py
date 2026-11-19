#!/usr/bin/env python3
"""Contract tests for scripts/check-test-timing.mjs, the browser-test timing gate."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-test-timing.mjs"


def check(source, name="a.test.js"):
    """The gate run over a directory holding one test file with `source`."""
    with tempfile.TemporaryDirectory() as scratch:
        (Path(scratch) / name).write_text(source)
        result = subprocess.run(
            ["node", str(CHECK), scratch],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.returncode, result.stderr


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CheckTestTimingTests(unittest.TestCase):
    def assertRejected(self, source, expected):
        code, message = check(source)
        self.assertEqual(code, 1, message)
        self.assertIn(expected, message)

    def assertAccepted(self, source, name="a.test.js"):
        code, message = check(source, name)
        self.assertEqual(code, 0, message)

    def test_clean_directory_passes(self):
        self.assertAccepted("await until(() => ready, { what: 'ready' });\n")

    def test_deadline_variable_is_rejected(self):
        self.assertRejected("const deadline = Date.now() + 5000;\n", "a.test.js:1")

    def test_other_names_for_a_bound_are_rejected(self):
        for name in ("limit", "giveUpAt", "expiresAt", "until"):
            with self.subTest(name=name):
                self.assertRejected(
                    f"const {name} = Date.now() + 9000;\n", "wall-clock"
                )

    def test_a_timestamp_that_is_data_is_not_a_bound(self):
        self.assertAccepted("lifecycle.endsAt = Date.now() + 45 * 60 * 1000;\n")

    def test_uncommented_wait_for_timeout_is_rejected(self):
        self.assertRejected("await page.waitForTimeout(500);\n", "fixed sleep")

    def test_uncommented_set_timeout_sleep_is_rejected(self):
        self.assertRejected(
            "await new Promise((resolve) => setTimeout(resolve, 1100));\n",
            "fixed sleep",
        )

    def test_an_arrow_resolving_sleep_is_rejected(self):
        self.assertRejected(
            "await new Promise((resolve) => setTimeout(() => resolve(), 500));\n",
            "fixed sleep",
        )

    def test_short_timer_yield_is_not_a_sleep(self):
        self.assertAccepted("await new Promise((r) => setTimeout(r, 0));\n")

    def test_comment_above_a_sleep_accepts_it(self):
        self.assertAccepted(
            "// Absence proof: outwait the debounce.\nawait page.waitForTimeout(500);\n"
        )

    def test_url_in_a_string_is_not_a_comment(self):
        self.assertRejected(
            'await fetch("http://x");\nawait page.waitForTimeout(500);\n',
            "fixed sleep",
        )

    def test_timing_ok_marker_accepts_a_deliberate_bound(self):
        self.assertAccepted(
            "// timing-ok: budget for a cold model load\n"
            "const deadline = Date.now() + budget;\n"
        )

    def test_a_bound_split_over_lines_is_rejected(self):
        self.assertRejected("const deadline =\n  Date.now() + 5000;\n", "a.test.js:1")

    def test_a_sleep_split_over_lines_with_a_trailing_comma_is_rejected(self):
        self.assertRejected(
            "await new Promise((resolve) => setTimeout(\n  resolve,\n  1000,\n));\n",
            "fixed sleep",
        )

    def test_quoted_text_is_not_code(self):
        self.assertAccepted('const note = "const deadline = Date.now() + 5000";\n')

    def test_a_marker_inside_a_string_exempts_nothing(self):
        self.assertRejected(
            'const note = "timing-ok:";\nconst deadline = Date.now() + 5000;\n',
            "wall-clock",
        )

    def test_an_apostrophe_in_a_comment_does_not_hide_later_code(self):
        self.assertRejected(
            "// it's a note\nconst deadline = Date.now() + 5000;\n", "a.test.js:2"
        )

    def test_wait_helper_is_exempt(self):
        self.assertAccepted("const deadline = Date.now() + timeout;\n", "wait.js")

    def test_a_wait_bounding_what_was_just_set_is_rejected(self):
        self.assertRejected(SET_THEN + BOUND_WAIT, "a.test.js:4: wait bounds")
        for wait in (
            "const reachable = await reaches(page, () => layer.scrollTop > 0);\n",
            "let ok = await page.waitForFunction(() => layer.scrollTop > 0);\n",
            "assert.equal(await reaches(page, () => layer.scrollTop > 0), true);\n",
        ):
            with self.subTest(wait=wait):
                self.assertRejected(SET_THEN + wait, "a.test.js:4: wait bounds")

    def test_the_message_names_the_property_just_set(self):
        self.assertRejected(
            SET_THEN + BOUND_WAIT, "wait bounds .scrollTop, which the test just set"
        )

    def test_every_bound_operator_and_wait_helper_is_rejected(self):
        for wait in (
            "await page.waitForFunction(() => layer.scrollTop !== 0);\n",
            "await reaches(page, () => layer.scrollTop >= 1);\n",
            "await reaches(page, () => layer.scrollTop <= 1);\n",
            "await page.waitForFunction(() => layer.scrollTop != 0);\n",
            "await until(async () => (await top()).scrollTop < 2000, 'top');\n",
            "await page.waitForFunction (() => layer.scrollTop > 0);\n",
            "await page.waitForFunction(() => near(top, 1) && layer.scrollTop > 0);\n",
            "await page.waitForFunction(() => {\n"
            "  const [first, second] = [1, 2];\n"
            "  return layer.scrollTop > first + second;\n"
            "});\n",
        ):
            with self.subTest(wait=wait):
                self.assertRejected(SET_THEN + wait, "wait bounds")

    def test_an_exact_comparison_beside_the_bound_does_not_exempt_it(self):
        for wait in (
            "await page.waitForFunction(\n"
            "  () => layer.scrollTop === 900 || layer.scrollTop > 0,\n"
            ");\n",
            "await page.waitForFunction(\n"
            "  () => code.scrollTop === 900 && layer.scrollTop > 0,\n"
            ");\n",
        ):
            with self.subTest(wait=wait):
                self.assertRejected(SET_THEN + wait, "wait bounds")

    def test_an_exact_comparison_with_another_literal_is_rejected(self):
        self.assertRejected(
            SET_THEN + "await page.waitForFunction(() => layer.scrollTop === 1);\n",
            "a.test.js:4: wait compares .scrollTop with 1, but the test just set 900",
        )
        for source in (
            SET_THEN + "await page.waitForFunction(() => 1 === layer.scrollTop);\n",
            SET_THEN + "await page.waitForFunction(() => 0 === layer.scrollTop);\n",
            "await page.locator('#code').evaluate((node) => (node.scrollTop = 900));\n"
            "await page.waitForFunction(() => layer.scrollTop === 1);\n",
            "await page.evaluate(() => { panel.hidden = false; });\n"
            "await page.waitForFunction(() => panel.hidden === true);\n",
            "await page.evaluate(() => { count.value = -1; });\n"
            "await page.waitForFunction(() => count.value === 0);\n",
            "await page.evaluate(() => { count.value = 0; });\n"
            "await page.waitForFunction(() => -1 === count.value);\n",
            SET_THEN + "await page.waitForFunction(() => layer.scrollTop == 1);\n",
            SET_THEN + "await page.waitForFunction(() => 1 == layer.scrollTop);\n",
            "await page.evaluate(() => { zoom.scale = 0.5; });\n"
            "await page.waitForFunction(() => zoom.scale === 1.5);\n",
            "await page.evaluate(() => { state.current = null; });\n"
            "await page.waitForFunction(() => state.current === 1);\n",
            "await page.evaluate(() => { left.scrollTop = right.scrollTop = 900; });\n"
            "await page.waitForFunction(() => left.scrollTop === 1);\n",
            "await page.evaluate(() => { code.scrollTop = 0; });\n"
            + SET_THEN
            + "await page.waitForFunction(() => layer.scrollTop === 0);\n",
            "await page.evaluate(() => { code.scrollLeft = 1; code.scrollTop = 900; });\n"
            "await page.waitForFunction(() => layer.scrollTop === 1);\n",
        ):
            with self.subTest(source=source):
                self.assertRejected(source, "wait compares")
        self.assertRejected(
            "await page.evaluate(() => { first.scrollTop = 100; second.scrollTop = 900; });\n"
            "await page.waitForFunction(() => first.scrollTop === 1);\n",
            "wait compares .scrollTop with 1, but the test just set 100, 900",
        )

    def test_a_value_the_literals_do_not_settle_passes(self):
        for source in (
            "await page.evaluate(() => { code.scrollTop = target; });\n"
            "await page.waitForFunction(() => layer.scrollTop === 1);\n",
            SET_THEN
            + "await page.waitForFunction(() => layer.scrollTop === 1 + gap);\n",
            SET_THEN
            + "await page.waitForFunction(() => gap - 1 === layer.scrollTop);\n",
            SET_THEN + "await page.waitForFunction(() => layer.scrollTop === 900.0);\n",
            SET_THEN
            + "await page.waitForFunction(() => 0 === layer.scrollTop - 900);\n",
            SET_THEN
            + "await page.waitForFunction(() => layer.scrollTop - 900 === 0);\n",
            SET_THEN
            + "await page.waitForFunction(() => 1 + layer.scrollTop === 901);\n",
            "await page.evaluate(() => { code.scrollTop = 1 + offset; });\n"
            "await page.waitForFunction(() => layer.scrollTop === 901);\n",
        ):
            with self.subTest(source=source):
                self.assertAccepted(source)

    def test_a_bound_with_the_property_on_the_right_is_rejected(self):
        for wait in (
            "await page.waitForFunction(() => 0 < layer.scrollTop);\n",
            "await page.waitForFunction(\n"
            "  () => 0 !== document.querySelector('.layer').scrollTop,\n"
            ");\n",
            "await until(async () => 2000 > (await top()).scrollTop, 'top');\n",
            "await page.waitForFunction(\n"
            "  () => 0 < document.querySelector(selectorFor('layer')).scrollTop,\n"
            ");\n",
            "await page.waitForFunction(\n"
            "  () => 0 < document.querySelectorAll('.layer')[0].scrollTop,\n"
            ");\n",
        ):
            with self.subTest(wait=wait):
                self.assertRejected(SET_THEN + wait, "wait bounds")

    def test_the_value_set_on_the_right_passes(self):
        self.assertAccepted(
            SET_THEN + "await page.waitForFunction(() => 900 === layer.scrollTop);\n"
        )

    def test_a_wait_for_the_value_set_passes(self):
        for source in (
            SET_THEN
            + "await reaches(page, () => layer.scrollTop === 900 && top > 0);\n",
            "await page.evaluate(() => { panel.hidden = true; });\n"
            "await page.waitForFunction(() => panel.hidden === true);\n",
            "await page.evaluate(() => { count.value = -1; });\n"
            "await page.waitForFunction(() => count.value === -1);\n",
            SET_THEN + "await page.waitForFunction(() => layer.scrollTop == 900);\n",
            SET_THEN + "await page.waitForFunction(() => 900 == layer.scrollTop);\n",
            "await page.evaluate(() => { first.scrollTop = 100; second.scrollTop = 900; });\n"
            "await page.waitForFunction(\n"
            "  () => first.scrollTop === 100 && second.scrollTop === 900,\n"
            ");\n",
            "await page.evaluate(() => { left.scrollTop = right.scrollTop = 900; });\n"
            "await page.waitForFunction(() => left.scrollTop === 900);\n",
            "await page.evaluate(() => { left.scrollTop = right.scrollLeft = 900; });\n"
            "await page.waitForFunction(() => left.scrollTop === 900);\n",
            "const page = await preflight(t, () => {\n"
            "  first.scrollTop = 100;\n"
            "  second.scrollTop = 900;\n"
            "});\n"
            "await page.waitForFunction(() => first.scrollTop === 100);\n",
        ):
            with self.subTest(source=source):
                self.assertAccepted(source)

    def test_a_step_between_the_set_and_the_wait_unties_them(self):
        for source in (
            SET_THEN + "await page.click('#more');\n" + BOUND_WAIT,
            "state.count = 0;\nstep();\nawait until(() => state.count >= 3, 'count');\n",
        ):
            with self.subTest(source=source):
                self.assertAccepted(source)

    def test_a_step_after_the_set_inside_the_callback_unties_them(self):
        for source in (
            "await page.evaluate(() => {\n"
            "  window.cutParses = 1;\n"
            "  type(other);\n"
            "});\n"
            "await page.waitForFunction(() => window.cutParses === 0);\n",
            "await page.evaluate(() => {\n"
            "  if (on) { code.scrollTop = 900; }\n"
            "  code.click();\n"
            "});\n" + BOUND_WAIT,
        ):
            with self.subTest(source=source):
                self.assertAccepted(source)

    def test_a_step_that_is_not_awaited_also_unties_them(self):
        self.assertAccepted(
            SET_THEN + "layer.scrollTo({ top: 0, behavior: 'instant' });\n" + BOUND_WAIT
        )

    def test_an_assignment_that_runs_before_the_wait_is_tied(self):
        for source in (
            "const before = await page.evaluate(() => {\n"
            "  document.getElementById('code').scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
            "await page\n"
            "  .locator('#code')\n"
            "  .evaluate((node) => (node.scrollTop = 900));\n" + BOUND_WAIT,
            "state.count = 0;\nawait until(() => state.count >= 3, 'count');\n",
            "await page.locator('#code', { state: { visible: true } })\n"
            "  .evaluate((node) => (node.scrollTop = 900));\n" + BOUND_WAIT,
            "await firstPage.evaluate(() => { code.scrollTop = other.scrollTop; });\n"
            "await firstPage.waitForFunction(() => layer.scrollTop > 0);\n",
            "await page.locator(sel('#code')).evaluate((node) => (node.scrollTop = 900));\n"
            + BOUND_WAIT,
            "await t.test('reset', () => page.evaluate(() => {\n"
            "  document.querySelector('#code').scrollTop = 900;\n"
            "}));\n" + BOUND_WAIT,
            "await Promise.all([page.evaluate(() => { code.scrollTop = 900; })]);\n"
            + BOUND_WAIT,
            "await page.evaluate(async () => {\n"
            "  code.scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
            "await page.evaluate(async function () {\n"
            "  code.scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
            "await page.locator('#code').evaluate((node, top) => {\n"
            "  node.scrollTop = top;\n"
            "}, 900);\n" + BOUND_WAIT,
            "await page.locator('#code').evaluate((node) => {\n"
            "  node.scrollTop = 900;\n"
            "}, undefined);\n" + BOUND_WAIT,
            "const strip = page.locator('.strip');\n"
            "await strip.evaluate((node) => (node.scrollTop = 900));\n" + BOUND_WAIT,
            "const handle = await page.$('#code');\n"
            "await handle.evaluate((node) => { node.scrollTop = 900; });\n"
            "await reaches(page, () => layer.scrollTop > 0);\n",
        ):
            with self.subTest(source=source):
                self.assertRejected(source, "wait bounds")

    def test_an_assignment_in_a_stored_function_is_not_tied(self):
        for source in (
            "const resetScroll = () => page.evaluate(() => {\n"
            "  document.getElementById('code').scrollTop = 900;\n"
            "});\n" + BOUND_WAIT + "await resetScroll();\n",
            "await page.evaluate(() => {\n"
            "  globalThis.resetScroll = () => { code.scrollTop = 900; };\n"
            "});\n" + BOUND_WAIT,
            "await page.evaluate(() => {\n"
            "  globalThis.resetScroll = () => (code.scrollTop = 900);\n"
            "});\n" + BOUND_WAIT,
            "await page.evaluate(() => {\n"
            "  globalThis.resetScroll = function () { code.scrollTop = 900; };\n"
            "});\n" + BOUND_WAIT,
            "await page.evaluate(() => {\n"
            "  globalThis.api = { reset() { code.scrollTop = 900; } };\n"
            "});\n" + BOUND_WAIT,
        ):
            with self.subTest(source=source):
                self.assertAccepted(source)

    def test_a_value_set_in_a_stored_function_is_not_a_value_set(self):
        then = "  code.scrollTop = 900;\n});\n"
        wait = "await page.waitForFunction(() => layer.scrollTop === 0);\n"
        for reset in (
            "  globalThis.reset = () => { code.scrollTop = 0; };\n",
            "  globalThis.reset = () => (code.scrollTop = 0);\n",
            "  globalThis.reset = function () { code.scrollTop = 0; };\n",
            "  globalThis.reset = () => { if (on) { code.scrollTop = 0; } };\n",
            "  globalThis.api = { reset() { code.scrollTop = 0; } };\n",
            "  globalThis.api = { other() {}, reset() { code.scrollTop = 0; } };\n",
            "  class Api { async reset() { code.scrollTop = 0; } }\n",
        ):
            with self.subTest(reset=reset):
                self.assertRejected(
                    "await page.evaluate(() => {\n" + reset + then + wait,
                    "compares .scrollTop with 0, but the test just set 900",
                )
        for runs in (
            "  [a, b].forEach((el) => { el.scrollTop = 0; });\n",
            "  [a, b].forEach(function each(el) { el.scrollTop = 0; });\n",
            "  if (on) { code.scrollTop = 0; }\n",
            "  for (const el of [a, b]) { el.scrollTop = 0; }\n",
            "  for await (const el of [a, b]) { el.scrollTop = 0; }\n",
            "  [a, b].forEach(function (el) { el.scrollTop = 0; });\n",
            "  [a, b].forEach(async function (el) { el.scrollTop = 0; });\n",
            "  while (!done) { code.scrollTop = 0; done = true; }\n",
            "  switch (mode) { case 1: code.scrollTop = 0; }\n",
            "  try { step(); } catch (error) { code.scrollTop = 0; }\n",
        ):
            with self.subTest(runs=runs):
                self.assertAccepted(
                    "await page.evaluate(() => {\n" + runs + then + wait
                )

    def test_a_wait_on_another_page_is_not_tied(self):
        set_first = (
            OPEN_FIRST + "await firstPage.evaluate(() => {\n"
            "  document.querySelector('#code').scrollTop = 900;\n"
            "});\n"
        )
        for wait in (
            "await secondPage.waitForFunction(() => layer.scrollTop > 0);\n",
            "await reaches(secondPage, () => layer.scrollTop > 0);\n",
        ):
            with self.subTest(wait=wait):
                self.assertAccepted(set_first + wait)
        for used in (
            "await firstPage.waitForFunction(() => ready);\n",
            "await reaches(firstPage, () => ready);\n",
        ):
            with self.subTest(used=used):
                self.assertAccepted(
                    set_first.replace(OPEN_FIRST, used)
                    + "await secondPage.waitForFunction(() => layer.scrollTop > 0);\n"
                )
        for set_first in (
            "await firstPage\n"
            "  .locator('#code')\n"
            "  .evaluate((node) => (node.scrollTop = 900));\n",
            "await Promise.all([\n"
            "  firstPage.evaluate(() => { code.scrollTop = 900; }),\n"
            "]);\n",
            "await t.test('set', () => firstPage.evaluate(() => {\n"
            "  code.scrollTop = 900;\n"
            "}));\n",
        ):
            with self.subTest(set_first=set_first):
                self.assertAccepted(
                    OPEN_FIRST
                    + set_first
                    + "await secondPage.waitForFunction(() => layer.scrollTop > 0);\n"
                )

    def test_a_page_the_names_do_not_tell_stays_tied(self):
        self.assertRejected(
            "const page = await preflight(t, () => {\n"
            "  document.querySelector('#code').scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
            "wait bounds",
        )

    def test_an_assignment_in_another_test_is_not_tied_to_the_wait(self):
        self.assertAccepted(
            "test('set', async () => {\n"
            "  await first.evaluate(() => { code.scrollTop = 900; });\n"
            "});\n"
            "test('wait', async () => {\n"
            "  await second.waitForFunction(() => layer.scrollTop > 0);\n"
            "});\n"
        )

    def test_a_wait_is_reported_once(self):
        for source in (
            "await page.evaluate(() => {\n"
            "  left.scrollTop = 900;\n"
            "  right.scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
            "await page.evaluate(() => {\n"
            "  left.scrollTop = right.scrollTop = 900;\n"
            "});\n" + BOUND_WAIT,
        ):
            with self.subTest(source=source):
                code, message = check(source)
                self.assertEqual(code, 1, message)
                self.assertEqual(message.count("wait bounds"), 1, message)

    def test_an_assignment_of_what_the_wait_returns_is_not_tied(self):
        self.assertAccepted(
            "state.count = await until(() => state.count >= 3, 'count');\n"
        )

    def test_a_shift_is_not_a_bound(self):
        for wait in (
            "await page.waitForFunction(() => (layer.scrollTop >> 0) === 900);\n",
            "await page.waitForFunction(() => (1 << layer.scrollTop) === 2);\n",
        ):
            with self.subTest(wait=wait):
                self.assertAccepted(SET_THEN + wait)

    def test_a_bound_on_another_property_passes(self):
        self.assertAccepted(
            "await page.evaluate(() => { code.value = 'x'; });\n" + BOUND_WAIT
        )

    def test_a_comparison_after_the_wait_is_not_its_predicate(self):
        self.assertAccepted(
            SET_THEN
            + "await page.waitForFunction(() => ready);\n"
            + "assert.ok(layer.scrollTop > 0);\n"
        )

    def test_a_comparison_in_another_argument_is_not_the_predicate(self):
        for wait in (
            "await until(() => ready, layer.scrollTop > 0 ? 'scrolled' : 'ready');\n",
            "await page.waitForFunction(() => ready, layer.scrollTop > 0);\n",
            "await reaches(page, () => ready, layer.scrollTop > 0);\n",
        ):
            with self.subTest(wait=wait):
                self.assertAccepted(SET_THEN + wait)

    def test_an_assignment_in_a_comment_or_string_is_not_code(self):
        self.assertAccepted("// code.scrollTop = 900;\n" + BOUND_WAIT)
        self.assertAccepted("const note = 'code.scrollTop = 900';\n" + BOUND_WAIT)

    def test_timing_ok_marker_accepts_a_deliberate_bound_wait(self):
        self.assertAccepted(
            "await page.evaluate(() => { globalThis.count = 0; });\n"
            "// timing-ok: the reset is below the bound\n"
            "await page.waitForFunction(() => globalThis.count >= 3);\n"
        )


# The shape the task editor test failed in CI with.
SET_THEN = (
    "await page.evaluate(() => {\n"
    "  document.getElementById('code').scrollTop = 900;\n"
    "});\n"
)
BOUND_WAIT = "await page.waitForFunction(() => layer.scrollTop > 0);\n"
OPEN_FIRST = "await firstPage.goto(url);\n"


if __name__ == "__main__":
    unittest.main()
