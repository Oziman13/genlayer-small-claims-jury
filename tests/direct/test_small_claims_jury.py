"""Small Claims Jury v0.1 tests (genlayer-test direct mode: in-memory, model mocked).

Run from the repository root:  python3 -m pytest tests/direct
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone

import pytest
from gltest.direct import create_address

CONTRACT = "contracts/small_claims_jury.py"
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
HOUR, DAY = 3600, 86400

CQ = "paid for the bicycle repair"                      # the words the model quotes from the claim
AQ = "returned in working order"                        # and from the answer


def set_time(vm, seconds=0):
    stamp = (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vm.warp(stamp)
    module = sys.modules.get("genlayer.gl")
    if module is not None:
        module.message_raw["datetime"] = stamp


def low(address):
    return "0x" + bytes(address).hex() if isinstance(address, (bytes, bytearray)) else str(address).lower()


def person(name):
    return create_address(name)


def claim_text(token):
    return "[%s] I %s on 3 March and the shop never gave the bike back to me." % (token, CQ)


def answer_text(token):
    return "[%s] The shop says the bicycle was %s on 5 March and the customer signed for it." % (token, AQ)


def reading(winner, q1="", q2=""):
    return json.dumps({"winner": winner, "quote_1": q1, "quote_2": q2})


def mock_orders(vm, n, a_side, b_side):
    """Order A has the claim first, order B the answer first. Sides are what each reading picks: CLAIMANT,
    RESPONDENT or NONE."""
    ca, aa = "C%d" % n, "A%d" % n
    pick_a = {"CLAIMANT": 1, "RESPONDENT": 2, "NONE": 0}[a_side]
    pick_b = {"RESPONDENT": 1, "CLAIMANT": 2, "NONE": 0}[b_side]
    vm.mock_llm(r"FIRST STATEMENT ---\n\[%s\]" % ca, reading(pick_a, CQ if pick_a else "", AQ if pick_a else ""))
    vm.mock_llm(r"FIRST STATEMENT ---\n\[%s\]" % aa, reading(pick_b, AQ if pick_b else "", CQ if pick_b else ""))


@pytest.fixture
def court(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    set_time(direct_vm, 0)
    c = direct_deploy(CONTRACT)
    set_time(direct_vm, 0)
    return c


class Case:
    """One case between a claimant and a respondent; every call sets the sender and the time first."""

    def __init__(self, vm, c, n=1, claimant="ann", respondent="ben", title="Bicycle repair that was never returned"):
        self.vm, self.c, self.n = vm, c, n
        self.ann, self.ben = person(claimant), person(respondent)
        self.now = 0
        vm.sender = self.ann
        set_time(vm, 0)
        self.id = json.loads(c.file_claim(low(self.ben), title, claim_text("C%d" % n)))["id"]

    def at(self, seconds):
        self.now = seconds
        return self

    def call(self, who, name, *args):
        self.vm.sender = who
        set_time(self.vm, self.now)
        return getattr(self.c, name)(self.id, *args)

    def answer(self, text=None):
        return json.loads(self.call(self.ben, "answer", text or answer_text("A%d" % self.n)))

    def state(self):
        return json.loads(self.c.get_case_json(self.id))

    def rule(self, who=None):
        return json.loads(self.call(who or self.ann, "rule"))

    def appeal(self, who):
        return json.loads(self.call(who, "appeal"))


@pytest.fixture
def one(direct_vm, court):
    return Case(direct_vm, court)


def answered(case, a_side="CLAIMANT", b_side="CLAIMANT"):
    mock_orders(case.vm, case.n, a_side, b_side)
    case.at(HOUR).answer()
    return case


# -- filing ---------------------------------------------------------------------------------------------------------------------

def test_deploy_is_empty(court):
    assert court.get_case_count() == 0
    assert json.loads(court.get_cases_page(0, 10)) == {"items": [], "total": 0}
    assert court.get_case_json(0) == "NONE" and court.get_case_json(-1) == "NONE" and court.get_case_json("0") == "NONE"


def test_a_new_case(one):
    case = one.state()
    assert case["id"] == 0 and case["claimant"] == low(one.ann) and case["respondent"] == low(one.ben)
    assert case["phase"] == "OPEN" and case["answer"] is None and case["winner"] is None and case["quotes"] == {}
    assert case["filed"] == int(T0.timestamp()) and case["answer_by"] == case["filed"] + 3 * DAY
    assert case["appeal"] is None and case["ruled"] is None and case["appeal_until"] is None and case["answered"] is None
    assert case["title"] == "Bicycle repair that was never returned" and case["claim"] == claim_text("C1")


def test_title_and_statement_are_squashed_and_limited(direct_vm, court):
    direct_vm.sender = person("ann")
    court.file_claim(low(person("ben")), "  A   title\nwith   gaps  ", "s" * 30)
    assert json.loads(court.get_case_json(0))["title"] == "A title with gaps"
    court.file_claim(low(person("ben")), "x" * 5, "y" * 600)
    court.file_claim(low(person("ben")), "z" * 80, "  " + "w" * 30 + "  ")
    for bad_title in ("abcd", "t" * 81, "", "   ", "bad\x01title here", 12):
        with direct_vm.expect_revert("invalid title"):
            court.file_claim(low(person("ben")), bad_title, "s" * 30)
    for bad_text in ("s" * 29, "s" * 601, "", "x" * 29 + "\x07", 7):
        with direct_vm.expect_revert("invalid statement"):
            court.file_claim(low(person("ben")), "A fine title", bad_text)


@pytest.mark.parametrize("other", ["", "0x12", "ben", "0x" + "z" * 40, 5])
def test_the_other_side_must_be_an_address(direct_vm, court, other):
    direct_vm.sender = person("ann")
    with direct_vm.expect_revert("invalid address"):
        court.file_claim(other, "A fine title", "s" * 30)


def test_you_cannot_file_against_yourself_in_any_letter_case(direct_vm, court):
    direct_vm.sender = person("ann")
    with direct_vm.expect_revert("the other side must be a different address"):
        court.file_claim("  " + low(person("ann")).upper().replace("0X", "0x") + " ", "A fine title", "s" * 30)


def test_three_unfinished_cases_per_claimant(direct_vm, court):
    cases = [Case(direct_vm, court, n, respondent="r%d" % n) for n in range(3)]
    direct_vm.sender = person("ann")
    with direct_vm.expect_revert("too many unfinished cases of yours"):
        court.file_claim(low(person("r9")), "A fine title", "s" * 30)
    direct_vm.sender = person("ann")
    court.withdraw(cases[0].id)                                    # a finished case frees a place
    court.file_claim(low(person("r9")), "A fine title", "s" * 30)


def test_a_ruled_case_no_longer_counts_as_unfinished(direct_vm, court):
    cases = [Case(direct_vm, court, n, respondent="r%d" % n) for n in range(3)]
    answered(cases[0])
    cases[0].rule()
    cases[1].at(4 * DAY)
    direct_vm.sender = person("ann")
    set_time(direct_vm, 0)
    court.file_claim(low(person("r9")), "A fine title", "s" * 30)


def test_five_unfinished_cases_against_one_respondent(direct_vm, court):
    for n in range(5):
        Case(direct_vm, court, n, claimant="c%d" % n, respondent="ben")
    direct_vm.sender = person("late")
    with direct_vm.expect_revert("too many unfinished cases against that address"):
        court.file_claim(low(person("ben")), "A fine title", "s" * 30)
    direct_vm.sender = person("ben")
    court.file_claim(low(person("late")), "A counter claim", "s" * 30)       # ben can still file against others


def test_the_board_holds_a_hundred_cases(direct_vm, court):
    for i in range(100):
        direct_vm.sender = person("c%d" % (i // 3))
        court.file_claim(low(person("r%d" % (i // 5))), "A fine title", "s" * 30)
    direct_vm.sender = person("last")
    with direct_vm.expect_revert("the board is full"):
        court.file_claim(low(person("other")), "A fine title", "s" * 30)
    assert court.get_case_count() == 100


# -- answering -----------------------------------------------------------------------------------------------------------------------

def test_the_respondent_answers(one):
    one.at(HOUR)
    assert one.answer() == {"status": "ANSWERED"}
    case = one.state()
    assert case["phase"] == "ANSWERED" and case["answer"] == answer_text("A1") and case["answered"] == int(T0.timestamp()) + HOUR


def test_only_the_respondent_can_answer(one, direct_vm):
    for who in (one.ann, person("carl")):
        with direct_vm.expect_revert("only the respondent can answer"):
            one.call(who, "answer", answer_text("A1"))


def test_an_answer_is_checked_and_can_be_given_once(one, direct_vm):
    for bad in ("short", "x" * 601, 5, "q" * 29):
        with direct_vm.expect_revert("invalid statement"):
            one.call(one.ben, "answer", bad)
    one.answer()
    with direct_vm.expect_revert("the case is not waiting for an answer"):
        one.answer()


def test_the_answer_window_is_three_days(one, direct_vm):
    one.at(3 * DAY - 1)
    one.answer()
    other = Case(direct_vm, one.c, 2, claimant="x1", respondent="x2")
    other.at(3 * DAY)
    with direct_vm.expect_revert("the time to answer has passed"):
        other.answer()


def test_an_unanswered_case_is_closed_with_no_winner(one, direct_vm):
    one.at(3 * DAY - 1)
    with direct_vm.expect_revert("the time to answer has not passed"):
        one.call(person("carl"), "close_unanswered")
    one.at(3 * DAY)
    assert json.loads(one.call(person("carl"), "close_unanswered")) == {"status": "UNANSWERED"}
    case = one.state()
    assert case["phase"] == "UNANSWERED" and case["winner"] is None and case["answer"] is None
    with direct_vm.expect_revert("the case is not waiting for an answer"):
        one.call(person("carl"), "close_unanswered")
    with direct_vm.expect_revert("the case is not waiting for an answer"):
        one.answer()
    with direct_vm.expect_revert("the case is not ready for a ruling"):
        one.rule()


def test_an_answered_case_cannot_be_closed_as_unanswered(one, direct_vm):
    one.at(HOUR)
    one.answer()
    one.at(10 * DAY)
    with direct_vm.expect_revert("the case is not waiting for an answer"):
        one.call(one.ann, "close_unanswered")


# -- withdrawing -------------------------------------------------------------------------------------------------------------------

def test_the_claimant_can_withdraw_before_a_ruling(one, direct_vm):
    with direct_vm.expect_revert("only the claimant can withdraw"):
        one.call(one.ben, "withdraw")
    assert json.loads(one.call(one.ann, "withdraw")) == {"status": "WITHDRAWN"}
    assert one.state()["phase"] == "WITHDRAWN"
    with direct_vm.expect_revert("the case is closed"):
        one.call(one.ann, "withdraw")
    with direct_vm.expect_revert("the case is not waiting for an answer"):
        one.answer()


def test_an_answered_case_can_still_be_withdrawn_but_not_a_ruled_one(direct_vm, court):
    first = answered(Case(direct_vm, court, 1))
    first.call(first.ann, "withdraw")
    second = answered(Case(direct_vm, court, 2, claimant="c2", respondent="r2"))
    second.rule()
    with direct_vm.expect_revert("the case is closed"):
        second.call(second.ann, "withdraw")
    third = Case(direct_vm, court, 3, claimant="c3", respondent="r3")
    third.at(5 * DAY)
    third.call(person("z"), "close_unanswered")
    with direct_vm.expect_revert("the case is closed"):
        third.call(third.ann, "withdraw")


# -- the ruling -----------------------------------------------------------------------------------------------------------------------

COMBOS = [   # (reading with the claim first, reading with the answer first) -> the outcome
    ("CLAIMANT", "CLAIMANT", "CLAIMANT"), ("RESPONDENT", "RESPONDENT", "RESPONDENT"),
    ("CLAIMANT", "RESPONDENT", "UNDECIDED"), ("RESPONDENT", "CLAIMANT", "UNDECIDED"),
    ("NONE", "NONE", "UNDECIDED"), ("CLAIMANT", "NONE", "UNDECIDED"), ("NONE", "CLAIMANT", "UNDECIDED"),
    ("RESPONDENT", "NONE", "UNDECIDED"), ("NONE", "RESPONDENT", "UNDECIDED"),
]


@pytest.mark.parametrize("a_side,b_side,expected", COMBOS)
def test_a_side_wins_only_when_both_readings_agree(one, a_side, b_side, expected):
    answered(one, a_side, b_side)
    out = one.rule()
    assert out["winner"] == expected
    case = one.state()
    assert case["phase"] == "RULED" and case["winner"] == expected and case["ruled"] == int(T0.timestamp()) + HOUR
    assert case["appeal_until"] == case["ruled"] + 3 * DAY
    if expected == "UNDECIDED":
        assert out["quotes"] == {} and case["quotes"] == {}
    else:
        assert out["quotes"] == {"claimant": CQ, "respondent": AQ} == case["quotes"]


def test_the_ruling_can_be_asked_for_by_anyone_but_only_once(one, direct_vm):
    answered(one)
    assert one.rule(person("stranger"))["winner"] == "CLAIMANT"
    with direct_vm.expect_revert("the case is not ready for a ruling"):
        one.rule()


def test_a_case_without_an_answer_cannot_be_ruled(one, direct_vm):
    with direct_vm.expect_revert("the case is not ready for a ruling"):
        one.rule()


def test_both_orders_are_asked_with_neutral_labels(one):
    """Each prompt shows only FIRST/SECOND; the order flips between the two readings."""
    one.vm.mock_llm(r"--- TITLE ---\nBicycle repair that was never returned\n--- FIRST STATEMENT ---\n\[C1\].*\n--- END FIRST STATEMENT ---\n--- SECOND STATEMENT ---\n\[A1\]",
                    reading(1, CQ, AQ))
    one.vm.mock_llm(r"--- FIRST STATEMENT ---\n\[A1\].*\n--- END FIRST STATEMENT ---\n--- SECOND STATEMENT ---\n\[C1\]",
                    reading(2, AQ, CQ))
    one.at(HOUR).answer()
    assert one.rule()["winner"] == "CLAIMANT"


def test_the_prompt_never_names_claimant_or_respondent(one):
    one.vm.mock_llm(r"(?is)\A(?!.*(claimant|respondent|plaintiff|defendant)).*FIRST STATEMENT", reading(0))
    one.at(HOUR).answer()
    assert one.rule()["winner"] == "UNDECIDED"


BAD_ORDER_A = [
    "not json", "", json.dumps([]), json.dumps({"winner": 1, "quote_1": CQ}),
    json.dumps({"winner": 1, "quote_1": CQ, "quote_2": AQ, "why": "x"}),
    json.dumps({"winner": 3, "quote_1": CQ, "quote_2": AQ}), json.dumps({"winner": -1, "quote_1": CQ, "quote_2": AQ}),
    json.dumps({"winner": True, "quote_1": CQ, "quote_2": AQ}), json.dumps({"winner": "1", "quote_1": CQ, "quote_2": AQ}),
    json.dumps({"winner": None, "quote_1": CQ, "quote_2": AQ}),
    json.dumps({"winner": 1, "quote_1": AQ, "quote_2": CQ}),                         # quotes swapped between statements
    json.dumps({"winner": 1, "quote_1": CQ, "quote_2": "words nobody wrote"}),
    json.dumps({"winner": 1, "quote_1": "not in the claim", "quote_2": AQ}),
    json.dumps({"winner": 1, "quote_1": "paid fo", "quote_2": AQ}),                  # too short (7 characters)
    json.dumps({"winner": 1, "quote_1": CQ, "quote_2": ""}),
    json.dumps({"winner": 1, "quote_1": "", "quote_2": ""}),
    json.dumps({"winner": 1, "quote_1": 5, "quote_2": AQ}),
    json.dumps({"winner": 1, "quote_1": CQ * 20, "quote_2": AQ}),
    json.dumps({"winner": 0, "quote_1": CQ, "quote_2": ""}),
    json.dumps({"winner": 0, "quote_1": "", "quote_2": AQ}),
    "x" * 4001,
]


@pytest.mark.parametrize("bad", BAD_ORDER_A)
def test_a_badly_formed_reading_is_not_a_ruling(one, direct_vm, bad):
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", bad)
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", reading(1, AQ, CQ))
    one.at(HOUR).answer()
    before = one.state()
    with direct_vm.expect_revert("the ruling could not be read"):
        one.rule()
    assert one.state() == before and before["phase"] == "ANSWERED"


def test_a_bad_second_reading_is_not_a_ruling_either(one, direct_vm):
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", reading(1, CQ, AQ))
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", "garbage")
    one.at(HOUR).answer()
    with direct_vm.expect_revert("the ruling could not be read"):
        one.rule()
    assert one.state()["phase"] == "ANSWERED"


def test_no_model_answer_at_all_is_not_a_ruling(one, direct_vm):
    one.at(HOUR).answer()
    with direct_vm.expect_revert("the ruling could not be read"):
        one.rule()


def test_quotes_may_differ_in_case_and_spacing(one):
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", reading(1, "PAID  FOR the bicycle\nrepair", "Returned In Working Order"))
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", reading(2, "returned in working order", "paid for the bicycle repair"))
    one.at(HOUR).answer()
    out = one.rule()
    assert out["winner"] == "CLAIMANT" and out["quotes"] == {"claimant": "PAID FOR the bicycle repair", "respondent": "Returned In Working Order"}


def test_quotes_of_eight_characters_pass_and_seven_do_not(one, direct_vm):
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", reading(1, "paid for", AQ))
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", reading(2, AQ, "paid for"))
    one.at(HOUR).answer()
    assert one.rule()["quotes"]["claimant"] == "paid for"


def test_a_long_quote_of_three_hundred_characters_passes(direct_vm, court):
    long_claim = "[C1] " + ("alpha beta gamma delta " * 14)[:300]
    direct_vm.sender = person("ann")
    set_time(direct_vm, 0)
    court.file_claim(low(person("ben")), "A long statement case", long_claim.ljust(30))
    quote = long_claim[5:305][:300].strip()
    direct_vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", reading(1, quote, AQ))
    direct_vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", reading(2, AQ, quote))
    direct_vm.sender = person("ben")
    set_time(direct_vm, HOUR)
    court.answer(0, answer_text("A1"))
    direct_vm.sender = person("ann")
    assert json.loads(court.rule(0))["winner"] == "CLAIMANT"


# -- appeals ---------------------------------------------------------------------------------------------------------------------------

def test_only_the_side_that_lost_can_appeal(one, direct_vm):
    answered(one)
    one.rule()
    for who in (one.ann, person("carl")):
        with direct_vm.expect_revert("only the side that lost can appeal"):
            one.appeal(who)


def test_an_appeal_that_comes_out_the_same_confirms_the_ruling(one):
    answered(one)
    first = one.rule()
    out = one.appeal(one.ben)
    assert out == {"result": "CONFIRMED", "winner": "CLAIMANT"}
    case = one.state()
    assert case["winner"] == "CLAIMANT" and case["quotes"] == first["quotes"]
    assert case["appeal"] == {"result": "CONFIRMED", "first": "CLAIMANT", "second": "CLAIMANT"}


def test_an_appeal_that_comes_out_differently_leaves_the_case_undecided(one):
    answered(one)
    one.rule()
    one.vm.clear_mocks()
    mock_orders(one.vm, 1, "RESPONDENT", "RESPONDENT")
    out = one.appeal(one.ben)
    assert out == {"result": "NOT_CONFIRMED", "winner": "UNDECIDED"}
    case = one.state()
    assert case["winner"] == "UNDECIDED" and case["quotes"] == {} and case["phase"] == "RULED"
    assert case["appeal"] == {"result": "NOT_CONFIRMED", "first": "CLAIMANT", "second": "RESPONDENT"}


def test_an_appeal_that_cannot_decide_leaves_the_case_undecided(one):
    answered(one)
    one.rule()
    one.vm.clear_mocks()
    mock_orders(one.vm, 1, "CLAIMANT", "RESPONDENT")
    assert one.appeal(one.ben)["result"] == "NOT_CONFIRMED"
    assert one.state()["appeal"]["second"] == "UNDECIDED"


def test_the_respondent_who_lost_and_the_claimant_who_lost_can_both_appeal(direct_vm, court):
    won_by_respondent = answered(Case(direct_vm, court, 1), "RESPONDENT", "RESPONDENT")
    won_by_respondent.rule()
    assert won_by_respondent.appeal(won_by_respondent.ann)["result"] == "CONFIRMED"


def test_a_ruling_can_be_appealed_once(one, direct_vm):
    answered(one)
    one.rule()
    one.appeal(one.ben)
    with direct_vm.expect_revert("this ruling was already appealed"):
        one.appeal(one.ben)


def test_the_appeal_window_is_three_days(one, direct_vm):
    answered(one)
    one.rule()
    one.at(HOUR + 3 * DAY - 1)
    assert one.appeal(one.ben)["result"] == "CONFIRMED"
    other = answered(Case(direct_vm, one.c, 2, claimant="x1", respondent="x2"))
    other.rule()
    other.at(HOUR + 3 * DAY)
    with direct_vm.expect_revert("the time to appeal has passed"):
        other.appeal(other.ben)


def test_there_is_nothing_to_appeal_before_a_ruling_or_after_an_undecided_one(one, direct_vm):
    with direct_vm.expect_revert("there is no ruling to appeal"):
        one.appeal(one.ben)
    answered(one, "CLAIMANT", "RESPONDENT")
    with direct_vm.expect_revert("there is no ruling to appeal"):
        one.appeal(one.ben)
    one.rule()
    for who in (one.ann, one.ben):
        with direct_vm.expect_revert("there is no ruling to appeal"):
            one.appeal(who)


def test_an_unreadable_appeal_is_not_recorded(one, direct_vm):
    answered(one)
    one.rule()
    one.vm.clear_mocks()
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", "garbage")
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", reading(1, AQ, CQ))
    with direct_vm.expect_revert("the ruling could not be read"):
        one.appeal(one.ben)
    assert one.state()["appeal"] is None and one.state()["winner"] == "CLAIMANT"
    one.vm.clear_mocks()
    mock_orders(one.vm, 1, "CLAIMANT", "CLAIMANT")
    assert one.appeal(one.ben)["result"] == "CONFIRMED"


# -- views ---------------------------------------------------------------------------------------------------------------------------

def test_pages_and_bad_pages(direct_vm, court):
    for n in range(4):
        Case(direct_vm, court, n, claimant="c%d" % n, respondent="r%d" % n)
    page = json.loads(court.get_cases_page(1, 2))
    assert page["total"] == 4 and [c["id"] for c in page["items"]] == [1, 2]
    assert set(page["items"][0]) == {"id", "title", "claimant", "respondent", "phase", "winner", "filed"}
    assert json.loads(court.get_cases_page(4, 5))["items"] == []
    for bad in [(-1, 5), (0, 0), (0, 51), ("0", 5), (0, "5")]:
        with direct_vm.expect_revert("bad page"):
            court.get_cases_page(*bad)
    assert len(json.loads(court.get_cases_page(0, 50))["items"]) == 4


def test_unknown_cases_are_refused_by_every_call(one, direct_vm):
    for name, args in (("answer", (answer_text("A1"),)), ("close_unanswered", ()), ("withdraw", ()), ("rule", ()), ("appeal", ())):
        for bad in (5, -1, "0"):
            direct_vm.sender = one.ann
            with direct_vm.expect_revert("unknown case"):
                getattr(one.c, name)(bad, *args) if args else getattr(one.c, name)(bad)


def test_records_count_what_happened(direct_vm, court):
    ann, ben = person("ann"), person("ben")
    # case 0: ann wins against ben; case 1: ben (as claimant) loses to ann; case 2: ann's case goes unanswered;
    # case 3: ann withdraws; case 4: undecided
    c0 = answered(Case(direct_vm, court, 0, "ann", "ben"))
    c0.rule()
    c1 = Case(direct_vm, court, 1, "ben", "ann")
    mock_orders(direct_vm, 1, "RESPONDENT", "RESPONDENT")
    c1.at(HOUR).call(ann, "answer", answer_text("A1"))
    c1.rule()
    c2 = Case(direct_vm, court, 2, "ann", "ben")
    c2.at(4 * DAY).call(ben, "close_unanswered")
    c3 = Case(direct_vm, court, 3, "ann", "ben")
    c3.call(ann, "withdraw")
    c4 = answered(Case(direct_vm, court, 4, "ann", "ben"), "CLAIMANT", "RESPONDENT")
    c4.rule()
    record = json.loads(court.get_record_json(low(ann)))
    assert record == {"claimant": {"filed": 4, "won": 1, "lost": 0, "undecided": 1, "unanswered": 1, "withdrawn": 1},
                      "respondent": {"answered": 1, "won": 1, "lost": 0, "undecided": 0, "unanswered": 0}}
    record = json.loads(court.get_record_json(low(ben)))
    assert record == {"claimant": {"filed": 1, "won": 0, "lost": 1, "undecided": 0, "unanswered": 0, "withdrawn": 0},
                      "respondent": {"answered": 2, "won": 0, "lost": 1, "undecided": 1, "unanswered": 1}}
    assert json.loads(court.get_record_json(low(person("nobody")))) == {
        "claimant": {"filed": 0, "won": 0, "lost": 0, "undecided": 0, "unanswered": 0, "withdrawn": 0},
        "respondent": {"answered": 0, "won": 0, "lost": 0, "undecided": 0, "unanswered": 0}}
    with direct_vm.expect_revert("invalid address"):
        court.get_record_json("ann")
    upper = "0x" + low(ann)[2:].upper()
    assert json.loads(court.get_record_json(upper))["claimant"]["filed"] == 4


def test_an_appeal_that_flips_a_win_into_undecided_moves_the_record(direct_vm, court):
    case = answered(Case(direct_vm, court, 1))
    case.rule()
    direct_vm.clear_mocks()
    mock_orders(direct_vm, 1, "RESPONDENT", "RESPONDENT")
    case.appeal(case.ben)
    record = json.loads(court.get_record_json(low(case.ann)))["claimant"]
    assert record["won"] == 0 and record["undecided"] == 1


# -- the validators ----------------------------------------------------------------------------------------------------------------------

def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


RD = ["CLAIMANT", "CLAIMANT"]
WIN = {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ}, "reads": RD}
UNDECIDED = {"state": "OK", "winner": "UNDECIDED", "quotes": {}, "reads": ["CLAIMANT", "RESPONDENT"]}


def ruled(one, a_side="CLAIMANT", b_side="CLAIMANT"):
    answered(one, a_side, b_side)
    one.rule()


def test_validator_accepts_the_same_winner_even_with_other_words(one):
    ruled(one)
    assert one.vm.run_validator() is True
    other = {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": "never gave the bike back", "respondent": "customer signed for it"}, "reads": RD}
    assert one.vm.run_validator(leader_result=canon(other)) is True


def test_validator_accepts_the_same_undecided(one):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator() is True
    assert one.vm.run_validator(leader_result=canon(UNDECIDED)) is True


def test_validator_rejects_a_winner_its_own_readings_do_not_give(one):
    ruled(one)
    assert one.vm.run_validator(leader_result=canon({"state": "OK", "winner": "RESPONDENT",
                                                      "quotes": {"claimant": CQ, "respondent": AQ}, "reads": ["RESPONDENT", "RESPONDENT"]})) is False
    assert one.vm.run_validator(leader_result=canon(UNDECIDED)) is False


def test_validator_rejects_a_win_where_its_readings_disagree(one):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator(leader_result=canon(WIN)) is False


@pytest.mark.parametrize("forged", [
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": "nothing like it", "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": CQ}, "reads": RD},  # claim words credited to the answer
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": AQ, "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": "paid fo", "respondent": AQ}, "reads": RD},  # too short
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ.upper(), "respondent": AQ}, "reads": RD},  # not canonical spacing is fine, case is kept as written: still anchored
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ, "extra": "x"}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": [], "reads": RD},
    {"state": "OK", "winner": "UNDECIDED", "quotes": {"claimant": CQ, "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "NONE", "quotes": {}, "reads": RD},
    {"state": "OK", "winner": 1, "quotes": {"claimant": CQ, "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": 5, "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": "paid  for the bicycle repair", "respondent": AQ}, "reads": RD},  # not squashed
    {"state": "OK", "winner": "CLAIMANT", "reads": RD},
    {"winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ}, "reads": RD},
    {"state": "MAYBE", "winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ}, "reads": RD},
    {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ}, "why": "x", "reads": RD},
    [],
])
def test_validator_rejects_forged_readings(one, forged):
    ruled(one)
    expected = forged != {"state": "OK", "winner": "CLAIMANT", "quotes": {"claimant": CQ.upper(), "respondent": AQ}, "reads": RD}
    assert one.vm.run_validator(leader_result=canon(forged)) is (not expected)


def test_validator_rejects_text_that_is_not_the_canonical_json(one):
    ruled(one)
    assert one.vm.run_validator(leader_result=json.dumps(WIN, indent=2)) is False
    assert one.vm.run_validator(leader_result="not json") is False
    assert one.vm.run_validator(leader_result=5) is False
    assert one.vm.run_validator(leader_result="x" * 2001) is False


def test_validator_rejects_an_error_when_it_can_read(one):
    ruled(one)
    assert one.vm.run_validator(leader_result=canon({"state": "ERROR"})) is False


def test_validator_rejects_a_reading_when_its_own_model_fails(one):
    ruled(one)
    one.vm.clear_mocks()
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", "garbage")
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", "garbage")
    assert one.vm.run_validator() is False


def test_validator_rejects_a_reading_when_only_one_of_its_two_readings_fails(one):
    ruled(one)
    one.vm.clear_mocks()
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", reading(1, CQ, AQ))
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", "garbage")
    assert one.vm.run_validator() is False


def test_validator_accepts_error_when_it_cannot_read_either(one):
    ruled(one)
    one.vm.clear_mocks()
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[C1\]", "garbage")
    one.vm.mock_llm(r"FIRST STATEMENT ---\n\[A1\]", "garbage")
    assert one.vm.run_validator(leader_result=canon({"state": "ERROR"})) is True


def test_the_appeal_uses_the_same_validator_rules(one):
    ruled(one)
    one.appeal(one.ben)
    assert one.vm.run_validator() is True
    assert one.vm.run_validator(leader_result=canon(UNDECIDED)) is False


# -- random sequences against a written-out reference ----------------------------------------------------------------------------------

SIDES = ("CLAIMANT", "RESPONDENT", "NONE")


def reference_outcome(a_side, b_side):
    return a_side if a_side == b_side and a_side != "NONE" else "UNDECIDED"


@pytest.mark.parametrize("seed", range(8))
def test_random_cases_match_the_reference(direct_vm, court, seed):
    rnd = random.Random(seed)
    expected = {}
    for n in range(12):
        who_c, who_r = "c%d_%d" % (seed, n), "r%d_%d" % (seed, n)
        case = Case(direct_vm, court, n, who_c, who_r)
        fate = rnd.choice(["ruled", "ruled", "ruled", "unanswered", "withdrawn", "appealed"])
        if fate in ("unanswered", "withdrawn"):
            if fate == "unanswered":
                case.at(4 * DAY).call(person("any"), "close_unanswered")
            else:
                case.call(case.ann, "withdraw")
            expected[case.id] = ("UNANSWERED" if fate == "unanswered" else "WITHDRAWN", None)
            continue
        a_side, b_side = rnd.choice(SIDES), rnd.choice(SIDES)
        answered(case, a_side, b_side)
        outcome = reference_outcome(a_side, b_side)
        assert case.rule()["winner"] == outcome
        if fate == "appealed" and outcome != "UNDECIDED":
            direct_vm.clear_mocks()
            a2, b2 = rnd.choice(SIDES), rnd.choice(SIDES)
            mock_orders(direct_vm, n, a2, b2)
            loser = case.ben if outcome == "CLAIMANT" else case.ann
            again = reference_outcome(a2, b2)
            result = case.appeal(loser)
            assert result["result"] == ("CONFIRMED" if again == outcome else "NOT_CONFIRMED")
            outcome = outcome if again == outcome else "UNDECIDED"
        expected[case.id] = ("RULED", outcome)
        direct_vm.clear_mocks()
    for case_id, (phase, winner) in expected.items():
        state = json.loads(court.get_case_json(case_id))
        assert state["phase"] == phase and state["winner"] == winner, (case_id, state["phase"], state["winner"])


# -- boundaries found by the mutation check ----------------------------------------------------------------------------------------------

def test_finished_cases_do_not_count_against_a_respondent(direct_vm, court):
    for n in range(5):
        case = Case(direct_vm, court, n, claimant="c%d" % n, respondent="ben")
        case.call(case.ann, "withdraw")
    direct_vm.sender = person("late")
    court.file_claim(low(person("ben")), "A fine title", "s" * 30)


def test_validator_survives_readings_of_the_wrong_json_type(one):
    ruled(one)
    assert one.vm.run_validator(leader_result=canon(["state", "winner", "quotes"])) is False
    assert one.vm.run_validator(leader_result=canon({"state": "OK", "winner": "CLAIMANT", "quotes": ["claimant", "respondent"], "reads": RD})) is False
    assert one.vm.run_validator(leader_result=canon("OK")) is False
    assert one.vm.run_validator(leader_result=canon(None)) is False


def test_validator_rejects_quotes_on_an_undecided_reading(one):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator(leader_result=canon(UNDECIDED)) is True
    forged = {"state": "OK", "winner": "UNDECIDED", "quotes": {"claimant": CQ, "respondent": AQ}, "reads": ["CLAIMANT", "RESPONDENT"]}
    assert one.vm.run_validator(leader_result=canon(forged)) is False



@pytest.mark.parametrize("reads", [
    [], ["CLAIMANT"], ["CLAIMANT", "CLAIMANT", "CLAIMANT"], ["CLAIMANT", "SOMEONE"], ["CLAIMANT", 1], "CLAIMANT", None,
    ["CLAIMANT", "RESPONDENT"],          # a win needs both readings on the winner
    ["RESPONDENT", "RESPONDENT"],
    ["NONE", "NONE"],
])
def test_validator_rejects_a_win_with_reads_that_do_not_back_it(one, reads):
    ruled(one)
    forged = dict(WIN, reads=reads)
    assert one.vm.run_validator(leader_result=canon(forged)) is False


@pytest.mark.parametrize("reads", [["CLAIMANT", "CLAIMANT"], ["RESPONDENT", "RESPONDENT"]])
def test_validator_rejects_undecided_when_both_reads_agree_on_a_side(one, reads):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator(leader_result=canon(dict(UNDECIDED, reads=reads))) is False


@pytest.mark.parametrize("reads", [["NONE", "NONE"], ["CLAIMANT", "NONE"], ["NONE", "RESPONDENT"], ["CLAIMANT", "RESPONDENT"], ["RESPONDENT", "CLAIMANT"]])
def test_undecided_accepts_every_split_or_empty_pair_of_reads(one, reads):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator(leader_result=canon(dict(UNDECIDED, reads=reads))) is True


def test_the_case_keeps_how_the_two_readings_came_out(one):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.state()["reads"] == ["CLAIMANT", "RESPONDENT"]


def test_the_case_keeps_the_reads_of_a_win(one):
    ruled(one)
    assert one.state()["reads"] == ["CLAIMANT", "CLAIMANT"]


def test_a_case_that_has_no_ruling_yet_has_no_reads(one):
    answered(one)
    assert one.state()["reads"] == []


@pytest.mark.parametrize("reads", [
    [], ["NONE"], ["NONE", "NONE", "NONE"], ["NONE", "SOMEONE"], ["SOMEONE", "NONE"], ["NONE", 0], "NONE", None, {},
])
def test_validator_rejects_an_undecided_reading_with_malformed_reads(one, reads):
    ruled(one, "CLAIMANT", "RESPONDENT")
    assert one.vm.run_validator(leader_result=canon(dict(UNDECIDED, reads=reads))) is False


def test_the_two_reads_of_an_undecided_case_keep_their_order(one):
    ruled(one, "CLAIMANT", "NONE")
    assert one.state()["reads"] == ["CLAIMANT", "NONE"]
