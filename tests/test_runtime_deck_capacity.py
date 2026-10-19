"""Runtime admission, original physical overflows and native discovery receipts."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.deck_capacity import FAILED,MAX_DECK_SIZE
from hs_sim.engine.deck_generation import ShuffleGeneratedCopies
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.dead_minion_shuffles import ShuffleDeadMinion
from hs_sim.engine.growing_weapon_shuffles import ShuffleGrowingWeapon
from hs_sim.engine.effects import (ChoiceOption,Destroy,GainArmor,InvokeBehavior,ModifyWeapon,
    RequestChoice,ShuffleIntoDeck)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.temporary_deck_hands import ReplaceHandWithTemporaryDeckCards
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,MoveCard,destruction_result

P='deck.capacity.test.'
HERO,PLAIN,ORIGINAL,DEAD,WEAPON=(P+x for x in ('hero','plain','original','dead','weapon'))


@lru_cache(None)
def registry(role='writer',mode=None):
    r=Registry('runtime-deck-capacity-v1')
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,attack=1,health=2))
    r.register_behavior(P+'destroyed',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(ORIGINAL,ORIGINAL,CardType.MINION,attack=2,health=3,
        on_destroyed=P+'destroyed',deathrattle=P+'destroyed'))
    def dead(c):
        return (ShuffleDeadMinion(SourceAllocationFact.capture(c.state,c.state.entities[c.source_id]),
            c.death,c.player_id,c.source_id),)
    def weapon(c):
        return (ShuffleGrowingWeapon(SourceAllocationFact.capture(c.state,c.state.entities[c.source_id]),
            c.death,c.player_id,2,c.source_id),)
    r.register_behavior(P+'dead',dead);r.register_behavior(P+'weapon',weapon)
    r.register_card(CardDefinition(DEAD,DEAD,CardType.MINION,attack=1,health=1,deathrattle=P+'dead'))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=1,deathrattle=P+'weapon'))
    def held(c):return next(c.state.entities[i] for i in c.state.players[c.player_id].hand
        if c.state.entities[i].card_id==ORIGINAL)
    def ref(c):return CardReference.capture(held(c))
    def fail(c):raise ResolutionError('deliberate deck capacity rollback')
    bodies={
        'add':lambda c:(AddToDeck(c.player_id,PLAIN,source_id=c.source_id),),
        'top':lambda c:(AddToDeck(c.player_id,PLAIN,'top',c.source_id),),
        'group':lambda c:(ShuffleDeckCards(c.player_id,c.player_id,tuple(AddToDeck(c.player_id,PLAIN,source_id=c.source_id)for _ in range(3)),c.source_id),),
        'unknown':lambda c:(AddToDeck(c.player_id,'missing.deck.card',source_id=c.source_id),),
        'copy':lambda c:(CopyCard(ref(c),c.player_id,destination=Zone.DECK,source_id=c.source_id),),
        'copy_discover':lambda c:(RequestChoice(c.player_id,(ChoiceOption('copy','Copy original',
            (CopyCard(ref(c),c.player_id,destination=Zone.DECK,source_id=c.source_id),),card_id=ORIGINAL),),
            c.source_id,purpose=ChoicePurpose.CARD_DISCOVERY),),
        'move':lambda c:(MoveCard(ref(c),c.player_id,Zone.DECK,source_id=c.source_id),),
        'foreign':lambda c:(MoveCard(CardReference.capture(c.state.entities[c.state.players[2].deck[0]]),1,Zone.DECK,source_id=c.source_id),),
        'reorder':lambda c:(MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1,Zone.DECK,source_id=c.source_id),),
        'shuffle_hand':lambda c:(ShuffleIntoDeck(held(c).id),),
        'shuffle_board':lambda c:(ShuffleIntoDeck(c.state.players[1].board[-1],2),),
        'kill':lambda c:(Destroy(c.state.players[1].board[-1],c.source_id),),
        'break':lambda c:(ModifyWeapon(c.state.players[1].weapon_id,durability=-1),),
        'passage':lambda c:(ReplaceHandWithTemporaryDeckCards(c.player_id,4,c.source_id),),
        'fill99':lambda c:(ShuffleGeneratedCopies(c.player_id,c.player_id,PLAIN,99,c.source_id),),
        'fill98':lambda c:(ShuffleGeneratedCopies(c.player_id,c.player_id,PLAIN,max(0,98-len(c.state.players[c.player_id].deck)),c.source_id),),
        'fail':fail,
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    if mode:
        def watch(c):
            if mode=='depart':
                if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != P+'copy_discover':return ()
                return (MoveCard(ref(c),c.player_id,Zone.DECK,source_id=c.source_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Watcher',CardType.MINION,health=5,
            triggers=(TriggerSpec('choice_selected'if mode=='depart'else'card_added_to_deck'if mode=='insert'else'card_burned',P+'watch'),)))
    r.validate();r.freeze();return r


class RuntimeDeckCapacityTests(unittest.TestCase):
    def game(self,hand=(P+'add',),deck=99,enemy_deck=3,board=(),mode=None,weapon=False):
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,deck=(PLAIN,)*deck,
            board=(*((P+'watch',)if mode else()),*board),weapon_card_id=WEAPON if weapon else None,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup(HERO,deck=(PLAIN,)*enemy_deck)),seed=2872),registry('writer',mode))
    def play(self,g,cid):
        e=next(g.state.entities[i]for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(g.state.active_player,e.id,position=len(g.state.players[g.state.active_player].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,reader=None,mode=None):
        reader=reader or registry('reader',mode);snap=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(snap,reader)
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for pid in (1,2):
            view=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))
            for key in (FAILED,'original','receipt','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',view)
        return other
    def next_owner(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def failures(self,g):return [e for e in g.events if e.kind==FAILED]
    def rehash(self,snap):
        snap['events_hash']=canonical_hash(snap['events'])
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items()if k not in ('schema_version','events','events_hash','state_hash')})
        return snap

    def test_a01_generated_full_has_no_allocation_rng_or_successful_shuffle(self):
        for cid in (P+'add',P+'top'):
            g=self.game(hand=(cid,));before=g.snapshot();self.play(g,cid)
            self.assertEqual(g.state.next_entity_id,before['state']['next_entity_id'])
            self.assertEqual(g.snapshot()['rng_state'],before['rng_state']);self.assertEqual(len(g.state.players[1].deck),99)
            self.assertEqual(len(self.failures(g)),1);self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_a02_partial_group_keeps_original_count_and_only_one_actual_insertion(self):
        g=self.game(hand=(P+'group',),deck=98);self.play(g,P+'group')
        self.assertEqual(len(g.state.players[1].deck),99);self.assertEqual(len(self.failures(g)),2)
        row,=g.state.deck_shuffle_history;self.assertEqual((row.actor_id,row.declared_count),(1,3))
        self.assertEqual(sum(e.kind=='card_added_to_deck'for e in g.events),1);self.portable(g)

    def test_a03_unknown_card_still_rejects_when_full_and_rolls_back(self):
        g=self.game(hand=(P+'unknown',));before=g.snapshot()
        with self.assertRaises((ValueError,ResolutionError)):self.play(g,P+'unknown')
        self.assertEqual(g.snapshot(),before)

    def test_a04_copy_full_does_not_consume_or_burn_original(self):
        g=self.game(hand=(P+'copy',ORIGINAL));original=g.state.players[1].hand[-1];before=g.snapshot();self.play(g,P+'copy')
        self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.assertEqual(g.state.next_entity_id,before['state']['next_entity_id'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_a05_stored_original_overflow_is_destruction_without_board_death(self):
        g=self.game(hand=(P+'move',ORIGINAL));original=g.state.players[1].hand[-1];before=g.snapshot()['rng_state'];self.play(g,P+'move')
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertFalse(g.state.death_history)
        event,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(destruction_result(event).profile,'deck_overflow')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_a06_same_deck_reordering_is_allowed_at_full_capacity(self):
        g=self.game(hand=(P+'reorder',));ids=set(g.state.players[1].deck);self.play(g,P+'reorder')
        self.assertEqual(set(g.state.players[1].deck),ids);self.assertFalse(self.failures(g));self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_a07_other_deck_physical_transfer_overflow_keeps_owner_and_retires_once(self):
        g=self.game(hand=(P+'foreign',));original=g.state.players[2].deck[0];self.play(g,P+'foreign')
        e=g.state.entities[original];self.assertEqual((e.owner,e.controller,e.zone),(2,1,Zone.GRAVEYARD))
        self.assertEqual(len(g.state.players[2].deck),2);self.assertFalse(g.state.death_history);self.portable(g)

    def test_a08_board_full_shuffle_dies_in_original_control_and_runs_deathrattle(self):
        g=self.game(hand=(P+'shuffle_board',),enemy_deck=99,board=(ORIGINAL,));original=g.state.players[1].board[-1]
        before=g.snapshot()['rng_state'];self.play(g,P+'shuffle_board')
        death,=g.state.death_history;self.assertEqual((death.entity_id,death.controller),(original,1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_a09_hand_shuffle_overflow_runs_native_stored_destruction_only(self):
        g=self.game(hand=(P+'shuffle_hand',ORIGINAL));self.play(g,P+'shuffle_hand')
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)

    def test_a10_dead_minion_does_not_reset_reshuffle_or_consume_rng_when_full(self):
        g=self.game(hand=(P+'kill',),board=(DEAD,));original=g.state.players[1].board[-1];before=g.snapshot()['rng_state'];self.play(g,P+'kill')
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(len(self.failures(g)),1);self.portable(g)

    def test_a11_dead_weapon_does_not_reset_or_add_growth_when_full(self):
        g=self.game(hand=(P+'break',),weapon=True);original=g.state.players[1].weapon_id;before=g.snapshot()['rng_state'];self.play(g,P+'break')
        e=g.state.entities[original];self.assertEqual((e.zone,e.durability),(Zone.GRAVEYARD,0))
        self.assertFalse(e.enchantments);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_a12_partial_insertion_wait_is_atomic_and_failure_rolls_back(self):
        g=self.game(hand=(P+'group',),deck=98,mode='insert');before=g.snapshot();self.play(g,P+'group')
        self.assertEqual(len(self.failures(g)),2);other=self.portable(g,mode='insert');waiting=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),waiting)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,mode='insert')
        self.assertNotEqual(g.snapshot(),before)

    def test_a13_temporary_ordinary_return_preserves_original_hand_and_borrowed_entities(self):
        g=self.game(hand=(P+'passage',P+'fill99',ORIGINAL),deck=6)
        held=tuple(g.state.players[1].hand[1:]);self.play(g,P+'passage')
        self.assertEqual(len(g.state.temporary_hands[0].borrowed),4)
        self.next_owner(g);self.assertFalse(g.state.temporary_hands[0].deck_burned)
        self.assertTrue(set(held)<=set(g.state.players[1].hand));self.portable(g)

    def temporary_full(self,partial=False,mode=None):
        fill=P+('fill98'if partial else'fill99')
        # The fill effect is a genuinely borrowed physical card, not an edit.
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,hand=(P+'passage',ORIGINAL),
            board=(P+'watch',)if mode else(),deck=(fill,)*6,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup(HERO,deck=(PLAIN,)*6)),seed=2872),registry('writer',mode))
        self.play(g,P+'passage');self.play(g,fill);self.next_owner(g);return g

    def test_a14_temporary_full_return_retains_all_attempts_and_no_rng_for_failed_shuffle(self):
        g=self.temporary_full();root=g.state.temporary_hands[0]
        self.assertEqual(len(root.removed),3);self.assertEqual(root.deck_burned,root.removed)
        self.assertEqual(root.return_rng_before,root.return_rng_after);self.assertEqual(len(root.return_deck_after),99)
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(len(self.failures(g)),3);self.portable(g)

    def test_a15_temporary_partial_return_binds_prefix_success_and_suffix_overflow(self):
        g=self.temporary_full(True);root=g.state.temporary_hands[0]
        self.assertEqual(root.deck_burned,root.removed[1:]);self.assertIn(root.removed[0],root.return_deck_before)
        self.assertEqual(len(root.return_deck_after),99);self.assertEqual(g.state.deck_shuffle_history[-1].declared_count,3);self.portable(g)

    def test_a16_temporary_return_burn_wait_restores_complete_original_receipt(self):
        g=self.temporary_full(mode='burn');self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,mode='burn')
        while g.state.pending_choice:
            self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,mode='burn')

    def test_a17_oversized_experimental_input_cannot_grow_but_can_reorder(self):
        g=self.game(hand=(P+'add',P+'reorder'),deck=100);self.play(g,P+'add');self.play(g,P+'reorder')
        self.assertEqual(len(g.state.players[1].deck),100);self.assertEqual(len(self.failures(g)),1);self.portable(g)

    def test_a18_discovered_copy_of_departed_original_keeps_empty_recipient_without_fake_full_failure(self):
        for count in (3,99):
            g=self.game(hand=(P+'copy_discover',ORIGINAL),deck=count,mode='depart')
            self.play(g,P+'copy_discover');self.choose(g,'copy')
            event=next(e for e in g.events if e.kind=='card_discovered');self.assertIsNone(event.target_id)
            self.assertTrue(any(e.kind=='zone_target_skipped'for e in g.events));self.portable(g,mode='depart')

    def test_a19_rehashed_temporary_return_cannot_crop_all_failed_operands_or_borrow_another_group(self):
        g=self.temporary_full()
        for change in ('crop','borrow'):
            snap=json.loads(json.dumps(g.snapshot()))
            if change=='crop':
                root=snap['state']['temporary_hands'][0]
                root['removed']=[];root['deck_burned']=[]
                event=next(e for e in snap['events']if e['kind']=='temporary_deck_hand_restored')
                event['data']['removed']=[];event['data']['deck_burned']=[]
            else:
                event=next(e for e in snap['events']if e['kind']==FAILED)
                event['data']['temporary_hand_id']=2
            with self.assertRaises((ValueError,SnapshotError)) as error:
                Game.from_snapshot(self.rehash(snap),registry('reader'))
            self.assertIn('original temporary',str(error.exception))

    def vendor(self,count):
        import test_native_discovery_remainder_cards as v
        g=Game.from_scenario(Scenario((PlayerSetup(v.HERO,hand=(v.CARD,),deck=(v.PLAIN,)*count,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup(v.HERO,deck=(v.PLAIN,)*4)),seed=81,generation_context=v.CTX),v.registry('writer'))
        self.play(g,v.CARD);self.choose(g,g.state.pending_choice.options[0].id)
        return g,v

    def test_b01_real_vendor_partial_remainder_keeps_order_and_full_declared_count(self):
        g,v=self.vendor(98)
        finished=next(e for e in g.events if e.kind=='discovery_remainder_finished');cards=json.loads(dict(finished.data)['cards'])
        self.assertEqual(len(cards),2);self.assertIsNotNone(cards[0]);self.assertIsNone(cards[1])
        self.assertEqual(g.state.deck_shuffle_history[-1].declared_count,2);self.portable(g,v.registry('reader'))

    def test_b02_real_vendor_full_remainder_records_each_failure_without_shuffle(self):
        g,v=self.vendor(99);self.assertEqual(len(self.failures(g)),2);self.assertFalse(g.state.deck_shuffle_history)
        self.assertTrue(any(g.state.entities[i].card_id!=v.CARD for i in g.state.players[1].hand));self.portable(g,v.registry('reader'))

    def gift(self,count,selected_deck=True,real=False):
        import test_native_gift_remainders as v
        from hs_sim.engine.dark_gifts import public_gifts
        for seed in range(178,228):
            g=Game.from_scenario(Scenario((PlayerSetup(v.HERO,hand=(v.CARD if real else v.DISC,),deck=(v.FILL,)*count,
                mana=40,max_mana=40,mana_cap=40),PlayerSetup(v.HERO,deck=(v.FILL,)*3)),seed=seed,generation_context=v.CTX),
                v.registry('writer','full'if real else'EDR_100t8'))
            self.play(g,v.CARD if real else v.DISC)
            choices=g._frame.original_discovery_offer.options
            option=next((o for o in choices if (o.effects[0].selection.gift.id=='EDR_100t8')==selected_deck),None)
            if option is not None:
                self.choose(g,option.id);return g,v
        self.fail('Real native offer did not contain the requested existing gift')

    def test_b03_real_jumpscare_full_selected_deck_and_both_remainders_have_no_allocations(self):
        g,v=self.gift(99,real=True)
        self.assertEqual(len(self.failures(g)),3);self.assertFalse(g.state.deck_shuffle_history)
        queued=next(e for e in g.events if e.kind=='card_discovered');self.assertIsNone(queued.target_id)
        self.portable(g,v.registry('reader'))

    def test_b04_sweet_dreams_uses_last_slot_before_original_remainders_fail(self):
        g,v=self.gift(98);self.assertEqual(len(self.failures(g)),2);self.assertEqual(len(g.state.players[1].deck),99)
        recipient=next(e.target_id for e in g.events if e.kind=='card_discovered')
        from hs_sim.engine.dark_gifts import public_gifts
        self.assertEqual(public_gifts(g.state.entities[recipient])[0]['id'],'EDR_100t8')
        self.assertFalse(g.state.deck_shuffle_history);self.portable(g,v.registry('reader','EDR_100t8'))

    def test_b05_gifted_partial_remainders_keep_real_material_on_successful_original_slot(self):
        g,v=self.gift(98,False);self.assertEqual(len(self.failures(g)),1)
        from hs_sim.engine.dark_gifts import public_gifts
        success=g.state.deck_shuffle_history[-1].first_card
        self.assertEqual(len(public_gifts(g.state.entities[success.entity_id])),1);self.portable(g,v.registry('reader','EDR_100t8'))

    def test_b06_real_kong_zo_full_opponent_top_has_empty_actual_recipient(self):
        import test_discovered_spell_destination_card as v
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(v.CARD,),deck=(v.FILL,)*3,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(v.FILL,)*99)),seed=224517,generation_context=v.CTX),v.registry(None,v.MEMBERS,'writer'))
        self.play(g,v.CARD);self.choose(g,g.state.pending_choice.options[0].id);before=g.snapshot()['rng_state']
        self.choose(g,v.OPTIONS[1]);event=next(e for e in g.events if e.kind=='card_discovered')
        self.assertIsNone(event.target_id);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(len(g.state.players[2].deck),99);self.portable(g,v.registry(None,v.MEMBERS,'reader'))

    def test_b07_real_opponent_copy_sweet_dreams_full_has_no_borrowed_new_entity(self):
        import test_opponent_deck_gift_copy_card as v
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(v.PREP,v.CARD),deck=(v.FILL,)*99,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(v.A,))),seed=v.gift_seed('EDR_100t8')),v.registry(None,'writer'))
        self.play(g,v.PREP);self.play(g,v.CARD);self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual(len(self.failures(g)),1);self.assertIsNone(next(e.target_id for e in g.events if e.kind=='card_discovered'))
        self.portable(g,v.registry(None,'reader'))

    def test_b08_rehashed_cropped_partial_remainder_or_changed_failure_cannot_restore(self):
        g,v=self.vendor(98)
        for field in ('cards','failure'):
            snap=json.loads(json.dumps(g.snapshot()))
            if field=='cards':
                event=next(e for e in snap['events']if e['kind']=='discovery_remainder_finished')
                event['data']['cards']=json.dumps(json.loads(event['data']['cards'])[:1])
            else:
                event=next(e for e in snap['events']if e['kind']==FAILED)
                event['data']['deck_size']=98
            with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(self.rehash(snap),v.registry('reader'))
