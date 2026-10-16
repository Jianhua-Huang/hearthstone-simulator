"""Eight real roots through player DTOs, snapshots, clone and replay; no lab cards."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.five_cost_native_cards import RAGER,SOLDIER,MATRIARCH,ANCIENT,JAILBIRD,HOGDRIVER,SAWBONES,STORM
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Keyword
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182'


def setup(hand,*,board=(),enemy=(),deck=(YETI,)*10,seed=4878):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def attack(submit,cid,*,hero=False):
    def choose(listing):
        own,enemy=listing['observation']['players'];source=next(c['ref']for c in own['board']if c['card_id']==cid)
        target=enemy['hero']['ref']if hero else enemy['board'][0]['ref']
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
    submit(1,choose)


def main():
    def basic(g,play,end,submit):
        play(1,RAGER);play(1,SOLDIER);source=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==RAGER)
        assert source.max_health==2;attack(submit,SOLDIER);assert len(g.state.players[2].board)==0
    first=session(setup((RAGER,SOLDIER),enemy=(YETI,)),basic)
    def gift(g,play,end,submit):
        play(1,MATRIARCH);assert len(g.state.players[1].board)==1
    second=session(setup((MATRIARCH,),seed=4879),gift)
    def dormant(g,play,end,submit):
        play(1,ANCIENT);end(1);end(2);end(1);end(2);end(1)
        source=g.state.entities[g.state.players[1].board[0]];hero=g.state.entities[g.state.players[1].hero_id]
        assert source.dormancy is None and hero.armor==6
    third=session(setup((ANCIENT,),seed=4880),dormant)
    def prepare(g,play,end,submit):
        def choose(listing):
            card=next(c['ref']for c in listing['observation']['players'][0]['hand']if c['card_id']==SAWBONES)
            return next(a for a in listing['actions']if a['type']=='use_hand_action'and a['card']==card and a['action_id']=='prepare')
        submit(1,choose);bird=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==JAILBIRD)
        assert g.quote_cost(bird.id).amount==1;play(1,JAILBIRD);end(1);end(2);before=len(g.state.draw_history)
        play(1,SAWBONES);assert len(g.state.draw_history)==before+1 and len(g.state.players[1].board)==1
    fourth=session(setup((JAILBIRD,SAWBONES),seed=4881),prepare)
    def charge(g,play,end,submit):
        play(1,HOGDRIVER);attack(submit,HOGDRIVER,hero=True);assert g.state.entities[g.state.players[2].hero_id].health==25
    fifth=session(setup((HOGDRIVER,),deck=(YETI,YETI),seed=4882),charge)
    def kindred(g,play,end,submit):
        play(1,STORM);end(1);end(2);play(1,STORM)
        source=next(g.state.entities[i]for i in g.state.players[1].board if Keyword.RUSH in g.state.entities[i].keywords)
        assert source.card_id==STORM
        def choose(listing):
            own,enemy=listing['observation']['players'];attacker=next(c['ref']for c in own['board']if c['card_id']==STORM and 'rush'in c['keywords']);target=enemy['board'][0]['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==target)
        submit(1,choose);assert len(g.state.players[2].board)==0
    sixth=session(setup((STORM,STORM),enemy=(YETI,),seed=4883),kindred)
    cases=[first,second,third,fourth,fifth,sixth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=8,fixed_dependencies=1,lab_fixture_definitions=0,scenarios=cases,
        actions=sum(x['actions']for x in cases),checkpoints=sum(len(x['checkpoints'])for x in cases),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(22,28)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
