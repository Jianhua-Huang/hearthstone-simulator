"""Five real roots via player commands; one explicit lab-only temporary producer."""
import json
from hs_sim.cards import build_registry
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.model import Keyword,PaymentType
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.temporary_cards import CreateTemporaryCard


def lab_registry():
    r=build_registry();key='lab.k25c.temporary-v1'
    r.register_behavior(key,lambda c:(CreateTemporaryCard(c.player_id,'CORE_CS2_182',c.state.turn,source_id=c.source_id),))
    r.register_card(CardDefinition(key,'临时牌验证夹具（非正式卡牌）',CardType.SPELL,on_play=key,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    return r


def session(setup,run,factory=build_registry):
    g=Game.from_scenario(setup,factory());checkpoints=[]
    def check():
        s=g.snapshot();assert Game.from_snapshot(s,factory()).snapshot()==s
        assert g.clone().snapshot()==s and replay(build_replay(g),factory()).snapshot()==s
        checkpoints.append('ready')
    def submit(p,choose):
        listing=g.for_player(p).legal_actions();assert listing['actions']is not None
        reply=g.for_player(p).submit(dict(revision=listing['revision'],action=choose(listing)));assert reply['accepted'],reply
        check()
    def play(p,cid,*,target_card=None,target_player=None):
        def choose(listing):
            players={v['id']:v for v in listing['observation']['players']};card=next(c['ref']for c in players[p]['hand']if c['card_id']==cid)
            target=players[target_player]['hero']['ref']if target_player is not None else next((c['ref']for v in players.values()for c in v['board']if c['card_id']==target_card),None)
            return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card and a.get('target')==target)
        submit(p,choose)
    def end(p):submit(p,lambda listing:next(a for a in listing['actions']if a['type']=='end_turn'))
    check();run(g,play,end,submit);assert g.state.pending_choice is None
    return dict(actions=len(g.history),checkpoints=checkpoints,owner_health=g.state.entities[g.state.players[1].hero_id].health,
        enemy_health=g.state.entities[g.state.players[2].hero_id].health)


def setup(hand,enemy=(),seed=410):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=enemy,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def fox(g,play,end,submit):
        play(1,'CORE_DMF_511');play(1,'CORE_EX1_008');before=g.state.players[1].mana;play(1,'CORE_EX1_131')
        assert g.state.players[1].mana==before and not g.state.players[1].cost_modifiers
    first=session(setup(('CORE_DMF_511','CORE_EX1_008','CORE_EX1_131')),fox)

    def payment(g,play,end,submit):
        play(1,'CORE_CATA_001');play(1,'CATA_180');assert Keyword.IMMUNE in g.state.entities[g.state.players[1].hero_id].keywords
        before=g.state.players[1].mana;play(1,'CORE_EX1_506')
        assert g.state.players[1].mana==before and g.state.entities[g.state.players[1].hero_id].health==28
        before=g.state.players[1].mana;play(1,'CORE_CS2_064');assert g.state.players[1].mana==before
        assert g.state.entities[g.state.players[1].hero_id].health==28
    second=session(setup(('CORE_CATA_001','CATA_180','CORE_EX1_506','CORE_CS2_064'),seed=411),payment)

    def crocodile(g,play,end,submit):
        play(1,'TLC_250');play(1,'CORE_CS2_029',target_player=2);end(1);play(2,'CORE_CS2_089')
        assert g.state.entities[g.state.players[2].hero_id].health==24
        end(2);end(1);play(2,'CORE_CS2_089');assert g.state.entities[g.state.players[2].hero_id].health==30
    third=session(setup(('TLC_250','CORE_CS2_029'),('CORE_CS2_089','CORE_CS2_089'),seed=412),crocodile)

    def temporary(g,play,end,submit):
        play(1,'TLC_450');play(1,'lab.k25c.temporary-v1');s=g.state
        entity=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id=='CORE_CS2_182')
        assert entity.hand_lifetime is not None and quote_cost(s,g.registry,entity).amount==2
        before=g.state.players[1].mana;play(1,'CORE_CS2_182');assert g.state.players[1].mana==before-2
        assert not g.state.players[1].cost_modifiers
    fourth=session(setup(('TLC_450','lab.k25c.temporary-v1'),seed=413),temporary,lab_registry)
    scenarios=[first,second,third,fourth];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=5,lab_fixture_definitions=1,lab_fixture_is_official_card=False,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(17,21)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
