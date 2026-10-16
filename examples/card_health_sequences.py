"""Six complete real spell recipes through player actions and saved checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';BURST='FIR_909';SCORCH='FIR_954';CRYO='TLC_440';FUMES='TLC_901';ELECTRIC='TIME_216';INFEST='EDR_814'


def setup(hand,*,board=(),enemy=(),deck=(YETI,)*8,enemy_deck=(YETI,)*8,seed=521):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def burst(g,play,end,submit):
        before=g._rng.getstate();play(1,BURST)
        assert g._rng.getstate()==before and g.state.entities[g.state.players[2].hero_id].health==28
        assert all(g.state.entities[e].health==3 for e in g.state.players[2].board)
    first=session(setup((BURST,),enemy=(YETI,YETI)),burst)

    def scorch(g,play,end,submit):
        target=g.state.players[2].board[0];drawn=g.state.players[2].deck[0]
        play(1,SCORCH,target_card=YETI)
        assert g.state.entities[target].zone.value=='graveyard'and g.state.players[2].hand==[drawn]
        assert g.observe(1)['players'][1]['hand'][0].get('card_id')is None
    second=session(setup((SCORCH,),enemy=(YETI,),seed=522),scorch)

    def cryo(g,play,end,submit):
        play(1,'CORE_CS2_024',target_player=2);end(1);end(2)
        before=len(g.state.players[1].hand);play(1,CRYO,target_player=1)
        assert len(g.state.players[1].hand)==before+1
        hero=g.state.entities[g.state.players[1].hero_id];assert hero.health==26 and not hero.frozen
    third=session(setup(('CORE_CS2_024',CRYO),seed=523),cryo)

    def fumes(g,play,end,submit):
        play(1,FUMES,target_card='TLC_463')
        health={g.state.entities[e].card_id:g.state.entities[e].health for p in(1,2)for e in g.state.players[p].board}
        assert health=={'TLC_463':4,'JAIL_399':2,'DINO_132':9,YETI:5}
        rows=[r.health_result for r in g.state.damage_history if r.health_result.source_card_id==FUMES]
        assert len(rows)==3 and len({r.batch_id for r in rows})==1
    fourth=session(setup((FUMES,),board=('TLC_463',),enemy=('JAIL_399','DINO_132',YETI),seed=524),fumes)

    def electric(g,play,end,submit):
        drawn=tuple(g.state.players[1].deck)
        play(1,ELECTRIC,target_card='DINO_132')
        assert g.state.players[1].hand==list(drawn)
        assert g.state.entities[g.state.players[2].board[0]].health==7
    fifth=session(setup((ELECTRIC,),enemy=('DINO_132',),deck=(YETI,YETI),seed=525),electric)

    def infest(g,play,end,submit):
        play(1,INFEST,target_player=2)
        leech=g.state.entities[g.state.players[1].board[0]]
        assert(leech.card_id,leech.attack,leech.health)==('EDR_810t',0,2)
        assert g.state.card_summon_history[-1].request.cause.source.card_id==INFEST
        end(1)
        assert g.state.entities[g.state.players[2].hero_id].health==27
        assert g.state.entities[g.state.players[1].hero_id].health==31
    sixth=session(setup((INFEST,),seed=526),infest)
    scenarios=[first,second,third,fourth,fifth,sixth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,new_dependencies=0,existing_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(10,16)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
