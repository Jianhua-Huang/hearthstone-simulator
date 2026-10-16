"""Four real Beasts in one player-command game, without laboratory definitions."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

def main():
    setup=Scenario((PlayerSetup('HERO_08',hand=('TIME_046','TLC_256','DINO_400','TLC_840','CORE_EX1_606'),deck=('CORE_CS2_182',)*8,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*8)),seed=1052)
    def run(g,play,end,submit):
        for cid in('TIME_046','TLC_256','DINO_400','TLC_840'):play(1,cid)
        play(1,'CORE_EX1_606');s=g.state
        source=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='DINO_400')
        shield=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='TLC_256')
        assert(source.attack,source.health)==(6,1)and Keyword.DIVINE_SHIELD in shield.keywords
        end(1);end(2)
        def attack(listing):
            own=next(p for p in listing['observation']['players']if p['id']==1);enemy=next(p for p in listing['observation']['players']if p['id']==2)
            ref=next(c['ref']for c in own['board']if c['card_id']=='TLC_840')
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==ref and a['defender']==enemy['hero']['ref'])
        submit(1,attack);s=g.state;assert s.entities[s.players[2].hero_id].health==26
        for _ in range(2):end(1);end(2)
        s=g.state;pat=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='TIME_046')
        assert pat.active and(pat.attack,pat.health)==(3,12)and Keyword.TAUNT in pat.keywords
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=4,lab_fixture_definitions=0,actions=row['actions'],checkpoints=len(row['checkpoints']),scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(12,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result

if __name__=='__main__':main()
