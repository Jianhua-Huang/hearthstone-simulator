"""Five actual cards driven by player DTOs with original physical decks/history."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardType,PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';WISP='CORE_CS2_231';FIRE='CORE_CS2_029';BOLT='CORE_CS2_024';INNERVATE='CORE_EX1_169'


def setup(hand,deck=(YETI,)*8,board=(),enemy=(),enemy_hand=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=60,max_mana=60,mana_cap=60)),seed=1048)


def cards(g,zone='board',p=1):
    s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)]


def main():
    scenarios=[]
    for branch,attribute in(('END_010a','attack'),('END_010b','health')):
        def twilight(g,play,end,submit,branch=branch,attribute=attribute):
            submit(1,lambda x:next(a for a in x['actions']if a['type']=='play_card'and a.get('branch')==branch))
            assert all(getattr(e,attribute)==1 for p in(1,2)for e in cards(g,p=p)if e.card_id!='END_010')
            e=next(e for e in cards(g)if e.card_id=='END_010');assert(e.attack,e.health)==(5,5)
        scenarios.append(session(setup(('END_010',),board=(YETI,),enemy=(YETI,)),twilight))
    def chronogor(g,play,end,submit):
        original={e.id for e in cards(g,'deck')};play(1,'TIME_032')
        assert[c.card_id for c in cards(g,'hand')]==['GIL_820',YETI]
        assert[c.card_id for c in cards(g,'hand',2)]==[INNERVATE,BOLT]
        assert not cards(g,'deck')and len(cards(g,'deck',2))==8
        assert all(d.entity_id in original for d in g.state.draw_history)
    scenarios.append(session(setup(('TIME_032',),deck=(INNERVATE,BOLT,YETI,'GIL_820')),chronogor))
    def chromie(g,play,end,submit):
        play(1,WISP);play(1,'TIME_103');source=next(e.id for e in cards(g)if e.card_id=='TIME_103')
        play(1,FIRE,target_card='TIME_103')
        assert[d.card_id for d in g.state.draw_history if d.source_id==source]==[WISP,FIRE]
        assert sum(e.card_id==WISP for e in cards(g,'deck'))==1
    scenarios.append(session(setup((WISP,'TIME_103',FIRE),deck=(WISP,WISP,FIRE,YETI)),chromie))
    def epoch(g,play,end,submit):
        initial=cards(g,p=2)[0].id;end(1);play(2,WISP);play(2,YETI);end(2);play(1,'TIME_714')
        assert[e.id for e in cards(g,p=2)]==[initial]
    scenarios.append(session(setup(('TIME_714',),enemy=(YETI,),enemy_hand=(WISP,YETI)),epoch))
    def esho(g,play,end,submit):
        play(1,'TLC_110')
        assert[(e.attack,e.health)for e in cards(g)if e.card_id=='TIME_605']==[(5,6)]
        assert[(e.attack,e.health)for e in cards(g,'hand')]==[(5,6)]
        assert all((e.attack,e.health)==(5,6)for e in cards(g,'deck')if e.kind==CardType.MINION)
    scenarios.append(session(setup(('TLC_110','TIME_605'),deck=('TIME_605',FIRE,'TIME_605'),board=('TIME_605',)),esho))
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,dependencies=2,choice_only_dependencies=2,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(12,18)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
