"""Lasting costs/healing and an actual constructed Ysera opening, publicly driven."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from hs_sim.cards import build_registry
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardClass,DeckPolicy,DeckSpec,Game,MatchSetup,PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from examples.card_reactive_secrets import exercise


def power(submit,player):
    def choose(listing):
        enemy=next(p for p in listing['observation']['players']if p['id']==3-player)
        return next(a for a in listing['actions']if a['type']=='use_hero_power'and a.get('target')==enemy['hero']['ref'])
    submit(player,choose)


def main():
    def powers(g,play,end,submit):
        play(1,'CORE_DRG_403');s=g.state
        assert quote_cost(s,g.registry,s.entities[s.players[2].hero_power_id]).amount==4
        end(1);play(2,'EDR_847');before=g.state.players[2].mana;power(submit,2)
        assert g.state.players[2].mana==before and not g.state.players[2].cost_modifiers
        play(2,'CORE_CS2_024','EDR_847');assert len(g.state.players[2].cost_modifiers)==1
        end(2);end(1);before=g.state.players[2].mana;power(submit,2)
        assert g.state.players[2].mana==before and not g.state.players[2].cost_modifiers
    first=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_DRG_403',),deck=('CORE_CS2_182',)*8,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',hand=('EDR_847','CORE_CS2_024'),deck=('CORE_CS2_182',)*8,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=381),powers)

    def prices(g,play,end,submit):
        play(1,'TLC_257');s=g.state
        assert all(quote_cost(s,g.registry,s.entities[i]).amount==5 for i in s.players[1].hand if s.entities[i].kind.value=='minion')
        play(1,'CORE_CS2_182');before=g.state.players[1].mana;play(1,'EDR_000')
        assert g.state.players[1].mana==before-5
        assert g.state.players[1].mana_cap==40 and not any(e.kind=='opening_effect'for e in g.events)
    second=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('TLC_257','CORE_CS2_182','EDR_000','CORE_CS2_029'),
            deck=('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=382),prices)

    def healing(g,play,end,submit):
        play(1,'CATA_216');end(1);play(2,'CORE_CS2_029','CATA_216')
        end(2);end(1)
        submit(2,lambda listing:next(a for a in listing['actions']if a['type']=='play_card'and
            a['card']==next(c['ref']for p in listing['observation']['players']if p['id']==2 for c in p['hand']if c['card_id']=='CORE_CS2_029')and
            a.get('target')==next(p['hero']['ref']for p in listing['observation']['players']if p['id']==1)))
        end(2);assert g.state.entities[g.state.players[1].hero_id].health==24
        play(1,'CORE_CS2_089')
        assert g.state.entities[g.state.players[1].hero_id].health==30
    third=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CATA_216','CORE_CS2_089'),deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=('CORE_CS2_029','CORE_CS2_029'),deck=('CORE_CS2_182',)*8,
            mana=40,max_mana=40,mana_cap=40)),seed=383),healing)

    registry=build_registry();policy=DeckPolicy('k25-ysera-demo','cn37-source','experimental',tuple(registry.cards),deck_size=8,max_copies=8)
    deck1=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,('EDR_000',*('CORE_CS2_182',)*7))
    deck2=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,('CORE_CS2_182',)*8)
    g=Game.from_decks(MatchSetup((deck1,deck2),policy,'GAME_005',seed=384,first_player=1),registry);checkpoints=[]
    def check():
        saved=g.snapshot();assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert g.clone().snapshot()==saved and replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    check();assert [p.mana_cap for p in g.state.players.values()]==[15,15]
    while g.state.pending_choice is not None:
        p=g.state.pending_choice.player_id;listing=g.for_player(p).legal_actions()
        action=next(a for a in listing['actions']if a['type']=='select_choice'and not a['options'])
        response=g.for_player(p).submit(dict(revision=listing['revision'],action=action));assert response['accepted'],response
        check()
    assert [p.max_mana for p in g.state.players.values()]==[1,0]
    fourth=dict(actions=len(g.history),checkpoints=checkpoints,mana_caps=[p.mana_cap for p in g.state.players.values()],
        max_mana=[p.max_mana for p in g.state.players.values()],kind='constructed_opening_experimental_policy')
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
