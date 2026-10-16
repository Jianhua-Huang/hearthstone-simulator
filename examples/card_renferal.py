"""Renferal's two real plays and one actual opponent turn through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.hand_play_locks import play_error
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    root='EDR_526';plain='CORE_CS2_182'
    setup=Scenario((PlayerSetup('HERO_08',hand=(root,'EDR_523'),deck=(plain,)*8,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',hand=(plain,)*3,deck=(plain,)*8,mana=60,max_mana=60,mana_cap=60)),seed=1055)
    def run(g,play,end,submit):
        def marks():
            s=g.state;return[(i,e)for i in s.players[2].hand for e in s.entities[i].enchantments if e.hand_play_lock is not None]
        play(1,root);assert len(marks())==1;play(1,'EDR_523',target_card=root);play(1,root);assert len(marks())==3
        targets={i for i,_ in marks()};end(1);s=g.state
        assert all(play_error(s,s.entities[i])is not None for i in targets)
        listing=g.for_player(2).legal_actions();own=next(p for p in listing['observation']['players']if p['id']==2)
        refs={own['hand'][s.players[2].hand.index(i)]['ref']for i in targets}
        assert not any(a['type']=='play_card'and a['card']in refs for a in listing['actions'])
        end(2);end(1);s=g.state;assert all(play_error(s,s.entities[i])is None for i in targets)
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=1,lab_fixture_definitions=0,actions=row['actions'],checkpoints=len(row['checkpoints']),
        scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,7)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
