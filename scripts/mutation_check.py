"""Mutation check: change the contract on a disposable copy, one small edit at a time, and see whether the tests notice.

Run from the repository root:  python3 scripts/mutation_check.py
It first proves that the unmodified contract passes, then runs the tests against every mutant (stopping at the first
failing test). A mutant that survives is either a missing test or an equivalent change; survivors are listed.
Each entry is (label, text to find, replacement, which occurrence of the text to change: 1 = first).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/small_claims_jury.py"

MUTANTS = [
    ("title min 6", "TITLE_MIN, TITLE_MAX = 5, 80", "TITLE_MIN, TITLE_MAX = 6, 80", 1),
    ("title max 81", "TITLE_MIN, TITLE_MAX = 5, 80", "TITLE_MIN, TITLE_MAX = 5, 81", 1),
    ("statement min 31", "STATEMENT_MIN, STATEMENT_MAX = 30, 600", "STATEMENT_MIN, STATEMENT_MAX = 31, 600", 1),
    ("statement max 601", "STATEMENT_MIN, STATEMENT_MAX = 30, 600", "STATEMENT_MIN, STATEMENT_MAX = 30, 601", 1),
    ("quote min 9", "QUOTE_MIN, QUOTE_MAX = 8, 300", "QUOTE_MIN, QUOTE_MAX = 9, 300", 1),
    ("quote min 7", "QUOTE_MIN, QUOTE_MAX = 8, 300", "QUOTE_MIN, QUOTE_MAX = 7, 300", 1),
    ("quote max 299", "QUOTE_MIN, QUOTE_MAX = 8, 300", "QUOTE_MIN, QUOTE_MAX = 8, 299", 1),
    ("answer window four days", "ANSWER_SECONDS = 3 * 86400", "ANSWER_SECONDS = 4 * 86400", 1),
    ("answer window two days", "ANSWER_SECONDS = 3 * 86400", "ANSWER_SECONDS = 2 * 86400", 1),
    ("appeal window four days", "APPEAL_SECONDS = 3 * 86400", "APPEAL_SECONDS = 4 * 86400", 1),
    ("appeal window two days", "APPEAL_SECONDS = 3 * 86400", "APPEAL_SECONDS = 2 * 86400", 1),
    ("101 cases", "MAX_CASES = 100", "MAX_CASES = 101", 1),
    ("four unfinished claims", "MAX_ACTIVE_CLAIMS = 3", "MAX_ACTIVE_CLAIMS = 4", 1),
    ("six unfinished against", "MAX_ACTIVE_AGAINST = 5", "MAX_ACTIVE_AGAINST = 6", 1),
    ("page limit 51", "PAGE_LIMIT = 50", "PAGE_LIMIT = 51", 1),
    ("model answer cap", "MAX_MODEL = 4000", "MAX_MODEL = 4001", 1),
    ("quote anchor case sensitive", "_squash(quote).lower() in _squash(statement).lower()", "_squash(quote) in _squash(statement).lower()", 1),
    ("quote anchor spacing sensitive", "_squash(quote).lower() in _squash(statement).lower()", "quote.lower() in statement.lower()", 1),
    ("parser: wrong shape accepted", 'or set(raw) != {"winner", "quote_1", "quote_2"}:', ":", 1),
    ("parser: winner type unchecked", "if type(winner) is not int or winner not in (0, 1, 2) or", "if winner not in (0, 1, 2) or", 1),
    ("parser: winner range", "or winner not in (0, 1, 2) or", "or winner not in (0, 1, 2, 3) or", 1),
    ("parser: quote type unchecked", " or not isinstance(q1, str) or not isinstance(q2, str):", ":", 1),
    ("parser: undecided may quote", 'if q1 != "" or q2 != "":', "if False:", 1),
    ("parser: first quote unchecked", "if not _anchored(q1, first) or not _anchored(q2, second):", "if not _anchored(q2, second):", 1),
    ("parser: second quote unchecked", "if not _anchored(q1, first) or not _anchored(q2, second):", "if not _anchored(q1, first):", 1),
    ("parser: quotes anchored crosswise", "if not _anchored(q1, first) or not _anchored(q2, second):", "if not _anchored(q1, second) or not _anchored(q2, first):", 1),
    ("parser: quotes not squashed", "q1, q2 = _squash(q1), _squash(q2)", "pass", 1),
    ("second reading in the same order", "b = _read_once(title, answer, claim)", "b = _read_once(title, claim, answer)", 1),
    ("first reading answer first", "a = _read_once(title, claim, answer)", "a = _read_once(title, answer, claim)", 1),
    ("first reading mapped wrongly", 'side_a = ("NONE", "CLAIMANT", "RESPONDENT")[a["winner"]]', 'side_a = ("NONE", "RESPONDENT", "CLAIMANT")[a["winner"]]', 1),
    ("second reading mapped like the first", 'side_b = ("NONE", "RESPONDENT", "CLAIMANT")[b["winner"]]', 'side_b = ("NONE", "CLAIMANT", "RESPONDENT")[b["winner"]]', 1),
    ("agreement on nothing is a win", 'if side_a == side_b and side_a != "NONE":', "if side_a == side_b:", 1),
    ("one reading is enough", 'if side_a == side_b and side_a != "NONE":', 'if side_a != "NONE" or side_b != "NONE":', 1),
    ("quotes from the second reading", '"quotes": {"claimant": a["q1"], "respondent": a["q2"]},', '"quotes": {"claimant": b["q2"], "respondent": b["q1"]},', 1),
    ("quotes swapped", '"quotes": {"claimant": a["q1"], "respondent": a["q2"]},', '"quotes": {"claimant": a["q2"], "respondent": a["q1"]},', 1),
    ("a failed reading is tolerated", "if a is None or b is None:", "if a is None and b is None:", 1),
    ("validator: shape unchecked", 'if not isinstance(value, dict):\n        return False\n    if value == {"state": "ERROR"}:', 'if value == {"state": "ERROR"}:', 1),
    ("validator: extra keys allowed", 'if set(value) != {"state", "winner", "quotes", "reads"} or value["state"] != "OK" or', 'if value["state"] != "OK" or', 1),
    ("validator: state unchecked", 'or value["state"] != "OK" or not isinstance(value["quotes"], dict):', 'or not isinstance(value["quotes"], dict):', 1),
    ("validator: quotes type unchecked", ' or not isinstance(value["quotes"], dict):', ":", 1),
    ("validator: undecided with quotes", 'return value["quotes"] == {} and not', "return not", 1),
    ("validator: undecided with agreeing reads", ' and not (reads[0] == reads[1] and reads[0] != "NONE")', "", 1),
    ("validator: agreeing reads on NONE counted as agreement", 'and reads[0] != "NONE")', ")", 1),
    ("validator: reads unchecked", 'if not isinstance(reads, list) or len(reads) != 2 or any(r not in ("NONE", "CLAIMANT", "RESPONDENT") for r in reads):\n        return False', "pass", 1),
    ("validator: reads length unchecked", " or len(reads) != 2", "", 1),
    ("validator: reads values unchecked", ' or any(r not in ("NONE", "CLAIMANT", "RESPONDENT") for r in reads)', "", 1),
    ("validator: win without backing reads", 'if reads != [value["winner"], value["winner"]]:\n        return False', "pass", 1),
    ("reads stored in the other order", '"quotes": {}, "reads": [side_a, side_b]}', '"quotes": {}, "reads": [side_b, side_a]}', 1),
    ("reads of a win not stored", 'case["reads"] = reading["reads"]', 'pass', 1),
    ("validator: any winner", 'if value["winner"] not in ("CLAIMANT", "RESPONDENT") or set(value["quotes"]) != {"claimant", "respondent"}:', 'if set(value["quotes"]) != {"claimant", "respondent"}:', 1),
    ("validator: quote keys unchecked", 'or set(value["quotes"]) != {"claimant", "respondent"}:', ":", 1),
    ("validator: quote types unchecked", "return (isinstance(c, str) and isinstance(r, str) and c == _squash(c)", "return (c == _squash(c)", 1),
    ("validator: quotes not squashed", "and c == _squash(c) and r == _squash(r)\n            and", "and True\n            and", 1),
    ("validator: claimant quote unanchored", "and _anchored(c, claim) and _anchored(r, answer))", "and _anchored(r, answer))", 1),
    ("validator: respondent quote unanchored", "and _anchored(c, claim) and _anchored(r, answer))", "and _anchored(c, claim))", 1),
    ("validator: quotes anchored crosswise", "and _anchored(c, claim) and _anchored(r, answer))", "and _anchored(c, answer) and _anchored(r, claim))", 1),
    ("validator: result type unchecked", "if not isinstance(result, gl.vm.Return):\n            return False\n        proposed", "proposed", 1),
    ("validator: size cap removed", "or len(proposed) > 2000:", ":", 1),
    ("validator: non-canonical text", "or proposed != _canonical(parsed):", ":", 1),
    ("validator: own state ignored", 'if parsed["state"] != mine["state"]:', "if False:", 1),
    ("validator: error accepted over a reading", 'return parsed["state"] == "ERROR" or parsed["winner"] == mine["winner"]', 'return True', 1),
    ("validator: winner ignored", 'return parsed["state"] == "ERROR" or parsed["winner"] == mine["winner"]', 'return parsed["state"] == "ERROR" or True', 1),
    ("self filing allowed", "if other == me:", "if False:", 1),
    ("board full off by one", "if len(cases) >= MAX_CASES:", "if len(cases) > MAX_CASES:", 1),
    ("claim cap off by one", 'c["phase"] in ACTIVE) >= MAX_ACTIVE_CLAIMS', 'c["phase"] in ACTIVE) > MAX_ACTIVE_CLAIMS', 1),
    ("claim cap counts finished cases", 'if c["claimant"] == me and c["phase"] in ACTIVE) >= MAX_ACTIVE_CLAIMS', 'if c["claimant"] == me) >= MAX_ACTIVE_CLAIMS', 1),
    ("claim cap counts everyone", 'if c["claimant"] == me and c["phase"] in ACTIVE) >= MAX_ACTIVE_CLAIMS', 'if c["phase"] in ACTIVE) >= MAX_ACTIVE_CLAIMS', 1),
    ("against cap off by one", 'c["phase"] in ACTIVE) >= MAX_ACTIVE_AGAINST', 'c["phase"] in ACTIVE) > MAX_ACTIVE_AGAINST', 1),
    ("against cap counts finished cases", 'if c["respondent"] == other and c["phase"] in ACTIVE) >= MAX_ACTIVE_AGAINST', 'if c["respondent"] == other) >= MAX_ACTIVE_AGAINST', 1),
    ("against cap counts everyone", 'if c["respondent"] == other and c["phase"] in ACTIVE) >= MAX_ACTIVE_AGAINST', 'if c["phase"] in ACTIVE) >= MAX_ACTIVE_AGAINST', 1),
    ("answer window set to the claim time", '"filed": now, "answer_by": now + ANSWER_SECONDS', '"filed": now, "answer_by": now', 1),
    ("case count not kept", "self.case_count = u32(case_id + 1)", "pass", 1),
    ("anyone can answer", 'if _sender() != case["respondent"]:\n            raise gl.vm.UserError("only the respondent can answer")', 'if False:\n            raise gl.vm.UserError("only the respondent can answer")', 1),
    ("answer in any phase", 'if case["phase"] != "OPEN":\n            raise gl.vm.UserError("the case is not waiting for an answer")\n        now = _now()', 'if False:\n            raise gl.vm.UserError("the case is not waiting for an answer")\n        now = _now()', 1),
    ("answer window one second longer", 'if now >= case["answer_by"]:', 'if now > case["answer_by"]:', 1),
    ("answer window ignored", 'if now >= case["answer_by"]:\n            raise gl.vm.UserError("the time to answer has passed")', 'if False:\n            raise gl.vm.UserError("the time to answer has passed")', 1),
    ("answer not stored", 'case["answer"] = statement', "pass", 1),
    ("answer time not stored", 'case["answered"] = now', "pass", 1),
    ("answer does not move the phase", 'case["phase"] = "ANSWERED"', "pass", 1),
    ("answer statement unchecked", '        case = self._load(case_id)\n        statement = _text(statement, STATEMENT_MIN, STATEMENT_MAX, "statement")\n        if _sender() != case["respondent"]:', '        case = self._load(case_id)\n        if _sender() != case["respondent"]:', 1),
    ("close in any phase", 'if case["phase"] != "OPEN":\n            raise gl.vm.UserError("the case is not waiting for an answer")\n        if _now() <', 'if False:\n            raise gl.vm.UserError("the case is not waiting for an answer")\n        if _now() <', 1),
    ("close one second early", 'if _now() < case["answer_by"]:', 'if _now() < case["answer_by"] - 1:', 1),
    ("close one second late", 'if _now() < case["answer_by"]:', 'if _now() <= case["answer_by"]:', 1),
    ("close does not close", 'case["phase"] = "UNANSWERED"', "pass", 1),
    ("anyone can withdraw", 'if _sender() != case["claimant"]:\n            raise gl.vm.UserError("only the claimant can withdraw")', 'if False:\n            raise gl.vm.UserError("only the claimant can withdraw")', 1),
    ("withdraw after the ruling", 'if case["phase"] not in ACTIVE:\n            raise gl.vm.UserError("the case is closed")', 'if False:\n            raise gl.vm.UserError("the case is closed")', 1),
    ("withdraw only before an answer", 'if case["phase"] not in ACTIVE:', 'if case["phase"] != "OPEN":', 1),
    ("withdraw does not withdraw", 'case["phase"] = "WITHDRAWN"', "pass", 1),
    ("ruling without an answer", 'if case["phase"] != "ANSWERED":\n            raise gl.vm.UserError("the case is not ready for a ruling")', 'if False:\n            raise gl.vm.UserError("the case is not ready for a ruling")', 1),
    ("unreadable ruling passes", 'if reading["state"] != "OK":\n            raise gl.vm.UserError("the ruling could not be read, try again")\n        now = _now()', 'if False:\n            raise gl.vm.UserError("the ruling could not be read, try again")\n        now = _now()', 1),
    ("ruling does not move the phase", 'case["phase"] = "RULED"', "pass", 1),
    ("ruling time not stored", 'case["ruled"] = now', "pass", 1),
    ("winner not stored", 'case["winner"] = reading["winner"]', "pass", 1),
    ("quotes not stored", 'case["quotes"] = reading["quotes"]', "pass", 1),
    ("appeal window not stored", 'case["appeal_until"] = now + APPEAL_SECONDS', "pass", 1),
    ("appeal without a ruling", 'if case["phase"] != "RULED" or case["winner"] not in ("CLAIMANT", "RESPONDENT"):', 'if False:', 1),
    ("appeal after an undecided ruling", 'if case["phase"] != "RULED" or case["winner"] not in ("CLAIMANT", "RESPONDENT"):', 'if case["phase"] != "RULED":', 1),
    ("the winner appeals", 'loser = case["respondent"] if case["winner"] == "CLAIMANT" else case["claimant"]', 'loser = case["claimant"] if case["winner"] == "CLAIMANT" else case["respondent"]', 1),
    ("anyone appeals", 'if _sender() != loser:', "if False:", 1),
    ("appeal twice", 'if case["appeal"] is not None:', "if False:", 1),
    ("appeal window ignored", 'if _now() >= case["appeal_until"]:', "if False:", 1),
    ("appeal one second late", 'if _now() >= case["appeal_until"]:', 'if _now() > case["appeal_until"]:', 1),
    ("unreadable appeal passes", 'if reading["state"] != "OK":\n            raise gl.vm.UserError("the ruling could not be read, try again")\n        first', 'if False:\n            raise gl.vm.UserError("the ruling could not be read, try again")\n        first', 1),
    ("appeal always confirms", 'if reading["winner"] == first:', "if True:", 1),
    ("appeal never confirms", 'if reading["winner"] == first:', "if False:", 1),
    ("failed appeal keeps the winner", 'case["winner"] = "UNDECIDED"\n            case["quotes"] = {}', 'case["quotes"] = {}', 1),
    ("failed appeal keeps the quotes", 'case["winner"] = "UNDECIDED"\n            case["quotes"] = {}', 'case["winner"] = "UNDECIDED"', 1),
    ("appeal result missing the first ruling", '"first": first, "second": reading["winner"]}\n        else:', '"first": None, "second": reading["winner"]}\n        else:', 1),
    ("case view type unchecked", "if type(case_id) is not int or case_id < 0 or case_id >= int(self.case_count):\n            return \"NONE\"", "if case_id >= int(self.case_count):\n            return \"NONE\"", 1),
    ("page type unchecked", "if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= PAGE_LIMIT:", "if offset < 0 or not 1 <= limit <= PAGE_LIMIT:", 1),
    ("page limit unchecked", "or offset < 0 or not 1 <= limit <= PAGE_LIMIT:", "or offset < 0 or limit < 1:", 1),
    ("claimant wins counted as losses", 'mine["won" if case["winner"] == "CLAIMANT" else "lost" if case["winner"] == "RESPONDENT" else "undecided"] += 1', 'mine["lost" if case["winner"] == "CLAIMANT" else "won" if case["winner"] == "RESPONDENT" else "undecided"] += 1', 1),
    ("respondent wins counted as losses", 'mine["won" if case["winner"] == "RESPONDENT" else "lost" if case["winner"] == "CLAIMANT" else "undecided"] += 1', 'mine["lost" if case["winner"] == "RESPONDENT" else "won" if case["winner"] == "CLAIMANT" else "undecided"] += 1', 1),
    ("withdrawn not counted", 'elif case["phase"] == "WITHDRAWN":\n                    mine["withdrawn"] += 1', "elif False:\n                    mine[\"withdrawn\"] += 1", 1),
    ("answered not counted", 'if case["answer"] is not None:\n                    mine["answered"] += 1', "if False:\n                    mine[\"answered\"] += 1", 1),
    ("record address case sensitive", "who = _address(address)\n        out =", "who = address\n        out =", 1),
]


def run_tests(directory: Path) -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
                            cwd=directory, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mutation-") as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "contracts", work / "contracts")
        shutil.copytree(ROOT / "tests", work / "tests")
        source = (ROOT / CONTRACT).read_text()
        if not run_tests(work):
            print("The unmodified contract does not pass its tests; stopping.")
            return 2
        print("base: tests pass on the unmodified contract")
        killed, survived = 0, []
        for label, old, new, nth in MUTANTS:
            if source.count(old) < nth:
                print("ANCHOR MISSING:", label)
                return 3
            parts = source.split(old)
            mutated = old.join(parts[:nth]) + new + old.join(parts[nth:])
            (work / CONTRACT).write_text(mutated)
            if run_tests(work):
                survived.append(label)
                print("SURVIVED:", label)
            else:
                killed += 1
        print("mutants: %d, killed: %d, survived: %d" % (len(MUTANTS), killed, len(survived)))
        for label in survived:
            print(" -", label)
        return 0


if __name__ == "__main__":
    sys.exit(main())
