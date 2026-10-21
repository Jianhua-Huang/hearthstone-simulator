"""Original overdraw material, native destruction and capacity-driven return."""
from functools import lru_cache
import json,unittest
from hs_sim.cards.overdraw_return_card import load_batch,register_overdraw_return_card
from hs_sim.engine import (CardClass,CardDefinition,CardType,DeckPolicy,DeckSpec,Game,MatchSetup,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CastWhenDrawnSpec,Keyword,CostSpec
from hs_sim.engine.actions import Concede
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.zones import DrawMatching
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.overdraw_returns import SOURCE,PROGRAM,ACCEPTED,STORED,RETURNED
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.costs import quote_cost
from opening_fixtures import registry as opening_registry,metadata

P='godfrey.test.'
PLAIN='card.1'


@lru_cache(None)
def registry(role='writer',mode=None):
    r=opening_registry();register_overdraw_return_card(r)
    from hs_sim.cards.demon_zone_cards import register_demon_zone_cards
    register_demon_zone_cards(r)
    def enable(c):
        source=next(i for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==SOURCE)
        return(AddPlayerEffect(c.player_id,PROGRAM,source),)
    def fail(c):raise ResolutionError('Godfrey deliberate return rollback')
    r.register_behavior(P+'fail',fail)
    bodies={'enable':enable,'fill':lambda c:tuple(AddToHand(c.player_id,PLAIN)for _ in range(10-len(c.state.players[c.player_id].hand))),
        'draw3':lambda c:(Draw(c.player_id,3,c.source_id),),'free':lambda c:(GainArmor(c.player_id,1),),
        'generated':lambda c:(AddToHand(c.player_id,P+'held'),AddToHand(c.player_id,P+'held')),
        'cast':lambda c:(GainArmor(c.player_id,7),),
        'capacity':lambda c:(SetHandCapacity(c.player_id,12),),
        'foreign':lambda c:(DrawMatching(c.player_id,PoolQuery(),'skip',count=3,selection='first',source_id=c.source_id,owner_id=3-c.player_id),),
        'material':lambda c:(RandomBuffStoredMinion(c.player_id,3,4,zone=Zone.DECK,query=PoolQuery(card_ids=(P+'held',)),source_id=c.source_id,cost=CostSpec(delta=-2)),)}
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key))
    r.register_card(CardDefinition(P+'held','Original stored minion',CardType.MINION,cost=4,attack=2,health=3,metadata=metadata()))
    r.register_card(CardDefinition(P+'cast-drawn','Original drawn spell',CardType.SPELL,cost=3,on_play=P+'cast',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec()))
    r.register_card(CardDefinition('warlock.power','Power',CardType.HERO_POWER,cost=2,on_use='power',metadata=metadata(CardClass.WARLOCK,collectible=False)))
    r.register_card(CardDefinition('warlock.hero','Hero',CardType.HERO,health=30,initial_hero_power='warlock.power',metadata=metadata(CardClass.WARLOCK,collectible=False)))
    if mode:
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            if mode in ('burn_wait','burn_fail')and dict(c.event.data).get('draw_id')is None:return ()
            if mode in ('burn_fail','return_fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Watcher',CardType.MINION,health=20,
            triggers=(TriggerSpec('card_burned'if mode in ('burn_wait','burn_fail')else 'card_moved_to_hand',P+'watch'),)))
    r.validate();r.freeze();return r


