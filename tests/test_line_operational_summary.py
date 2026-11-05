import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import logging_database as logs


@compiles(JSONB, "sqlite")
def compile_jsonb_for_test(_type, _compiler, **_kwargs):
    return "TEXT"


class LineOperationalSummaryTests(unittest.TestCase):
    def test_counts_only_reported_values_and_distinct_identifiers(self):
        engine = create_engine("sqlite://")
        logs.LineUtilizationLog.__table__.create(engine)
        session_factory = sessionmaker(bind=engine)
        observed_at = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

        with session_factory() as session:
            session.add_all([
                logs.LineUtilizationLog(id=1, city="grenoble", route_id="A", direction="outbound",
                                        trip_id="trip-1", vehicle_id="bus-1", boardings=4,
                                        occupancy=12, observed_at=observed_at),
                logs.LineUtilizationLog(id=2, city="grenoble", route_id="A", direction="outbound",
                                        trip_id="trip-1", vehicle_id="bus-1", alightings=2,
                                        occupancy=14, observed_at=observed_at),
                logs.LineUtilizationLog(id=3, city="grenoble", route_id="A", direction="outbound",
                                        trip_id="trip-2", boardings=0, observed_at=observed_at),
            ])
            session.commit()

        with patch.object(logs, "_get_session_factory", return_value=session_factory):
            result = logs.get_line_utilization_summary("test")

        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["eventCount"], 3)
        self.assertEqual(row["observedTripCount"], 2)
        self.assertEqual(row["observedVehicleCount"], 1)
        self.assertEqual(row["boardingSampleCount"], 2)
        self.assertEqual(row["alightingSampleCount"], 1)
        self.assertEqual(row["occupancySampleCount"], 2)
        self.assertEqual(row["totalBoardings"], 4)
        self.assertEqual(row["totalAlightings"], 2)
        self.assertEqual(row["averageOccupancy"], 13.0)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
