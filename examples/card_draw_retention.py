"""Six actual draw restrictions/copies through player DTOs and full checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario,Zone
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

GODS='BE_EVENT_100';TITANS='BE_EVENT_101';BOUNTY='EDR_234';MIMIC='EDR_522';LADDER='TIME_031';DIVINE='EDR_804'
YETI='CORE_CS2_182';CROC='CORE_CS2_120';PENGUIN='CORE_ICC_023';WISP='EDR_851t';FIRE='CORE_CS2_029';INNERVATE='CORE_EX1_169'


def setup(hand,*,deck=(YETI,)*8,board=(),enemy_deck=(YETI,)*8,seed=951):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=enemy_deck,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def missing_play(g,cid):
    listing=g.for_player(1).legal_actions();player=next(p for p in listing['observation']['players']if p['id']==1)
    ref=next(c['ref']for c in player['hand']if c['card_id']==cid)
    assert not any(a['type']=='play_card'and a['card']==ref for a in listing['actions'])


def main():
    def gods(g,play,end,submit):
        play(1,GODS);assert g.state.players[1].mana==40;missing_play(g,FIRE);play(1,PENGUIN)
        end(1);end(2);play(1,FIRE,target_player=2);assert not g.state.players[1].player_effects
    a=session(setup((GODS,FIRE,PENGUIN),deck=(YETI,CROC)),gods)
    def titans(g,play,end,submit):
        play(1,TITANS);assert g.state.players[1].mana==40;missing_play(g,PENGUIN);play(1,INNERVATE)
        assert len(g.state.draw_history)==2 and all(d.card_id in (FIRE,INNERVATE)for d in g.state.draw_history)
    b=session(setup((TITANS,PENGUIN),deck=(FIRE,INNERVATE,YETI),seed=952),titans)
    def bounty(g,play,end,submit):
        original=g.state.players[1].deck[:2];play(1,BOUNTY);missing_play(g,YETI)
        s=g.state;assert all(quote_unselected_cost(s,g.registry,s.entities[i]).amount==4 for i in original)
        end(1);end(2);missing_play(g,YETI);end(1);end(2);play(1,YETI)
        assert g.state.entities[original[0]].zone==Zone.BOARD
    c=session(setup((BOUNTY,),seed=953),bounty)
    def mimic(g,play,end,submit):
        originals=g.state.players[2].deck[:2];play(1,MIMIC);s=g.state;copies=[s.entities[i]for i in s.players[1].hand]
        assert [e.origin_entity_id for e in copies]==originals and all(e.owner==e.controller==1 for e in copies)
        assert s.players[2].hand==originals and len(s.draw_history)==2
    d=session(setup((MIMIC,),enemy_deck=(YETI,CROC),seed=954),mimic)
    def ladder(g,play,end,submit):
        play(1,LADDER);s=g.state
        assert len(s.draw_history)==3 and len({g.registry.card(d.card_id).cost for d in s.draw_history})==3
    e=session(setup((LADDER,),deck=('CORE_EX1_008',CROC,CROC,'TLC_242',YETI),seed=955),ladder)
    def divine(g,play,end,submit):
        original=g.state.players[1].board[0];play(1,DIVINE,target_card=WISP);s=g.state
        assert s.entities[original].zone==Zone.GRAVEYARD and len(s.draw_history)==3 and not s.discard_history
    f=session(setup((DIVINE,),board=(WISP,),seed=956),divine)
    scenarios=[a,b,c,d,e,f];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=6,new_dependencies=0,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(16,22)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
