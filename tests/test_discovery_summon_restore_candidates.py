"""Discovery-summon restoration retains the original typed candidate inventory."""
from dataclasses import asdict
import json
import unittest

from hs_sim.engine import CardType, DiscoverFromPool, PoolQuery, Zone
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.discovery_summons import spec_from_dict
from hs_sim.engine.summon_quantities import SummonCause


def request():
    source=SourceAllocationFact(1,'probe.source',CardType.MINION,1,1,Zone.BOARD,0,0,2,1)
    cause=SummonCause(source,1,1,0)
    return DiscoverFromPool(1,'probe',PoolQuery(kinds=(CardType.MINION,)),
        source_id=1,destination='board',cause=cause)


class DiscoverySummonRestoreCandidateTests(unittest.TestCase):
    def test_original_empty_fixed_inventory_roundtrips(self):
        original=request()
        wire=json.loads(json.dumps(asdict(original)))
        self.assertEqual(wire['fixed_candidates'],[])
        self.assertEqual(spec_from_dict(wire),original)

    def test_non_array_and_duplicate_inventories_remain_rejected(self):
        original=json.loads(json.dumps(asdict(request())))
        for malformed in (None,'',(),['same','same']):
            with self.subTest(value=malformed),self.assertRaises(ValueError):
                spec_from_dict({**original,'fixed_candidates':malformed})


if __name__=='__main__':unittest.main()
