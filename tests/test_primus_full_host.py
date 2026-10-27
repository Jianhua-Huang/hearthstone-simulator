"""Real paid Primus and complete Rune inventories in the actual local host."""
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import primus_titan as native
from hs_sim.engine import CardClass,Game,PlayerSetup,Scenario,UseMinionAbility
from hs_sim.engine.pools import PoolQuery,resolve_candidates
from hs_sim.local_pool_format import build_cn37_local_pool_format


@lru_cache(None)
def format_for(role='writer'):
    return build_cn37_local_pool_format()


def registry(mode=None,role='writer'):
    return format_for(role).registry


class PrimusFullHostTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode=None

    def test_paid_native_skills_discover_complete_real_rune_candidates_and_restore_in_full_standard_host(self):
        fmt=format_for();expected_counts={'blood':24,'frost':19,'unholy':30}
        for skill,rune in native.RUNE_BY_SKILL.items():
            members=resolve_candidates(fmt.registry,fmt.context,native.POOL,PoolQuery(collectible=True,runes_any=(rune,)),
                current_class=CardClass.MAGE,source_card_id=native.CARD,player_id=1)
            ids={member.card_id for member in members}
            self.assertEqual(len(members),expected_counts[rune]);self.assertTrue(all(cid in fmt.registry.cards for cid in ids))
            g=Game.from_scenario(Scenario((
                PlayerSetup('HERO_08',hand=(native.CARD,),deck=('CORE_EX1_028',)*4,mana=10,max_mana=10),
                PlayerSetup('HERO_08',board=(native.TOKEN,),deck=('CORE_EX1_028',)*4)),
                seed=611,generation_context=fmt.context),fmt.registry)
            source=self.play(g,native.CARD);self.assertEqual(g.state.players[1].mana,2)
            target=self.entity(g,native.TOKEN,2,'board').id if skill==native.BLOOD else None
            g.apply(UseMinionAbility(1,source,skill,target));choice=g.state.pending_choice
            self.assertEqual(len(choice.options),3);self.assertTrue({o.card_id for o in choice.options}<=ids)
            restored=self.portable(g);key=choice.options[0].id;cid=choice.options[0].card_id
            self.choose(g,key);self.choose(restored,key);self.assertEqual(g.snapshot(),restored.snapshot())
            self.assertEqual(self.entity(g,cid).card_id,cid);self.assertEqual(g.state.players[1].mana,2)
            self.assertFalse(g.state.cast_history);self.assertEqual(len(g.state.play_history),1)


if __name__=='__main__':unittest.main()
