"""Six actual conditional/resource spells through player DTOs and checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';BIG='DINO_132';FIRE='FIR_923';ADVANCE='TIME_750';FORTIFY='TLC_620';ABLATING='TLC_447';BLOOD='JAIL_441';STRIKE='RLK_024'


def setup(hand,*,board=(),enemy=(),armor=0,power=False,seed=711):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
        mana=40,max_mana=40,mana_cap=40,armor=armor,hero_power_card_id='HERO_08bp'if power else None),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def use_power(g,submit,target_player):
    def choose(listing):
        hero=next(p['hero']['ref']for p in listing['observation']['players']if p['id']==target_player)
        return next(a for a in listing['actions']if a['type']=='use_hero_power'and a.get('target')==hero)
    submit(1,choose)


def main():
    def fire(g,play,end,submit):
        play(1,FIRE);s=g.state
        assert not s.players[2].board and len(s.players[1].hand)==1
        assert next(r.health_result.damage_dealt for r in s.damage_history if r.health_result.source_card_id==FIRE)==8
    first=session(setup((FIRE,BIG),enemy=(YETI,)),fire)

    def advance(g,play,end,submit):
        original=tuple(g.state.players[1].deck);play(1,ADVANCE,target_player=2);s=g.state
        assert len(s.draw_history)==1 and s.draw_history[0].entity_id in original
        assert len(s.players[1].hand)==2 and s.entities[s.players[2].hero_id].health==27
    second=session(setup((ADVANCE,BIG),seed=712),advance)

    def fortify(g,play,end,submit):
        play(1,FORTIFY,target_card=BIG);s=g.state
        assert s.entities[s.players[1].hero_id].armor==7
        assert s.entities[s.players[2].board[0]].health==5
    third=session(setup((FORTIFY,),enemy=(BIG,),armor=4,seed=713),fortify)

    def ablating(g,play,end,submit):
        play(1,'TLC_901',target_card=YETI);end(1);end(2)
        play(1,ABLATING,target_card='CORE_EX1_506');s=g.state
        assert not s.players[1].board and len(s.players[2].board)==1
        assert s.entities[s.players[2].board[0]].health==10
        rows=[r.health_result for r in s.damage_history if r.health_result.source_card_id==ABLATING]
        assert len(rows)==1 and len({r.batch_id for r in rows})==1
        assert any(r.health_result.source_card_id==BIG and r.health_result.damage_dealt==5 for r in s.damage_history)
    fourth=session(setup(('TLC_901',ABLATING),board=(YETI,),enemy=('CORE_EX1_506',BIG),seed=714),ablating)

    def blood(g,play,end,submit):
        play(1,'CORE_CS2_029',target_player=1);use_power(g,submit,1)
        play(1,BLOOD,target_card=YETI);s=g.state
        assert s.entities[s.players[1].hero_id].health==26
        assert s.entities[s.players[1].hero_power_id].uses_this_turn==0
        use_power(g,submit,2);assert g.state.players[1].hero_power_uses_this_turn==2
    fifth=session(setup(('CORE_CS2_029',BLOOD),enemy=(YETI,),power=True,seed=715),blood)

    def strike(g,play,end,submit):
        play(1,'CORE_CS2_029',target_player=1);play(1,STRIKE,target_card=BIG);s=g.state
        assert s.entities[s.players[1].hero_id].health==30
        assert s.entities[s.players[2].board[0]].health==6
    sixth=session(setup(('CORE_CS2_029',STRIKE),enemy=(BIG,),seed=716),strike)
    scenarios=[first,second,third,fourth,fifth,sixth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,new_dependencies=0,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(13,19)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
