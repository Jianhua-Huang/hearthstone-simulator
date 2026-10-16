"""Actual permanent damage after source death and a whole real enemy-turn tax."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_reactive_secrets import exercise


def main():
    def damage(g,play,end,submit):
        play(1,'CORE_RLK_706');source=g.state.players[1].board[0];end(1)
        assert g.state.entities[g.state.players[2].hero_id].health==27
        play(2,'CORE_CS2_029','CORE_RLK_706')
        submit(2,lambda listing:next(a for a in listing['actions']if a['type']=='use_hero_power'and
            a.get('target')==next(c['ref']for p in listing['observation']['players']if p['id']==1 for c in p['board']if c['card_id']=='CORE_RLK_706')))
        assert source in g.state.players[1].graveyard;end(2);end(1)
        assert g.state.entities[g.state.players[2].hero_id].health==24
        hits=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id=='CORE_RLK_706']
        assert len(hits)==2 and all(h.source_controller==1 and h.damage_dealt==3 for h in hits)
    first=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_RLK_706',),deck=('CORE_CS2_182',)*6,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',hand=('CORE_CS2_029',),deck=('CORE_CS2_182',)*6,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=392),damage)

    def prices(g,play,end,submit):
        def quote():
            s=g.state;e=next(i for i in s.players[2].hand if s.entities[i].card_id=='CORE_CS2_029')
            return quote_cost(s,g.registry,s.entities[e]).amount
        def hit_hero():
            submit(2,lambda listing:next(a for a in listing['actions']if a['type']=='play_card'and
                a['card']==next(c['ref']for p in listing['observation']['players']if p['id']==2 for c in p['hand']if c['card_id']=='CORE_CS2_029')and
                a.get('target')==next(p['hero']['ref']for p in listing['observation']['players']if p['id']==1)))
        play(1,'CORE_SCH_713');assert quote()==4;end(1);assert quote()==5
        before=g.state.players[2].mana;play(2,'CORE_CS2_029','CORE_SCH_713');assert g.state.players[2].mana==before-5
        before=g.state.players[2].mana;hit_hero();assert g.state.players[2].mana==before-5
        end(2);assert quote()==4;end(1);before=g.state.players[2].mana;hit_hero()
        assert g.state.players[2].mana==before-4
    second=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_SCH_713',),deck=('CORE_CS2_182',)*6,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=('CORE_CS2_029',)*3,deck=('CORE_CS2_182',)*6,
            mana=40,max_mana=40,mana_cap=40)),seed=393),prices)
    scenes=[first,second];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=2,actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(13,15)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
