"""Real physical-zone effects; Steamcleaner starts from a real constructed opening."""
import json
from hs_sim.cards import build_registry
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardClass,DeckPolicy,DeckSpec,Game,MatchSetup,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

YETI='CORE_CS2_182';DOOM='CORE_EX1_310';CLEAN='CORE_REV_946';MUSTER='CORE_GVG_061'


def submit(g,p,choose):
    listing=g.for_player(p).legal_actions()
    reply=g.for_player(p).submit(dict(revision=listing['revision'],action=choose(listing)))
    assert reply['accepted'],reply


def play(g,cid):
    def choose(listing):
        own=next(p for p in listing['observation']['players']if p['id']==1)
        ref=next(c['ref']for c in own['hand']if c['card_id']==cid)
        return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==ref)
    submit(g,1,choose)


def steam_scene():
    cards=(CLEAN,'EDR_451',YETI)*4
    policy=DeckPolicy('k30.native.experimental','local-2026-09-23','experimental',
        (CLEAN,'EDR_451',YETI),deck_size=12,max_copies=4)
    setup=MatchSetup(tuple(DeckSpec('HERO_04','HERO_04bp',CardClass.PALADIN,cards)for _ in(1,2)),
        policy,'GAME_005',seed=430,first_player=1)
    g=Game.from_decks(setup,build_registry());checkpoints=[]
    def check(label):
        saved=g.snapshot();assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert g.clone().snapshot()==saved and replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append(label)
    while g.state.pending_choice:
        submit(g,g.state.pending_choice.player_id,lambda listing:listing['actions'][0])
    check('constructed_opening')
    while g.state.active_player!=1 or g.state.players[1].max_mana<6:
        submit(g,g.state.active_player,lambda listing:next(a for a in listing['actions']if a['type']=='end_turn'))
    play(g,'EDR_451')
    submit(g,1,lambda listing:next(a for a in listing['actions']if a['type']=='use_hero_power'))
    check('real_imbue_portals')
    for p in(1,2):submit(g,p,lambda listing:next(a for a in listing['actions']if a['type']=='end_turn'))
    # The second use guarantees fresh real Portals even if earlier Portals were drawn.
    submit(g,1,lambda listing:next(a for a in listing['actions']if a['type']=='use_hero_power'))
    original={eid for group in g.state.opening.original_entities for eid in group}
    targets={eid for p in(1,2)for eid in g.state.players[p].deck if eid not in original}
    assert len(targets)>=2 and all(g.state.entities[eid].card_id=='EDR_445pt3'for eid in targets)
    check('captured_portal_inventory');play(g,CLEAN)
    assert all(g.state.entities[eid].zone.value=='graveyard'for eid in targets)
    assert all(eid in original for p in(1,2)for eid in g.state.players[p].deck)
    check('destroyed_without_cast_or_discard')
    return dict(actions=len(g.history),checkpoints=checkpoints,destroyed_real_portals=len(targets),
        opening='Game.from_decks',lab_fixture_definitions=0)


def setup(hand):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=432)


def main():
    def doom(g,play,end,send):
        play(1,DOOM)
        assert len(g.state.discard_history)==2 and len(g.state.players[1].hand)==1
        def choose(listing):
            players={p['id']:p for p in listing['observation']['players']}
            source=next(c['ref']for c in players[1]['board']if c['card_id']==DOOM)
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==players[2]['hero']['ref'])
        send(1,choose);assert g.state.entities[g.state.players[2].hero_id].health==25
    first=session(setup((DOOM,YETI,YETI,YETI)),doom)
    def muster(g,play,end,send):
        play(1,MUSTER)
        assert len(g.state.players[1].board)==3
        assert(g.state.entities[g.state.players[1].weapon_id].card_id,
            g.state.entities[g.state.players[1].weapon_id].durability)==('CS2_091',4)
        def choose(listing):
            players={p['id']:p for p in listing['observation']['players']}
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==players[1]['hero']['ref']and a['defender']==players[2]['hero']['ref'])
        send(1,choose);assert g.state.entities[g.state.players[1].weapon_id].durability==3
    second=session(setup((MUSTER,)),muster);third=steam_scene();scenes=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=3,new_dependencies=1,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False,
        generation_limit='Existing experimental dragon pool; no full Standard generation certificate.')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
