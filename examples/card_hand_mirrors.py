"""Real hand shuffle, hidden copy damage and full-board failure via player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';ASSAILANT='EDR_524';ILLUSION='EDR_780';FROSTBOLT='CORE_CS2_024'


def setup(hand,*,board=(),enemy_hand=(),seed=401):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=enemy_hand,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def shuffle(g,play,end,submit):
        original=g.state.players[2].hand[0]
        play(1,ASSAILANT)
        assert g.state.players[2].deck==[original]
        assert all(x.get('card_id')is None for x in g.observe(1)['players'][1]['hand'])
        end(1);assert original in g.state.players[2].hand
        play(2,YETI);assert original in g.state.players[2].board
    first=session(setup((ASSAILANT,YETI),enemy_hand=(YETI,'CORE_CS2_023')),shuffle)

    def illusions(g,play,end,submit):
        play(1,ILLUSION)
        # Target both visible slots in order, without consulting the secret flag.
        refs=[e['ref']for e in g.observe(1)['players'][0]['board']]
        assert len(refs)==2
        for target in refs:
            def action(listing,target=target):
                own=next(p for p in listing['observation']['players']if p['id']==1)
                card=next(c['ref']for c in own['hand']if c['card_id']==FROSTBOLT)
                return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card and a.get('target')==target)
            submit(1,action)
        assert len(g.state.players[1].board)==1
        survivor=g.state.entities[g.state.players[1].board[0]]
        assert survivor.health==1 and len(g.state.death_history)==1
        assert all(e['kind']not in('copy_followup_started','hidden_damage_pair_marked')for e in g.player_events(1))
    second=session(setup((ILLUSION,FROSTBOLT,FROSTBOLT),seed=402),illusions)

    def full(g,play,end,submit):
        before=g._rng.getstate();play(1,ILLUSION)
        assert len(g.state.players[1].board)==7 and g._rng.getstate()==before
        assert not any(e.kind=='hidden_damage_pair_marked'for e in g.events)
    third=session(setup((ILLUSION,),board=(YETI,)*6,seed=403),full)
    scenarios=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=2,new_dependencies=0,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(7,10)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
