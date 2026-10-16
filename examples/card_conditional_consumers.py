"""Eight real consumers through player DTOs and portable checkpoints."""
import json
from hs_sim.cards import build_registry
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.conditional_consumer_cards import CULTIST,TYRANT,KEEPER,BITTER,AXE,CLAWS,AUCTIONEER,WAYGATE
from hs_sim.engine import CardClass,DeckPolicy,DeckSpec,Game,MatchSetup,PlayerSetup,Scenario
from hs_sim.engine.model import Keyword,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182';BOLT='CORE_CS2_024';FIREBALL='CORE_CS2_029';DRAGON='CATA_898';FIREFLY='CORE_UNG_809'


def setup(hand,*,board=(),enemy=(),seed=5181):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def session(start,run):
    g=Game.from_decks(start,build_registry())if isinstance(start,MatchSetup)else Game.from_scenario(start,build_registry());checkpoints=[]
    def check():
        saved=g.snapshot();assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert g.clone().snapshot()==saved and replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def submit(player,choose):
        listing=g.for_player(player).legal_actions();assert listing['actions']is not None
        reply=g.for_player(player).submit(dict(revision=listing['revision'],action=choose(listing)));assert reply['accepted'],reply;check()
    def play(cid,*,target_card=None,target_player=None,middle=False):
        def choose(listing):
            players={v['id']:v for v in listing['observation']['players']};ref=next(c['ref']for c in players[1]['hand']if c['card_id']==cid)
            target=players[2]['board'][1]['ref']if middle else players[target_player]['hero']['ref']if target_player is not None else next((c['ref']for v in players.values()for c in v['board']if c['card_id']==target_card),None)
            return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==ref and a.get('target')==target)
        submit(1,choose)
    def end(player):submit(player,lambda listing:next(a for a in listing['actions']if a['type']=='end_turn'))
    def attack():
        def choose(listing):
            players={v['id']:v for v in listing['observation']['players']};own=players[1]['hero']['ref'];enemy=players[2]['hero']['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==own and a['defender']==enemy)
        submit(1,choose)
    check()
    while g.state.pending_choice:
        submit(g.state.pending_choice.player_id,lambda listing:next(a for a in listing['actions']if a['type']=='select_choice'and not a['options']))
    run(g,play,end,attack,submit);assert g.state.pending_choice is None
    return dict(actions=len(g.history),checkpoints=checkpoints,starting_deck_inventory_known=g.state.opening is not None)


def main():
    def cultist(g,play,end,attack,submit):
        play(CULTIST);old=g.state.players[1].board[0];play(BOLT,target_card=CULTIST)
        fresh=g.state.entities[g.state.players[1].board[0]];assert fresh.id!=old and(fresh.attack,fresh.health)==(5,1)and Keyword.REBORN not in fresh.keywords
    first=session(setup((CULTIST,BOLT)),cultist)
    def tyrant(g,play,end,attack,submit):
        play(TYRANT);source=g.state.players[1].board[0];assert g.state.entities[source].attack==1
        end(1);assert g.state.entities[source].attack==7;end(2);assert g.state.entities[source].attack==1
    second=session(setup((TYRANT,),seed=5182),tyrant)
    def keeper(g,play,end,attack,submit):
        play(KEEPER);assert g.state.entities[g.state.players[1].board[0]].keywords==frozenset((Keyword.TAUNT,Keyword.DIVINE_SHIELD))
    third=session(setup((KEEPER,DRAGON),seed=5183),keeper)
    def bitter(g,play,end,attack,submit):
        middle=g.state.players[2].board[1];play(BOLT,middle=True);play(BITTER,middle=True)
        assert g.state.entities[middle].zone==Zone.GRAVEYARD and all(g.state.entities[i].frozen for i in g.state.players[2].board)
    fourth=session(setup((BOLT,BITTER),enemy=(YETI,)*3,seed=5184),bitter)
    def axe(g,play,end,attack,submit):
        play(AXE);weapon=g.state.players[1].weapon_id;attack();end(1);end(2);attack()
        assert g.state.entities[weapon].zone==Zone.GRAVEYARD
        assert all(g.state.entities[i].health==3 for player in g.state.players.values()for i in player.board)
    fifth=session(setup((AXE,),board=(YETI,),enemy=(YETI,),seed=5185),axe)
    def claws(g,play,end,attack,submit):
        highest=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==YETI)
        play(CLAWS);attack();assert g.state.entities[highest.id].zone==Zone.GRAVEYARD and len(g.state.discard_history)==1
    sixth=session(setup((CLAWS,YETI,BOLT),seed=5186),claws)
    def auctioneer(g,play,end,attack,submit):
        def prepare(listing):
            own=next(v for v in listing['observation']['players']if v['id']==1);ref=next(c['ref']for c in own['hand']if c['card_id']==AUCTIONEER)
            return next(a for a in listing['actions']if a['type']=='use_hand_action'and a['card']==ref and a['action_id']=='prepare')
        submit(1,prepare);end(1);end(2);play(AUCTIONEER);before=len(g.state.draw_history);play(FIREBALL,target_player=2)
        assert len(g.state.draw_history)==before+1
    seventh=session(setup((AUCTIONEER,FIREBALL),seed=5187),auctioneer)
    cards=(FIREFLY,)*2+(WAYGATE,)*2+(YETI,)*8
    policy=DeckPolicy('cn37-k81-native','cn37-k81-native','experimental',(FIREFLY,WAYGATE,YETI),deck_size=12,max_copies=8)
    start=MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),policy,'GAME_005',seed=1083,first_player=1)
    def waygate(g,play,end,attack,submit):
        original=set(g.state.opening.original_entities[0]);play(FIREFLY)
        child=next(g.state.entities[i]for i in g.state.players[1].hand if i not in original)
        assert g.quote_cost(child.id).amount==1;end(1);end(2);play(WAYGATE);assert g.quote_cost(child.id).amount==0
        assert all(g.quote_cost(i).amount==4 for i in g.state.players[1].hand if i in original and g.state.entities[i].card_id==YETI)
    eighth=session(start,waygate)
    cases=[first,second,third,fourth,fifth,sixth,seventh,eighth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=8,fixed_dependencies=0,lab_fixture_definitions=0,scenarios=cases,actions=sum(c['actions']for c in cases),checkpoints=sum(len(c['checkpoints'])for c in cases),
        full_openings=1,opening_policy='12-card experimental fixture; not a certified Standard deck or pool',formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(26,34)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