class OverdrawReturnTests(unittest.TestCase):
    def game(self,*,mode=None,tail=(P+'held',P+'held'),active=True,extra=(),seat=1):
        hand=tuple((P+'enable',)if active else())+(P+'fill',P+'draw3',P+'free',P+'free',P+'generated',*extra)
        own=PlayerSetup('mage.hero',hand=hand,deck=(SOURCE,*tail,PLAIN),
            board=(P+'watch',)if mode else(),mana=10,max_mana=10)
        other=PlayerSetup('warrior.hero',deck=(PLAIN,)*4)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=290),registry('writer',mode))
    def play(self,g,cid):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        d=g.registry.card(cid)
        g.apply(PlayCard(pid,eid,position=len(g.state.players[pid].board)if d.kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def burn(self,g,*,active=True):
        if active:self.play(g,P+'enable')
        self.play(g,P+'fill');self.play(g,P+'draw3')
    def portable(self,g,mode=None):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry('reader',mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),s);return other
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        return s

    def test_a01_complete_source_and_real_start_program(self):
        r=registry();d=r.card(SOURCE)
        self.assertEqual((d.cost,d.attack,d.health),(4,5,4));self.assertEqual(len(load_batch()['cards']),1)
        cards=(SOURCE,*('card.'+str(i)for i in range(1,30)))
        policy=DeckPolicy('godfrey-exp','godfrey-exp','experimental',tuple(r.cards),deck_size=30)
        setup=MatchSetup((DeckSpec('warlock.hero','warlock.power',CardClass.WARLOCK,cards),
            DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,tuple('card.'+str(i)for i in range(1,31)))),policy,'coin',seed=290,first_player=1)
        g=Game.from_decks(setup,r)
        self.assertEqual([p.spec_id for p in g.state.players[1].player_effects],[PROGRAM]);self.portable(g)

    def test_a02_actual_overdraw_records_destroy_then_store_originals(self):
        g=self.game();originals=tuple(g.state.players[1].deck[1:3]);self.burn(g)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned','burned'])
        self.assertEqual([r.original.entity_id for r in g.state.overdraw_returns],list(originals))
        self.assertTrue(all(r.phase=='stored'for r in g.state.overdraw_returns))
        self.assertTrue(all(g.state.entities[i].zone==Zone.SETASIDE for i in originals));self.portable(g)

    def test_a03_vacated_slot_returns_original_with_one_less_cost_and_no_new_draw(self):
        g=self.game();self.burn(g);self.play(g,P+'free')
        done=[r for r in g.state.overdraw_returns if r.phase=='returned'];self.assertEqual(len(done),1)
        row=done[0];e=g.state.entities[row.original.entity_id]
        self.assertEqual(g.state.hand_entries[e.hand_entry_id-1].source_id,row.source_id)
        self.assertEqual(e.zone,Zone.HAND);self.assertEqual(quote_cost(g.state,g.registry,e).amount,3)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(len(g.state.players[1].hand),10)
        self.play(g,P+'free');self.assertTrue(all(r.phase=='returned'for r in g.state.overdraw_returns))
        self.portable(g)

    def test_a04_generated_overflow_is_not_captured_and_absent_program_keeps_normal_burn(self):
        g=self.game();self.burn(g);before=len(g.state.overdraw_returns)
        self.play(g,P+'generated');self.assertEqual(len(g.state.overdraw_returns),before)
        h=self.game(active=False);self.burn(h,active=False)
        self.assertEqual(h.state.overdraw_returns,[])
        self.assertEqual([h.state.entities[d.entity_id].zone for d in h.state.draw_history[1:]],[Zone.GRAVEYARD]*2)

    def test_a05_real_impfernal_destruction_resolves_before_storage_and_returns(self):
        g=self.game(tail=('JAIL_398',P+'held'));self.burn(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual(g.state.overdraw_returns[0].original.card_id,'JAIL_398')
        self.play(g,P+'free');self.play(g,P+'free')
        self.assertTrue(all(r.phase=='returned'for r in g.state.overdraw_returns));self.portable(g)

    def test_a06_burned_cast_when_drawn_returns_without_casting_or_redrawing(self):
        g=self.game(tail=(P+'cast-drawn',P+'held'));self.burn(g);self.play(g,P+'free');self.play(g,P+'free')
        self.assertEqual(g.state.cast_history[-1].card_id,P+'free')
        self.assertFalse(any(c.card_id==P+'cast-drawn'for c in g.state.cast_history))
        self.assertEqual(len(g.state.draw_history),3)

    def test_b01_burn_wait_and_return_wait_restore_complete_original_lease(self):
        for mode in ('burn_wait','return_wait'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.burn(g)
                if mode=='return_wait':self.play(g,P+'free')
                self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,mode)
                s=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),s);self.finish(g);self.finish(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_b02_player_views_hide_queue_originals_rng_and_receipts(self):
        g=self.game();self.burn(g)
        for pid in (1,2):
            text=json.dumps(g.observe(pid),sort_keys=True)
            for field in ('overdraw_returns',ACCEPTED,STORED,RETURNED,'rng_before','rng_after'):self.assertNotIn(field,text)

    def test_b03_rehashed_missing_original_queue_or_borrowed_draw_rejected(self):
        g=self.game();self.burn(g)
        s=json.loads(json.dumps(g.snapshot()));s['state']['overdraw_returns']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))

    def test_b04_stored_enchantments_and_original_identity_survive_burn_and_return(self):
        g=self.game(extra=(P+'material',));self.play(g,P+'enable');self.play(g,P+'material')
        originals={i:(g.state.entities[i].attack,g.state.entities[i].max_health,
            quote_cost(g.state,g.registry,g.state.entities[i]).amount)for i in g.state.players[1].deck[1:3]}
        self.play(g,P+'fill');self.play(g,P+'draw3');self.play(g,P+'free');self.play(g,P+'free')
        for eid,(attack,health,cost)in originals.items():
            e=g.state.entities[eid];self.assertEqual((e.attack,e.max_health),(attack,health))
            self.assertEqual(quote_cost(g.state,g.registry,e).amount,max(0,cost-1))

    def test_b05_actual_foreign_deck_draw_preserves_original_owner(self):
        g=self.game(extra=(P+'foreign',));self.play(g,P+'enable');self.play(g,P+'fill');self.play(g,P+'foreign')
        self.assertEqual(len(g.state.overdraw_returns),2);self.play(g,P+'free')
        row=next(r for r in g.state.overdraw_returns if r.phase=='returned')
        e=g.state.entities[row.original.entity_id];self.assertEqual((e.owner,e.controller,e.zone),(2,1,Zone.HAND))
        self.assertEqual(quote_cost(g.state,g.registry,e).amount,0)

    def test_b06_second_seat_and_single_candidate_do_not_consume_rng(self):
        g=self.game(seat=2);self.burn(g);self.play(g,P+'free');before=g.snapshot()['rng_state'];self.play(g,P+'free')
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertTrue(all(r.player_id==2 and r.phase=='returned'for r in g.state.overdraw_returns))

    def test_b07_terminal_during_native_burn_wait_keeps_actual_prefix(self):
        g=self.game(mode='burn_wait');self.burn(g);g.apply(Concede(1))
        self.assertEqual(g.state.status,'finished');self.portable(g,'burn_wait')

    def test_b08_coherent_closed_random_candidate_crop_is_rejected(self):
        g=self.game();self.burn(g);self.play(g,P+'free')
        s=json.loads(json.dumps(g.snapshot()));row=next(r for r in s['state']['overdraw_returns']if r['phase']=='returned')
        row['candidates']=[row['id']];row['rng_after']=row['rng_before']
        event=next(e for e in s['events']if e['kind']==RETURNED)
        event['data']['row']=json.dumps(row,sort_keys=True,separators=(',',':'))
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))

    def test_b09_later_minion_play_does_not_install_start_of_game_program(self):
        g=self.game(active=False);self.burn(g,active=False);self.play(g,SOURCE)
        self.assertFalse(any(p.spec_id==PROGRAM for p in g.state.players[1].player_effects))
        self.assertEqual(g.state.overdraw_returns,[])

    def test_b10_capacity_change_returns_all_pending_originals_without_new_draws(self):
        g=self.game(extra=(P+'capacity',));self.burn(g);self.play(g,P+'capacity')
        self.assertTrue(all(r.phase=='returned'for r in g.state.overdraw_returns))
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(g.state.players[1].hand_cap,12)

    def test_b11_whole_action_error_rolls_back_capture_and_random_return_material(self):
        for mode in ('burn_fail','return_fail'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g,P+'enable');self.play(g,P+'fill')
                if mode=='return_fail':self.play(g,P+'draw3')
                before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,P+'draw3'if mode=='burn_fail'else P+'free')
                self.assertEqual(g.snapshot(),before)
        s=json.loads(json.dumps(g.snapshot()));s['state']['overdraw_returns'][0]['draw_id']=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))
