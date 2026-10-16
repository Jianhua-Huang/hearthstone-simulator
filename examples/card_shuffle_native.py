"""The real Tracker and three existing Standard shuffle producers through DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

TRACKER='TLC_520';RAPTORS='TLC_826';PLAIN='CORE_CS2_182'


def setup(hand,deck=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60)),seed=1049)


def price(g,submit,expected):
    listing=g.for_player(1).legal_actions();own=next(p for p in listing['observation']['players']if p['id']==1)
    card=next(c for c in own['hand']if c['card_id']==TRACKER);assert card['cost']['amount']==expected


def main():
    def one(g,play,end,submit):
        play(1,RAPTORS);price(g,submit,5);before=g.state.players[1].mana;play(1,TRACKER)
        s=g.state;assert s.players[1].mana==before-5 and len(s.deck_shuffle_history)==1
        assert s.deck_shuffle_history[0].declared_count==10
        e=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id==TRACKER)
        assert(e.attack,e.health)==(5,5)and Keyword.RUSH in e.keywords
    a=session(setup((RAPTORS,TRACKER)),one)
    def two(g,play,end,submit):
        play(1,RAPTORS);play(1,RAPTORS);price(g,submit,4);play(1,TRACKER)
        assert len(g.state.deck_shuffle_history)==2 and len(g.state.players[1].deck)==20
    b=session(setup((RAPTORS,RAPTORS,TRACKER)),two)
    def selected(g,play,end,submit):
        original=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==TRACKER)
        def choose(listing):
            own=next(p for p in listing['observation']['players']if p['id']==1)
            ref=next(c['ref']for c in own['hand']if c['card_id']=='CATA_721')
            target=next(c['ref']for c in own['hand']if c['card_id']==TRACKER)
            return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==ref and a.get('target')==target)
        submit(1,choose);assert g.state.entities[original].zone==Zone.HAND
        price(g,submit,5);play(1,TRACKER);assert g.state.entities[original].zone==Zone.BOARD
    c=session(setup(('CATA_721',TRACKER)),selected)
    def leftmost(g,play,end,submit):
        original=g.state.players[1].hand[0];play(1,'DINO_408');assert g.state.entities[original].zone==Zone.DECK
        end(1);end(2);assert g.state.entities[original].zone==Zone.HAND
        price(g,submit,5);play(1,TRACKER);assert len(g.state.deck_shuffle_history)==1
    d=session(setup((TRACKER,'DINO_408')),leftmost)
    rows=[a,b,c,d];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=1,existing_standard_producers=3,lab_fixture_definitions=0,actions=sum(x['actions']for x in rows),
        checkpoints=sum(len(x['checkpoints'])for x in rows),scenarios=rows,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(11,15)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
