"""Small Claims Jury on a local GenLayer network (glsim, 5 validators): real leader/validator rounds, model mocked.

Every validator of the local network gets the same mocked model answers, so these tests show that the contract runs through
real consensus rounds (two readings per ruling, on every validator), not how a real model weighs two statements. glsim keeps
mocks for the whole run, so each test uses its own simulator and its own tokens.
"""
import json

import pytest

from rpc import RpcError, Sim

ANN = "0x1111111111111111111111111111111111111111"
BEN = "0x2222222222222222222222222222222222222222"
CARL = "0x3333333333333333333333333333333333333333"
T0 = "2026-11-01T10:00:00Z"
T1 = "2026-11-01T14:00:00Z"
T5 = "2026-11-05T10:00:00Z"
CQ = "paid for the bicycle repair"
AQ = "returned in working order"
CLAIM = "[C1] I %s on 3 March and the shop never gave the bike back to me." % CQ
ANSWER = "[A1] The shop says the bicycle was %s on 5 March and the customer signed for it." % AQ
TITLE = "Bicycle repair that was never returned"


@pytest.fixture
def sim():
    simulator = Sim()
    try:
        yield simulator
    finally:
        simulator.close()


def reading(winner, q1="", q2=""):
    return json.dumps({"winner": winner, "quote_1": q1, "quote_2": q2})


def mocks(sim, claim_first, answer_first):
    sim.rpc("sim_installMocks", web_mocks={}, llm_mocks={
        "FIRST STATEMENT ---\\n\\[C1\\]": claim_first, "FIRST STATEMENT ---\\n\\[A1\\]": answer_first})


def say(sim, contract, method, who, *args):
    out = sim.call(contract, method, list(args), who)
    return json.loads(out) if isinstance(out, str) and out[:1] == "{" else out


def start(sim):
    sim.set_time(T0)
    contract = sim.deploy("contracts/small_claims_jury.py", [], ANN)
    case = say(sim, contract, "file_claim", ANN, BEN, TITLE, CLAIM)["id"]
    return contract, case


def test_a_case_from_claim_to_confirmed_ruling_through_five_validators(sim):
    contract, case = start(sim)
    mocks(sim, reading(1, CQ, AQ), reading(2, AQ, CQ))             # both orders pick the claimant
    sim.set_time(T1)
    assert say(sim, contract, "answer", BEN, case, ANSWER) == {"status": "ANSWERED"}
    ruling = say(sim, contract, "rule", CARL, case)
    assert ruling == {"winner": "CLAIMANT", "quotes": {"claimant": CQ, "respondent": AQ}}
    assert say(sim, contract, "appeal", BEN, case) == {"result": "CONFIRMED", "winner": "CLAIMANT"}
    state = sim.read_json(contract, "get_case_json", [case])
    assert state["phase"] == "RULED" and state["winner"] == "CLAIMANT"
    assert state["appeal"] == {"result": "CONFIRMED", "first": "CLAIMANT", "second": "CLAIMANT"}
    record = sim.read_json(contract, "get_record_json", [ANN])
    assert record["claimant"]["won"] == 1 and record["claimant"]["filed"] == 1


def test_a_leaning_towards_the_first_statement_ends_undecided(sim):
    contract, case = start(sim)
    mocks(sim, reading(1, CQ, AQ), reading(1, AQ, CQ))             # always picks whatever is shown first
    sim.set_time(T1)
    say(sim, contract, "answer", BEN, case, ANSWER)
    ruling = say(sim, contract, "rule", ANN, case)
    assert ruling == {"winner": "UNDECIDED", "quotes": {}}
    assert sim.read_json(contract, "get_case_json", [case])["winner"] == "UNDECIDED"
    with pytest.raises(RpcError):
        say(sim, contract, "appeal", BEN, case)                    # nothing to appeal


def test_a_quote_credited_to_the_wrong_statement_is_not_a_ruling(sim):
    contract, case = start(sim)
    mocks(sim, reading(1, AQ, CQ), reading(2, AQ, CQ))             # first reading swaps the quotes
    sim.set_time(T1)
    say(sim, contract, "answer", BEN, case, ANSWER)
    before = sim.read(contract, "get_case_json", [case])
    with pytest.raises(RpcError):
        say(sim, contract, "rule", ANN, case)
    assert sim.read(contract, "get_case_json", [case]) == before


def test_a_badly_formed_second_reading_changes_nothing(sim):
    contract, case = start(sim)
    mocks(sim, reading(1, CQ, AQ), "I would say the shop is right.")
    sim.set_time(T1)
    say(sim, contract, "answer", BEN, case, ANSWER)
    with pytest.raises(RpcError):
        say(sim, contract, "rule", ANN, case)
    assert sim.read_json(contract, "get_case_json", [case])["phase"] == "ANSWERED"


def test_timing_and_roles_are_enforced(sim):
    contract, case = start(sim)
    with pytest.raises(RpcError):
        say(sim, contract, "answer", CARL, case, ANSWER)           # not the respondent
    with pytest.raises(RpcError):
        say(sim, contract, "close_unanswered", CARL, case)         # too early
    sim.set_time(T5)
    with pytest.raises(RpcError):
        say(sim, contract, "answer", BEN, case, ANSWER)            # too late
    assert say(sim, contract, "close_unanswered", CARL, case) == {"status": "UNANSWERED"}
    assert sim.read_json(contract, "get_case_json", [case])["winner"] is None
    record = sim.read_json(contract, "get_record_json", [BEN])
    assert record["respondent"]["unanswered"] == 1
