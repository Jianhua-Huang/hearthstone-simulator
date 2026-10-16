"""Six actual draw spells, including Armaments from a genuine match opening."""
import json

from hs_sim.cards import build_registry
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardClass, DeckPolicy, DeckSpec, Game, MatchSetup, PlayerSetup, Scenario
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

ROOT='MEND_043';FORWARD='TIME_770';BRIBE='JAIL_206';FLIGHT='TLC_222';HYBRID='TLC_236';ARMS='EDR_251'
YETI='CORE_CS2_182';CROC='CORE_CS2_120';MURLOC='CORE_EX1_506';ONE='CORE_EX1_008';THREE='TLC_242'


def setup(hand,deck,seed):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def original_match():
    ids=('EDR_852',ARMS,YETI);cards=(ids[0],)*4+(ids[1],)*4+(ids[2],)*4
    # Use the existing explicitly experimental pool's real target identity.
    # A made-up test target has no Emerald Dragon generation pool.
    policy=DeckPolicy('k44.native','local-2026-09-23','experimental',ids,deck_size=12,max_copies=12)
    g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_04','HERO_04bp',CardClass.PALADIN,cards)for _ in (1,2)),
        policy,'GAME_005',seed=944,first_player=1),build_registry());checkpoints=[]
    def check():
        saved=g.snapshot();assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert g.clone().snapshot()==saved and replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def submit(p,pick):
        listing=g.for_player(p).legal_actions();reply=g.for_player(p).submit(dict(revision=listing['revision'],action=pick(listing)))
        assert reply['accepted'],reply;check()
    def end(p):submit(p,lambda x:next(a for a in x['actions']if a['type']=='end_turn'))
    def play(cid):
        def pick(x):
            player=next(p for p in x['observation']['players']if p['id']==1)
            ref=next(c['ref']for c in player['hand']if c['card_id']==cid)
            return next(a for a in x['actions']if a['type']=='play_card'and a['card']==ref)
        submit(1,pick)
    check()
    while g.state.pending_choice:
        submit(g.state.pending_choice.player_id,lambda x:next(a for a in x['actions']if a['type']=='select_choice'and not a['options']))
    end(1);end(2);play('EDR_852');end(1);end(2)
    submit(1,lambda x:next(a for a in x['actions']if a['type']=='use_hero_power'))
    s=g.state;source=next(i for i in s.players[1].hand if s.entities[i].card_id==ARMS);play(ARMS);s=g.state
    rows=[d for d in s.draw_history if d.source_id==source]
    assert len(rows)==2 and rows[0].entity_id in s.opening.original_entities[0]
    assert rows[1].entity_id not in s.opening.original_entities[0]and rows[1].card_id=='EDR_445pt3'and rows[1].outcome=='cast'
    assert s.players[1].board and s.cast_history[-1].completed
    return dict(actions=len(g.history),checkpoints=checkpoints,actual_opening=True,original_root_draw=rows[0].id,
        generated_portal_draw=rows[1].id,formal_deck_certificate=False)


def main():
    def root(g,play,end,submit):
        play(1,ROOT);s=g.state
        assert len(s.draw_history)==2 and s.entities[s.players[1].hero_id].armor==6
    a=session(setup((ROOT,),(YETI,)*4,941),root)
    def forward(g,play,end,submit):
        original=g.state.players[1].deck[:2];play(1,FORWARD)
        assert [o.entity_id for o in g.state.pending_choice.options]==original
        submit(1,lambda x:next(a for a in x['actions']if a['type']=='select_choice'))
        s=g.state;prices=[quote_unselected_cost(s,g.registry,s.entities[i]).amount for i in original]
        assert sorted(prices)==[2,4]
    b=session(setup((FORWARD,),(YETI,YETI),942),forward)
    def bribe(g,play,end,submit):
        original=g.state.players[1].deck[:];play(1,BRIBE)
        submit(1,lambda x:next(a for a in x['actions']if a['type']=='select_choice'))
        s=g.state;given=[i for i in original if s.entities[i].controller==2]
        assert len(given)==1 and given[0]in s.players[2].hand and s.entities[given[0]].owner==1
    c=session(setup((BRIBE,),(YETI,CROC,THREE),943),bribe)
    def flight(g,play,end,submit):
        play(1,FLIGHT);s=g.state;cards=[s.entities[i]for i in s.players[1].hand]
        assert {e.card_id for e in cards}=={CROC,MURLOC}
        assert all(e.attack==e.base_attack+1 and e.max_health==e.base_health+1 for e in cards)
    d=session(setup((FLIGHT,),(CROC,MURLOC,YETI),944),flight)
    def hybrid(g,play,end,submit):
        play(1,'CORE_EX1_169');end(1);end(2)
        s=g.state;source=next(i for i in s.players[1].hand if s.entities[i].card_id==HYBRID);play(1,HYBRID);s=g.state
        rows=[r for r in s.draw_history if r.source_id==source]
        assert len(rows)==4
        assert all(quote_unselected_cost(s,g.registry,s.entities[r.entity_id]).amount==g.registry.card(r.card_id).cost-1 for r in rows)
    e=session(setup((HYBRID,'CORE_EX1_169'),(YETI,YETI,ONE,CROC,THREE,YETI),945),hybrid)
    f=original_match();scenarios=[a,b,c,d,e,f]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,new_dependencies=0,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(19,25)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
