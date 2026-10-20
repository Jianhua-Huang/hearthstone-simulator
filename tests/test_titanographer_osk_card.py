"""Original Osk delegates real Battlecries while physical hand identity stays fixed."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.titanographer_osk_card import CARD,RULE,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardType,CostSpec,DeckPolicy,DeckSpec,EndTurn,
    Game,IllegalAction,MatchSetup,PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,
    SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.battlecries import capture
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.held_battlecry_forms import HeldBattlecryFormsProfile,PUBLICATION,public_form,validate_game,validate_profile
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard

P='fixture.osk.held.';UNIT=P+'unit';WATCH=P+'watch';FROST='CORE_CS2_024'
FORMS=tuple(load_batch()['forms'])


@lru_cache(maxsize=None)
def seed_for(form):
    return next(seed for seed in range(10000)if Random(seed).choice(FORMS)==form)


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=4,attack=4,health=7))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def fail(c):raise ResolutionError('Osk native selection reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    scripts={
        'get':lambda c:(AddToHand(c.player_id,CARD,c.source_id),),
        'draw':lambda c:(Draw(c.player_id,1,c.source_id),),
        'copy':lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        'base':lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        'buff':lambda c:(BuffStoredCard(ref(c),3,4,c.source_id,cost=CostSpec(delta=-2)),),
        'transfer':lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        'shuffle':lambda c:(MoveCard(ref(c),c.player_id,Zone.DECK,'top',reset=True,source_id=c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if name in('copy','base','buff','transfer','shuffle')
                else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')if name=='bounce'else None))
    def watch(c):
        d=dict(c.event.data)
        if mode=='entry_fail'and d['mode']=='initial_random'and c.state.hand_entries[d['hand_entry_id']-1].reason=='created':
            return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='turn_wait'and d['mode']=='owner_start_random':
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,triggers=(TriggerSpec(PUBLICATION,P+'watch'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class OskHeldBattlecryTests(unittest.TestCase):
    def game(self,form='TLC_452t13',hand=None,deck=None,board=(),enemy=(),mode='normal',active=1,second=False,cap=10):
        hand=(CARD,)if hand is None else hand;deck=(UNIT,)*10 if deck is None else deck
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==active else((CARD,)if second else()),deck=deck,
            board=(((WATCH,)if mode!='normal'else())+board)if p==active else enemy,max_mana=10,mana=10,hand_cap=cap)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=seed_for(form)),fixture(mode))
    def roots(self,g,p=None):return[g.state.entities[i]for i in g.state.players[p or g.state.active_player].hand if g.state.entities[i].card_id==CARD]
    def form(self,g,e):return public_form(g.registry,g.state.entities[e.id])
    def play(self,g,card=CARD,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==card)
        g.apply(PlayCard(p,eid,target));return eid
    def receipts(self,g):return[e for e in g.events if e.kind==PUBLICATION]
    def portable(self,g,mode='normal'):
        s=g.snapshot();r=fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return Game.from_snapshot(s,r)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_complete_original_root_all31_existing_bodies_and64_primary_faces(self):
        d=load_batch();r=fixture();root=r.card(CARD)
        self.assertEqual((root.cost,root.attack,root.health),(6,6,6));self.assertTrue(root.metadata.collectible)
        self.assertEqual(len(d['official_observations']),64);self.assertEqual(len(d['existing_dependencies']),31)
        self.assertEqual(r.held_battlecry_forms_profiles[CARD].forms,FORMS)
        self.assertIsNone(root.battlecry);self.assertEqual(root.target_rule,RULE)

    def test_native_profile_rejects_duplicate_unknown_and_incompatible_forms(self):
        with self.assertRaises(ValueError):HeldBattlecryFormsProfile(CARD,(FORMS[0],FORMS[0]))
        with self.assertRaises(ValueError):HeldBattlecryFormsProfile(CARD,(CARD,))
        with self.assertRaisesRegex(ValueError,'unsupported card definition'):validate_profile(fixture(),HeldBattlecryFormsProfile(CARD,('unknown.osk',)))
        with self.assertRaises(ValueError):validate_profile(fixture(),HeldBattlecryFormsProfile(CARD,(UNIT,)))

    def test_each_actual_form_can_be_selected_without_replacing_physical_card_or_stats(self):
        for form in FORMS:
            with self.subTest(form=form):
                g=self.game(form);e=self.roots(g)[0];payload=capture(e)
                self.assertEqual(self.form(g,e),form);self.assertEqual((e.card_id,e.attack,e.max_health),(CARD,6,6))
                self.assertEqual((payload[0].card_id,payload[0].behavior_id),(form,g.registry.card(form).battlecry))
                self.assertEqual(g.state.hand_entries[e.hand_entry_id-1].card_id,CARD)
                self.assertEqual(len(self.receipts(g)),1)

    def test_real_six_mana_root_plays_selected_damage_with_original_root_and_body_history(self):
        g=self.game();eid=self.roots(g)[0].id;hero=g.state.players[2].hero_id;self.play(g,target=hero)
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(g.state.entities[hero].health,25)
        self.assertEqual(g.state.play_history[-1].card_id,CARD)
        self.assertEqual((g.state.battlecry_history[-1].card_id,g.state.battlecry_history[-1].payload.card_id),(CARD,'TLC_452t13'))
        self.assertEqual(g.state.entities[eid].card_id,CARD);self.portable(g)

    def test_owner_start_only_reselects_held_owner_without_changing_slot_or_residence(self):
        g=self.game(second=True);left=self.roots(g,1)[0];right=self.roots(g,2)[0]
        initial={e.id:(e.zone_epoch,e.hand_entry_id,capture(e)[0].ability_id)for e in(left,right)}
        left_form=self.form(g,left);g.apply(EndTurn(1));self.assertEqual(self.form(g,left),left_form)
        self.assertEqual(self.receipts(g)[-1].source_id,right.id);g.apply(EndTurn(2))
        self.assertEqual(self.receipts(g)[-1].source_id,left.id);self.assertEqual(len(self.receipts(g)),4)
        for e in(left,right):
            now=g.state.entities[e.id];self.assertEqual((now.zone_epoch,now.hand_entry_id,capture(now)[0].ability_id),initial[e.id])
        for event in self.receipts(g):self.assertEqual(tuple(dict(event.data)['candidates']),FORMS)

    def test_hand_buffs_and_cost_attachment_survive_reselection_on_the_original_object(self):
        g=self.game(hand=(CARD,P+'buff'));e=self.roots(g)[0];self.play(g,P+'buff',e.id)
        before=g.state.entities[e.id];attachments=tuple(before.enchantments)
        g.apply(EndTurn(1));g.apply(EndTurn(2));e=g.state.entities[e.id]
        self.assertEqual((e.card_id,e.attack,e.max_health,quote_cost(g.state,g.registry,e).amount),(CARD,9,10,4))
        self.assertEqual(tuple(e.enchantments),attachments)

    def test_fresh_acquisition_gets_a_body_before_notification_and_original_deck_waits(self):
        g=self.game(hand=(P+'get',P+'draw'),deck=(CARD,))
        deck_id=g.state.players[1].deck[0];self.assertFalse(capture(g.state.entities[deck_id]));self.play(g,P+'get')
        fresh=self.roots(g)[0];self.assertIn(self.form(g,fresh),FORMS)
        self.play(g,P+'draw');self.assertEqual(len(self.roots(g)),2);self.assertIn(self.form(g,g.state.entities[deck_id]),FORMS)
        self.assertEqual(len(self.receipts(g)),2)

    def test_native_root_drawn_by_real_set_to_two_branch_keeps_its_original_arrival(self):
        g=self.game('TLC_452t18',deck=(CARD,UNIT));self.play(g)
        self.assertEqual(len(g.state.players[1].hand),2)
        for eid in g.state.players[1].hand:
            e=g.state.entities[eid];self.assertEqual((e.attack,e.max_health,quote_cost(g.state,g.registry,e).amount),(2,2,2))
        self.assertIn(self.form(g,self.roots(g)[0]),FORMS)

    def test_current_copy_keeps_selected_body_and_buffs_but_owns_new_slot_without_rng(self):
        g=self.game(hand=(CARD,P+'buff',P+'copy'));original=self.roots(g)[0];self.play(g,P+'buff',original.id)
        form=self.form(g,original);rng=g._rng.getstate();self.play(g,P+'copy',original.id);roots=self.roots(g)
        self.assertEqual(len(roots),2);copy=next(e for e in roots if e.id!=original.id)
        self.assertEqual(self.form(g,copy),form);self.assertEqual((copy.attack,copy.max_health),(9,10))
        self.assertNotEqual(capture(copy)[0].ability_id,capture(g.state.entities[original.id])[0].ability_id)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(dict(self.receipts(g)[-1].data)['mode'],'inherited')
        self.portable(g)

    def test_printed_base_copy_starts_its_own_selection_and_does_not_copy_local_buffs(self):
        g=self.game(hand=(CARD,P+'buff',P+'base'));original=self.roots(g)[0];self.play(g,P+'buff',original.id)
        self.play(g,P+'base',original.id);copy=next(e for e in self.roots(g)if e.id!=original.id)
        self.assertEqual((copy.attack,copy.max_health,quote_cost(g.state,g.registry,copy).amount),(6,6,6))
        self.assertEqual(dict(self.receipts(g)[-1].data)['mode'],'initial_random')

    def test_returned_root_gets_new_hand_residence_and_normal_reset_then_selection(self):
        g=self.game(hand=(CARD,P+'bounce'));e=self.roots(g)[0];old_entry=e.hand_entry_id
        self.play(g,target=g.state.players[2].hero_id);self.play(g,P+'bounce',e.id);e=g.state.entities[e.id]
        self.assertEqual((e.card_id,e.zone,e.attack,e.max_health),(CARD,Zone.HAND,6,6))
        self.assertGreater(e.hand_entry_id,old_entry);self.assertIn(self.form(g,e),FORMS)
        self.assertEqual(dict(self.receipts(g)[-1].data)['mode'],'initial_random');self.portable(g)

    def test_actual_transfer_preserves_form_then_new_holder_owns_next_rotation(self):
        g=self.game(hand=(CARD,P+'transfer'));e=self.roots(g)[0];form=self.form(g,e)
        self.play(g,P+'transfer',e.id);self.assertEqual(self.form(g,e),form)
        self.assertEqual(g.state.entities[e.id].controller,2);self.assertEqual(dict(self.receipts(g)[-1].data)['mode'],'inherited')
        g.apply(EndTurn(1));self.assertEqual(self.receipts(g)[-1].player_id,2);self.portable(g)

    def test_reset_shuffle_retires_held_body_and_later_actual_draw_creates_new_selection(self):
        g=self.game(hand=(CARD,P+'shuffle',P+'draw'));e=self.roots(g)[0]
        self.play(g,P+'shuffle',e.id);self.assertFalse(capture(g.state.entities[e.id]))
        self.play(g,P+'draw');self.assertIn(self.form(g,e),FORMS)
        self.assertEqual(dict(self.receipts(g)[-1].data)['mode'],'initial_random')

    def test_all_five_actual_target_shapes_follow_selected_form_and_nontarget_body_has_none(self):
        for form in('TLC_452t1','TLC_452t13','TLC_452t19','TLC_452t26','TLC_452t35','TLC_452t2'):
            with self.subTest(form=form):
                g=self.game(form,board=(UNIT,),enemy=(UNIT,'TTN_903'))
                eid=self.roots(g)[0].id;actions=[x for x in g.legal_actions()if isinstance(x,PlayCard)and x.entity_id==eid]
                target_ids={x.target_id for x in actions};own=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
                if form=='TLC_452t2':self.assertEqual(target_ids,{None});continue
                self.assertIn(enemy,target_ids)
                self.assertEqual(own in target_ids,form in('TLC_452t13','TLC_452t19','TLC_452t26'))
                self.assertEqual(g.state.players[2].hero_id in target_ids,form=='TLC_452t13')
                if form=='TLC_452t19':self.assertNotIn(g.state.players[2].board[1],target_ids)

    def test_real_root_copy_branch_and_paired_spell_bonus_delegate_existing_shared_effects(self):
        g=self.game('TLC_452t19',board=(UNIT,));target=g.state.players[1].board[0];self.play(g,target=target)
        copied=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].origin_entity_id==target)
        self.assertEqual((copied.attack,copied.max_health),(6,9))
        g=self.game('TLC_452t2',hand=(CARD,FROST));hero=g.state.players[2].hero_id;self.play(g)
        self.play(g,FROST,hero);self.assertEqual((g.state.players[1].mana,g.state.entities[hero].health),(4,24))

    def test_real_root_remove_two_uses_body_domain_and_restores_original_public_choice(self):
        g=self.game('TLC_452t21',enemy=(UNIT,UNIT));targets=tuple(g.state.players[2].board)
        self.play(g);q=g.state.pending_choice
        self.assertIsNotNone(q);self.assertEqual((q.min_count,q.max_count),(2,2))
        self.assertEqual({o.entity_id for o in q.options},set(targets));restored=self.portable(g)
        for current in(g,restored):
            choice=current.state.pending_choice
            current.apply(SelectChoice(choice.player_id,choice.id,tuple(o.id for o in choice.options)))
            self.assertTrue(all(current.state.entities[i].zone==Zone.SETASIDE for i in targets))
            self.assertFalse(current.state.death_history)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_real_root_control_uses_original_paid_target_and_preserves_selected_body(self):
        g=self.game('TLC_452t35',enemy=(UNIT,));target=g.state.players[2].board[0]
        self.play(g,target=target);self.assertEqual(g.state.entities[target].controller,1)
        self.assertIn(target,g.state.players[1].board);self.assertFalse(g.state.players[2].board)
        self.assertEqual(g.state.battlecry_history[-1].payload.card_id,'TLC_452t35')

    def test_other_native_targeted_and_group_rewards_use_the_physical_root(self):
        g=self.game('TLC_452t1',enemy=(UNIT,));eid=self.roots(g)[0].id;target=g.state.players[2].board[0]
        self.play(g,target=target);self.assertEqual(g.state.entities[eid].max_health,13)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].max_health,37)
        g=self.game('TLC_452t26',enemy=(UNIT,));target=g.state.players[2].board[0]
        self.play(g,target=target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game('TLC_452t17',board=(UNIT,));target=g.state.players[1].board[0]
        eid=self.play(g);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(6,9))
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(6,6))

    def test_waiting_owner_start_restores_independently_and_failed_resume_keeps_same_selection(self):
        g=self.game(mode='turn_wait');g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();restored=self.portable(g,'turn_wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_failed_acquisition_reaction_rolls_back_new_root_rng_and_native_selection(self):
        g=self.game(hand=(P+'get',),mode='entry_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'get')
        self.assertEqual(g.snapshot(),saved)

    def test_private_hand_form_is_visible_to_holder_and_public_only_after_play(self):
        g=self.game();e=self.roots(g)[0];form=self.form(g,e)
        own=g.observe(1);opponent=g.observe(2)
        self.assertEqual(own['players'][0]['hand'][0]['battlecry_form'],form)
        self.assertNotIn(form,json.dumps(opponent));self.assertNotIn(PUBLICATION,json.dumps(opponent))
        for key in('rng_before','rng_after','candidates','ability_id'):self.assertNotIn(key,json.dumps(own))
        self.play(g,target=g.state.players[2].hero_id)
        self.assertEqual(g.observe(2)['players'][0]['board'][0]['battlecry_form'],form)

    def test_rehashed_missing_or_changed_random_receipt_cannot_replace_current_native_body(self):
        g=self.game();saved=g.snapshot();index=next(i for i,e in enumerate(g.events)if e.kind==PUBLICATION)
        for field,value in(('selected','unknown.osk'),('candidates',()),('ability_id',True),('mode','inherited')):
            bad=deepcopy(saved);raw=bad['events'][index];data=dict(raw['data']);data[field]=value;raw['data']=data
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())
        forged=g.clone();forged._events[index]=replace(forged._events[index],kind='stored_card_buffed')
        with self.assertRaisesRegex(ValueError,'complete current selection'):validate_game(forged)

    def test_second_actor_plays_root_with_same_original_body_and_player_target_input(self):
        g=self.game(active=2);self.play(g,target=g.state.players[1].hero_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,25)
        self.assertEqual(g.state.battlecry_history[-1].player_id,2)

    def test_actual_opening_defers_random_selection_until_mulligan_finishes(self):
        cards=(CARD,)+(FROST,)*11;policy=DeckPolicy('osk.opening','osk.experimental','experimental',(CARD,FROST),deck_size=12,max_copies=12)
        selected=None
        for seed in range(20):
            g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),
                policy,'GAME_005',seed=seed,first_player=1),fixture())
            if self.roots(g,1)or self.roots(g,2):selected=g;break
        self.assertIsNotNone(selected);g=selected;self.assertFalse(self.receipts(g))
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(g.state.opening.stage,'complete')
        for p in(1,2):
            for e in self.roots(g,p):self.assertIn(self.form(g,e),FORMS)
        self.portable(g)


if __name__=='__main__':unittest.main()
