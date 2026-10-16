"""Four real corpse consumers via player DTOs; no synthetic game definitions."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Resource,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,*,board=(),enemy=(),deck=None,corpses=20,seed=4473):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8 if deck is None else deck,
        mana=30,max_mana=30,mana_cap=30,corpses=corpses,hero_power_card_id='HERO_08bp'),PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8,
        mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),seed=seed)


def body(g,cid,p=1):
    s=g.state;return next(s.entities[i]for i in s.players[p].board if s.entities[i].card_id==cid)


def main():
    def falric(g,play,end,submit):
        play(1,'CORE_EDR_003');play(1,'CORE_CS2_029',target_card='CORE_CS2_182')
        assert g.state.players[1].resources[Resource.CORPSES]==2
        play(1,'RLK_060');s=g.state
        assert sum(s.entities[i].card_id=='RLK_008t'for i in s.players[1].board)==2
        assert s.players[1].resources[Resource.CORPSES]==0
    first=session(setup(('CORE_EDR_003','CORE_CS2_029'),board=('CORE_CS2_182',),deck=('RLK_060',),corpses=0),falric)
    def swarm(g,play,end,submit):
        for branch in('ants','bites'):
            def choose(listing,branch=branch):
                players={p['id']:p for p in listing['observation']['players']}
                card=next(c['ref']for c in players[1]['hand']if c['card_id']=='EDR_813')
                target=next(c['ref']for c in players[2]['board']if c['card_id']=='CORE_CS2_182')if branch=='bites'else None
                return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card and a.get('branch')==branch and a.get('target')==target)
            submit(1,choose)
        assert body(g,'CORE_CS2_182',2).health==1
        assert sum(g.state.entities[i].card_id=='EDR_813at'for i in g.state.players[1].board)==2
    second=session(setup(('EDR_813','EDR_813'),enemy=('CORE_CS2_182',),corpses=2,seed=4474),swarm)
    def terror(g,play,end,submit):
        play(1,'TLC_433');play(1,'FIR_951')
        def twenty(listing):
            key=next(o['ref']for o in listing['observation']['pending_choice']['options']if o['card_id']=='FIR_951t3')
            return next(a for a in listing['actions']if a['type']=='select_choice'and a['options']==[key])
        submit(1,twenty);assert not g.state.players[1].quests
        play(1,'TLC_433t');play(1,'CORE_CS2_029',target_card='TLC_433t');play(1,'CORE_CS2_029',target_card='TLC_433t')
        grave=body(g,'TLC_433t2').id
        def use(listing):
            players={p['id']:p for p in listing['observation']['players']}
            location=next(c['ref']for c in players[1]['board']if c['card_id']=='TLC_433t2');target=players[2]['hero']['ref']
            return next(a for a in listing['actions']if a['type']=='use_location'and a['location']==location and a.get('target')==target)
        submit(1,use)
        for _ in range(2):end(1);end(2)
        submit(1,use);assert g.state.entities[grave].zone==Zone.GRAVEYARD
        assert(body(g,'TLC_433t').attack,body(g,'TLC_433t').health)==(8,8)
        assert g.state.entities[g.state.players[2].hero_id].health==22
    third=session(setup(('TLC_433','FIR_951','CORE_CS2_029','CORE_CS2_029'),corpses=30,seed=4475),terror)
    def doctor(g,play,end,submit):
        play(1,'JAIL_446');primary=g.state.players[1].hero_power_id
        def kiss(listing):
            players={p['id']:p for p in listing['observation']['players']};owner=players[1]
            power=next(c['ref']for c in owner['additional_hero_powers']if c['card_id']=='JAIL_446hp')
            target=next(c['ref']for c in owner['board']if c['card_id']=='CORE_CS2_182')
            return next(a for a in listing['actions']if a['type']=='use_hero_power'and a['power']==power and a.get('target')==target)
        submit(1,kiss)
        def original(listing):
            players={p['id']:p for p in listing['observation']['players']};power=players[1]['hero_power']['ref'];target=players[2]['hero']['ref']
            return next(a for a in listing['actions']if a['type']=='use_hero_power'and a['power']==power and a.get('target')==target)
        submit(1,original);assert g.state.players[1].hero_power_id==primary
        assert body(g,'CORE_CS2_182').attack==7 and g.state.players[1].resources[Resource.CORPSES]==0
    fourth=session(setup(('JAIL_446',),board=('CORE_CS2_182',),corpses=3,seed=4476),doctor)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=4,fixed_dependencies=6,lab_fixture_definitions=0,scenarios=scenarios,actions=sum(s['actions']for s in scenarios),
        checkpoints=sum(len(s['checkpoints'])for s in scenarios),formal_pool_complete=False,cn_calibrated=False,
        explicit_unsupported=['Thalena installation with a pre-existing additional Hero Power'])
    assert(result['actions'],result['checkpoints'])==(20,24)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
