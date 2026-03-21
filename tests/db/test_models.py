"""Unit tests for backend/db/models.py.

All four ORM classes are instantiated in memory — no database connection
is required.  Tests verify:
  - Default primary-key generation
  - Nullable vs non-nullable field contract
  - Correct Python types on each column
  - Foreign-key reference definition on Prediction
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.db.models import AgentReputation, Prediction, PriceSnapshot, Transcript


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


class TestTranscriptModel:
    def test_id_column_has_uuid_default_configured(self):
        """The id column must declare a callable default that produces UUIDs."""
        col = Transcript.__table__.c["id"]
        assert col.default is not None
        fn = col.default.arg
        assert fn.__name__ == "uuid4" and fn.__module__ == "uuid"

    def test_explicit_id_accepted(self):
        """An explicit UUID passed to the constructor is stored as-is."""
        explicit_id = uuid.uuid4()
        t = Transcript(ticker="AAPL", id=explicit_id)
        assert t.id == explicit_id

    def test_required_ticker_field(self):
        t = Transcript(ticker="NVDA")
        assert t.ticker == "NVDA"

    def test_optional_fields_default_to_none(self):
        t = Transcript(ticker="MSFT")
        assert t.fiscal_quarter is None
        assert t.filing_date is None
        assert t.transcript_text is None
        assert t.edgar_accession_number is None

    def test_optional_fields_accept_values(self):
        t = Transcript(
            ticker="NVDA",
            fiscal_quarter="Q3 2024",
            filing_date=date(2024, 8, 28),
            transcript_text="Good morning everyone...",
            edgar_accession_number="0001045810-24-000123",
        )
        assert t.fiscal_quarter == "Q3 2024"
        assert t.filing_date == date(2024, 8, 28)
        assert t.transcript_text.startswith("Good morning")
        assert t.edgar_accession_number == "0001045810-24-000123"

    def test_tablename(self):
        assert Transcript.__tablename__ == "transcripts"


# ---------------------------------------------------------------------------
# PriceSnapshot
# ---------------------------------------------------------------------------


class TestPriceSnapshotModel:
    def test_id_column_has_uuid_default_configured(self):
        col = PriceSnapshot.__table__.c["id"]
        assert col.default is not None
        fn = col.default.arg
        assert fn.__name__ == "uuid4" and fn.__module__ == "uuid"

    def test_required_fields(self):
        ps = PriceSnapshot(ticker="TSLA", snapshot_date=date(2024, 3, 1))
        assert ps.ticker == "TSLA"
        assert ps.snapshot_date == date(2024, 3, 1)

    def test_optional_price_fields_default_to_none(self):
        ps = PriceSnapshot(ticker="AAPL", snapshot_date=date(2024, 1, 1))
        assert ps.close_price is None
        assert ps.price_30d_later is None
        assert ps.actual_direction is None

    def test_optional_price_fields_accept_decimal(self):
        ps = PriceSnapshot(
            ticker="AAPL",
            snapshot_date=date(2024, 1, 1),
            close_price=Decimal("182.3200"),
            price_30d_later=Decimal("190.1000"),
            actual_direction="up",
        )
        assert ps.close_price == Decimal("182.3200")
        assert ps.price_30d_later == Decimal("190.1000")
        assert ps.actual_direction == "up"

    def test_tablename(self):
        assert PriceSnapshot.__tablename__ == "price_snapshots"


# ---------------------------------------------------------------------------
# AgentReputation
# ---------------------------------------------------------------------------


class TestAgentReputationModel:
    def test_id_column_has_uuid_default_configured(self):
        col = AgentReputation.__table__.c["id"]
        assert col.default is not None
        fn = col.default.arg
        assert fn.__name__ == "uuid4" and fn.__module__ == "uuid"

    def test_prediction_count_columns_have_zero_default(self):
        """correct_predictions and total_predictions declare a default of 0."""
        correct_col = AgentReputation.__table__.c["correct_predictions"]
        total_col = AgentReputation.__table__.c["total_predictions"]
        assert correct_col.default.arg == 0
        assert total_col.default.arg == 0

    def test_accuracy_and_weight_default_to_none(self):
        ar = AgentReputation(agent_name="technical")
        assert ar.accuracy is None
        assert ar.weight is None

    def test_accepts_updated_scores(self):
        ar = AgentReputation(
            agent_name="bull",
            correct_predictions=7,
            total_predictions=10,
            accuracy=Decimal("0.7000"),
            weight=Decimal("0.2500"),
        )
        assert ar.correct_predictions == 7
        assert ar.accuracy == Decimal("0.7000")
        assert ar.weight == Decimal("0.2500")

    def test_tablename(self):
        assert AgentReputation.__tablename__ == "agent_reputation"


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


class TestPredictionModel:
    def test_id_column_has_uuid_default_configured(self):
        col = Prediction.__table__.c["id"]
        assert col.default is not None
        fn = col.default.arg
        assert fn.__name__ == "uuid4" and fn.__module__ == "uuid"

    def test_required_ticker_field(self):
        p = Prediction(ticker="GOOG")
        assert p.ticker == "GOOG"

    def test_optional_fields_default_to_none(self):
        p = Prediction(ticker="AMZN")
        assert p.transcript_id is None
        assert p.final_direction is None
        assert p.final_confidence is None
        assert p.final_reasoning is None
        assert p.agent_reports is None
        assert p.debate_transcript is None
        assert p.weighted_signals is None
        assert p.actual_direction is None
        assert p.was_correct is None

    def test_accepts_full_payload(self):
        tid = uuid.uuid4()
        agent_reports = {"fundamentals": {"signal": "bullish"}}
        debate = [{"round": 1, "bull": "Strong revenue", "bear": "Weak margins"}]
        signals = {"fundamentals": 0.4, "sentiment": 0.3, "technical": 0.3}

        p = Prediction(
            ticker="NVDA",
            transcript_id=tid,
            final_direction="up",
            final_confidence=Decimal("0.7800"),
            final_reasoning="Bullish momentum confirmed by all analysts.",
            agent_reports=agent_reports,
            debate_transcript=debate,
            weighted_signals=signals,
            actual_direction="up",
            was_correct=True,
        )

        assert p.transcript_id == tid
        assert p.final_direction == "up"
        assert p.final_confidence == Decimal("0.7800")
        assert p.agent_reports["fundamentals"]["signal"] == "bullish"
        assert p.was_correct is True

    def test_transcript_id_foreign_key_column_exists(self):
        """Verify the FK is declared on the column (structural, not DB-level)."""
        col = Prediction.__table__.c["transcript_id"]
        fk_targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "transcripts.id" in fk_targets

    def test_tablename(self):
        assert Prediction.__tablename__ == "predictions"
