"""S12: the loader turns the dataset file into the Expected values."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harness.adapters.dataset_file import DATASET, load_dataset
from harness.domain.expected import Movement


def fixture(**overrides: object) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "dataset_version": 3,
        "holder": "Ana",
        "currency": "BRL",
        "accounts": {
            "acc-9001": {
                "checking_balance_cents": 220000,
                "bills": [],
                "investments": [],
                "operations": [],
            }
        },
        "cases": [
            {
                "id": "redeem-then-pay",
                "cluster": "short_balance",
                "account": "acc-9001",
                "turns": [
                    {"message": "Paga?", "executes": [], "judge": ["Pergunta"]},
                    {
                        "message": "Pode.",
                        "executes": [
                            {
                                "action": "redeem_investment",
                                "investment_id": "reserva",
                                "amount_cents": 80000,
                            },
                            {
                                "action": "pay_card_bill",
                                "bill_id": "bill-gold",
                                "amount_cents": 300000,
                            },
                        ],
                        "must_check": ["list_operations"],
                    },
                ],
                "final_state": {
                    "checking_balance_cents": 0,
                    "bill_paid_cents": {"bill-gold": 300000},
                    "investment_balance_cents": {"reserva": 70000},
                },
            }
        ],
    }
    raw.update(overrides)
    return raw


def write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(raw))
    return path


def test_ids_are_normalized_to_target_id(tmp_path: Path) -> None:
    dataset = load_dataset(write(tmp_path, fixture()))

    assert dataset.conversations[0].turns[1].executes == (
        Movement(action="redeem_investment", target_id="reserva", amount_cents=80000),
        Movement(action="pay_card_bill", target_id="bill-gold", amount_cents=300000),
    )
    assert dataset.conversations[0].turns[1].must_check == ("list_operations",)
    assert dataset.conversations[0].turns[0].must_check == ()


def test_the_identity_is_the_sha256_of_the_file_bytes(tmp_path: Path) -> None:
    path = write(tmp_path, fixture())

    assert load_dataset(path).sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_extra_keys_such_as_the_holdout_split_are_accepted(tmp_path: Path) -> None:
    raw = fixture(split="holdout")
    raw["cases"][0]["split"] = "holdout"
    raw["cases"][0]["turns"][1]["executes"][0]["note"] = "extra"

    assert len(load_dataset(write(tmp_path, raw)).conversations) == 1


@pytest.mark.parametrize("amount", [0, -1])
def test_a_movement_amount_must_be_positive(tmp_path: Path, amount: int) -> None:
    raw = fixture()
    raw["cases"][0]["turns"][1]["executes"][1]["amount_cents"] = amount

    with pytest.raises(ValidationError):
        load_dataset(write(tmp_path, raw))


def test_every_conversation_account_needs_a_fixture(tmp_path: Path) -> None:
    raw = fixture()
    raw["cases"][0]["account"] = "acc-9999"

    with pytest.raises(ValidationError, match="acc-9999"):
        load_dataset(write(tmp_path, raw))


def test_must_check_only_names_read_tools_that_exist(tmp_path: Path) -> None:
    raw = fixture()
    raw["cases"][0]["turns"][1]["must_check"] = ["list_statements"]

    with pytest.raises(ValidationError):
        load_dataset(write(tmp_path, raw))


def test_the_repository_dataset_has_13_conversations_of_2_turns() -> None:
    dataset = load_dataset(DATASET)

    assert len(dataset.conversations) == 13
    assert {len(conversation.turns) for conversation in dataset.conversations} == {2}
    assert len({conversation.account for conversation in dataset.conversations}) == 13
