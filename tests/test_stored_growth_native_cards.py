"""Real attacking beneficiaries and one native hand/deck growing instance."""
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.stored_growth_native_cards import load_batch
from hs_sim.engine import (Attack, AuraSpec, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, Game, HandProgressSpec, PlayCard, PlayerSetup, Scenario,
    SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy,
    Draw, ForceAttack, GainArmor, Heal, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_progress import progress_ability, public_progress
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference, SetCapturedMinionStats
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

ARCH='TLC_811';STEG='TLC_827';PLAIN='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def registry(mode=None):
    r=build_registry()
    scripts=dict(hit=lambda c:(Damage(c.target_id,3,c.source_id),),
        heal=lambda c:(Heal(c.target_id,99,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),
        arm=lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=1,source_id=c.source_id),),
        draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),
        force=lambda c:(ForceAttack(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id=='k53.runner'),c.state.players[3-c.player_id].board[0]),),
        set=lambda c:(SetCapturedMinionStats(MinionReference.capture(c.state.entities[c.target_id]),
            health=7,source_id=c.source_id),),
        fault=lambda c:(SetCapturedMinionStats(MinionReference.capture(c.state.entities[c.target_id]),
            health=7,source_id=c.source_id),AddToHand(c.player_id,'missing.k53',c.source_id)),
        copy_current=lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==STEG)),c.player_id,mode='current'),),
        copy_base=lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==STEG)),c.player_id,mode='base'),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k53',c.source_id),),
        reenter=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id,cause=SummonCause.capture(c)),))
    for key,body in scripts.items():
        r.register_behavior('k53.'+key,body)
        if key not in('fail','reenter'):
            r.register_card(CardDefinition('k53.'+key,key,CardType.SPELL,cost=1,on_play='k53.'+key,
                requires_target=key in('hit','heal','silence','bounce','set','fault'),metadata=META))
    for name,attack,health,extra in [('runner',2,4,{}),('enemy',2,20,{}),
            ('aura',0,5,dict(auras=(AuraSpec(0,health=2),)))]:
        r.register_card(CardDefinition('k53.'+name,name,CardType.MINION,attack=attack,health=health,metadata=META,**extra))
    if mode:
        def watch(c):
            event=c.event
            if event.kind=='attack_declared':
                if c.state.entities[event.source_id].card_id!='k53.runner':return ()
                arch=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ARCH)
                effects=(ReturnToHand(event.source_id),InvokeBehavior('k53.reenter',c.source_id,c.player_id,event.source_id))if mode=='target_reentry'else(
                    (Destroy(arch,c.source_id),)if mode=='source_death'else(
                    (Damage(arch,3,c.source_id),)if mode=='source_damage'else(GainArmor(c.player_id,0),)))
            elif event.kind=='turn_ended':
                if event.player_id!=c.player_id:return ()
                zone=Zone.DECK if mode=='deck_to_hand'else Zone.HAND
                target=next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone.value)
                    if c.state.entities[i].card_id==STEG)
                effects=(MoveCard(CardReference.capture(target),c.player_id,
                    Zone.HAND if zone==Zone.DECK else Zone.DECK,source_id=c.source_id),)
            else:
                if c.state.entities[event.target_id].card_id!=STEG:return ()
                effects=(GainArmor(c.player_id,0),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
                ChoiceOption('bad','Fail',(InvokeBehavior('k53.fail',c.source_id,c.player_id),))),c.source_id),)
        event='turn_ended'if mode in('hand_to_deck','deck_to_hand')else(
            'hand_progressed'if mode=='growth_wait'else'attack_declared')
        r.register_behavior('k53.watch',watch)
        r.register_card(CardDefinition('k53.watch','Native boundary observer',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,'k53.watch'),),metadata=META))
    return r


class StoredGrowthNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),deck=None,enemy=(),other=(),active=1,mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,
            deck=(PLAIN,)*8 if deck is None else deck,mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('test.hero',hand=other,board=enemy,deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60)),
            active_player=active,seed=1053),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        e=self.entity(g,cid,p,'hand');g.apply(PlayCard(p,e.id,target));return e.id
    def hero(self,g,p=1):s=g.state;return s.players[p].hero_id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def attack(self,g):
        target=self.entity(g,'k53.runner').id
        result=g.apply(Attack(1,target,self.entity(g,'k53.enemy',2).id));return target,result
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def test_complete_printed_faces_keep_zero_attack_explicit_and_beast_metadata(self):
        rows=load_batch()['cards'];self.assertEqual(len(rows),2)
        for row in rows:
            raw=row['record'];card=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack']or 0,raw['health']))
            self.assertEqual(card.metadata.tribes,('beast',))
        raw=next(x['record']for x in rows if x['record']['id']==STEG)
        self.assertIsNone(raw['attack']);self.assertNotIn('ATK',raw['tags']);self.assertEqual(self.r.card(STEG).attack,0)
    def test_both_real_cards_pay_three_mana(self):
        for cid in(ARCH,STEG):
            g=self.game((cid,));self.play(g,cid);self.assertEqual(g.state.players[1].mana,57)
    def test_other_friendly_attack_sets_health_before_combat(self):
        g=self.game(board=(ARCH,'k53.runner'),enemy=('k53.enemy',));target,result=self.attack(g)
        e=g.state.entities[target];self.assertEqual((e.health,e.max_health,e.damage),(4,6,2))
        self.assertEqual(sum(x.kind=='stats_changed'and x.target_id==target for x in result.events),1);self.portable(g)
    def test_wounded_source_supplies_remaining_health_and_target_damage_is_cleared(self):
        g=self.game(('k53.hit','k53.hit'),board=(ARCH,'k53.runner'),enemy=('k53.enemy',))
        self.play(g,'k53.hit',self.entity(g,ARCH).id);self.play(g,'k53.hit',self.entity(g,'k53.runner').id)
        target,result=self.attack(g);e=g.state.entities[target];self.assertEqual((e.health,e.max_health,e.damage),(1,3,2))
        self.assertFalse(any(x.kind=='healed'for x in result.events));self.portable(g)
    def test_self_attack_does_not_trigger(self):
        g=self.game(board=(ARCH,),enemy=('k53.enemy',));source=self.entity(g,ARCH).id
        result=g.apply(Attack(1,source,self.entity(g,'k53.enemy',2).id))
        self.assertEqual(g.state.entities[source].health,4);self.assertFalse(any(e.kind=='stats_changed'for e in result.events))
    def test_hero_attacks_do_not_trigger_the_minion_only_body(self):
        g=self.game(('k53.arm',),board=(ARCH,),enemy=('k53.enemy',));self.play(g,'k53.arm')
        result=g.apply(Attack(1,self.hero(g),self.entity(g,'k53.enemy',2).id))
        self.assertEqual(g.state.entities[self.hero(g)].max_health,30);self.assertFalse(any(e.kind=='stats_changed'for e in result.events))
    def test_opponent_attacks_do_not_trigger(self):
        g=self.game(board=(ARCH,),enemy=('k53.runner',),active=2)
        source=self.entity(g,'k53.runner',2).id;g.apply(Attack(2,source,self.hero(g)))
        self.assertEqual(g.state.entities[source].max_health,4)
    def test_defending_friendly_minion_does_not_count_as_attacking(self):
        g=self.game(board=(ARCH,'k53.runner'),enemy=('k53.enemy',),active=2);target=self.entity(g,'k53.runner').id
        g.apply(Attack(2,self.entity(g,'k53.enemy',2).id,target));self.assertEqual(g.state.entities[target].max_health,4)
    def test_silenced_archaios_has_no_attack_notification_body(self):
        g=self.game(('k53.silence',),board=(ARCH,'k53.runner'),enemy=('k53.enemy',));self.play(g,'k53.silence',self.entity(g,ARCH).id)
        target,_=self.attack(g);self.assertEqual(g.state.entities[target].max_health,4)
    def test_forced_attack_uses_the_same_real_attack_declaration(self):
        g=self.game(('k53.runner','k53.force'),board=(ARCH,),enemy=('k53.enemy',));target=self.play(g,'k53.runner');self.play(g,'k53.force')
        self.assertEqual(g.state.entities[target].max_health,6);self.assertTrue(g.state.character_attack_history[0].declaration.forced);self.portable(g)
    def test_original_attacker_reentry_cannot_receive_the_old_setter(self):
        mode='target_reentry';g=self.game(board=('k53.watch',ARCH,'k53.runner'),enemy=('k53.enemy',),mode=mode)
        target,_=self.attack(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g,mode);self.choose(g)
        self.assertEqual(g.state.entities[target].max_health,4);self.assertGreater(g.state.entities[target].zone_epoch,0);self.portable(g,mode)
    def test_accepted_source_health_is_not_recomputed_after_earlier_reaction(self):
        mode='source_damage';g=self.game(board=('k53.watch',ARCH,'k53.runner'),enemy=('k53.enemy',),mode=mode)
        target,_=self.attack(g);self.choose(g)
        self.assertEqual(self.entity(g,ARCH).health,3);self.assertEqual(g.state.entities[target].max_health,6);self.portable(g,mode)
    def test_accepted_setter_survives_later_source_death(self):
        mode='source_death';g=self.game(board=('k53.watch',ARCH,'k53.runner'),enemy=('k53.enemy',),mode=mode)
        target,_=self.attack(g);arch=self.entity(g,ARCH).id;self.choose(g)
        self.assertEqual(g.state.entities[arch].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[target].max_health,6);self.portable(g,mode)
    def test_bad_attack_choice_restores_original_waiting_boundary(self):
        mode='attack_wait';g=self.game(board=('k53.watch',ARCH,'k53.runner'),enemy=('k53.enemy',),mode=mode)
        self.attack(g);waiting=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),waiting);self.choose(g);self.portable(g,mode)
    def test_captured_setter_uses_shared_ordered_stat_layer_and_silence(self):
        g=self.game(('k53.set','k53.silence'),board=('k53.runner','k53.aura'));target=self.entity(g,'k53.runner').id
        self.play(g,'k53.set',target);self.assertEqual(g.state.entities[target].max_health,9)
        self.play(g,'k53.silence',target);self.assertEqual(g.state.entities[target].max_health,6)
    def test_failure_after_shared_setter_rolls_back_payment_stats_and_history(self):
        g=self.game(('k53.fault',),board=('k53.runner',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k53.fault',self.entity(g,'k53.runner').id)
        self.assertEqual(g.snapshot(),before)
    def test_captured_setter_codec_roundtrips_original_reference(self):
        g=self.game(board=(ARCH,'k53.runner'));effect=SetCapturedMinionStats(MinionReference.capture(self.entity(g,'k53.runner')),health=6,source_id=self.entity(g,ARCH).id)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(effect)),effect)
    def test_captured_setter_codec_rejects_unknown_and_future_allocations(self):
        g=self.game(board=(ARCH,'k53.runner'));ref=MinionReference.capture(self.entity(g,'k53.runner'))
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        for bad in(replace(ref,entity_id=999999),replace(ref,zone_epoch=ref.zone_epoch+1),replace(ref,entered_order=g.state.next_order)):
            with self.assertRaises(ValueError):codec.encode(SetCapturedMinionStats(bad,health=6))
        with self.assertRaises(ValueError):codec.encode(SetCapturedMinionStats(ref,health=6,source_id=999999))
    def test_captured_setter_requires_real_reference_and_valid_stat(self):
        g=self.game(board=('k53.runner',));ref=MinionReference.capture(self.entity(g,'k53.runner'))
        for kwargs in(dict(),dict(health=-1),dict(health=True)):
            with self.assertRaises(ValueError):SetCapturedMinionStats(ref,**kwargs)
        with self.assertRaises(ValueError):SetCapturedMinionStats(ref.entity_id,health=6)
    def test_own_end_grows_board_hand_and_deck_once_each(self):
        g=self.game((STEG,),board=(STEG,),deck=(STEG,PLAIN));g.apply(EndTurn(1));s=g.state
        for zone in('board','hand','deck'):self.assertEqual(self.entity(g,STEG,zone=zone).attack,1)
        self.assertEqual([progress_ability(self.entity(g,STEG,zone=z)).progress_completions for z in('hand','deck')],[1,1]);self.portable(g)
    def test_opponent_end_does_not_grow_held_deck_or_board_carriers(self):
        g=self.game((STEG,),board=(STEG,),deck=(PLAIN,STEG),active=2);g.apply(EndTurn(2))
        for zone in('board','hand','deck'):self.assertEqual(self.entity(g,STEG,zone=zone).attack,0)
    def test_multiple_same_name_carriers_have_one_completion_per_physical_card(self):
        g=self.game((STEG,STEG),deck=(STEG,STEG),board=(STEG,STEG));g.apply(EndTurn(1));s=g.state
        cards=[e for e in s.entities.values()if e.card_id==STEG];self.assertEqual(len(cards),6);self.assertEqual([e.attack for e in cards],[1]*6)
        ids=[progress_ability(e).id for e in cards];self.assertEqual(len(set(ids)),6)
    def test_repeated_owner_ends_stack_without_duplicate_completion(self):
        g=self.game((STEG,),deck=(PLAIN,PLAIN,STEG));self.cycle(g);g.apply(EndTurn(1))
        self.assertEqual(self.entity(g,STEG,zone='hand').attack,2);self.assertEqual(self.entity(g,STEG,zone='deck').attack,2)
        self.assertEqual(progress_ability(self.entity(g,STEG,zone='hand')).progress_completions,2);self.portable(g)
    def test_draw_preserves_original_deck_growth_and_renews_listener_identity(self):
        g=self.game(deck=(STEG,PLAIN));before=self.entity(g,STEG,zone='deck');self.cycle(g);after=g.state.entities[before.id]
        self.assertEqual((after.zone,after.attack),(Zone.HAND,1));self.assertNotEqual(progress_ability(before).id,progress_ability(after).id)
        self.assertEqual(progress_ability(after).progress_completions,1);self.portable(g)
    def test_hand_play_preserves_growth_and_board_still_grows_only_once(self):
        g=self.game((STEG,));self.cycle(g);target=self.play(g,STEG);self.assertEqual(g.state.entities[target].attack,1)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].attack,2);self.portable(g)
    def test_return_from_board_resets_ordinary_growth_then_native_hand_grows(self):
        g=self.game(('k53.bounce',),board=(STEG,));target=self.entity(g,STEG).id;self.cycle(g);self.play(g,'k53.bounce',target)
        self.assertEqual(g.state.entities[target].attack,0);g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].attack,1)
    def test_current_and_base_copies_use_shared_material_policies(self):
        g=self.game((STEG,'k53.copy_current','k53.copy_base'));self.cycle(g);self.play(g,'k53.copy_current');self.play(g,'k53.copy_base');s=g.state
        cards=[s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==STEG]
        self.assertEqual([e.attack for e in cards],[1,1,0]);self.assertEqual([progress_ability(e).progress_completions for e in cards],[1,1,0]);self.portable(g)
    def test_silenced_board_carrier_does_not_grow(self):
        g=self.game(('k53.silence',),board=(STEG,));target=self.entity(g,STEG).id;self.play(g,'k53.silence',target);g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].attack,0)
    def test_pre_growth_hand_to_deck_move_expires_old_event_candidate(self):
        mode='hand_to_deck';g=self.game((STEG,),board=('k53.watch',),deck=(PLAIN,),mode=mode);target=self.entity(g,STEG,zone='hand').id
        g.apply(EndTurn(1));self.portable(g,mode);self.choose(g);e=g.state.entities[target]
        self.assertEqual((e.zone,e.attack,progress_ability(e).progress_completions),(Zone.DECK,0,0));self.portable(g,mode)
    def test_pre_growth_deck_to_hand_move_does_not_rebind_old_witness(self):
        mode='deck_to_hand';g=self.game(board=('k53.watch',),deck=(STEG,),mode=mode);target=self.entity(g,STEG,zone='deck').id
        g.apply(EndTurn(1));self.choose(g);e=g.state.entities[target]
        self.assertEqual((e.zone,e.attack,progress_ability(e).progress_completions),(Zone.HAND,0,0));self.portable(g,mode)
    def test_private_progress_wait_restores_and_does_not_duplicate_growth(self):
        mode='growth_wait';g=self.game((STEG,),mode=mode,board=('k53.watch',));target=self.entity(g,STEG,zone='hand').id
        g.apply(EndTurn(1));other=self.portable(g,mode);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].attack,1);self.portable(g,mode)
    def test_bad_progress_choice_rolls_back_only_to_waiting_boundary(self):
        mode='growth_wait';g=self.game((STEG,),mode=mode,board=('k53.watch',));g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.entity(g,STEG,zone='hand').attack,1)
    def test_native_pair_is_one_instance_and_accepts_only_typed_ordered_scope(self):
        spec=self.r.card(STEG).hand_progress;self.assertEqual(spec.zones,(Zone.HAND,Zone.DECK))
        for bad in((Zone.DECK,Zone.HAND),(Zone.HAND,Zone.HAND),(Zone.BOARD,),('hand','deck'),[Zone.HAND,Zone.DECK],()):
            with self.assertRaises(ValueError):replace(spec,zone=bad)
        for good in(Zone.HAND,Zone.DECK):self.assertEqual(replace(spec,zone=good).zones,(good,))
    def test_deck_pair_keeps_restricted_repeat_minion_contract(self):
        spec=self.r.card(STEG).hand_progress
        for kwargs in(dict(goal=2),dict(repeat=False),dict(kind='infuse'),dict(amount_basis='event_amount')):
            with self.assertRaises(ValueError):replace(spec,**kwargs)
        with self.assertRaises(ValueError):self.r.validate_hand_progress(spec,CardType.SPELL)
    def test_serialized_pair_and_pending_progress_restore_without_scope_expansion(self):
        g=self.game((STEG,));saved=json.loads(json.dumps(g.snapshot()));self.assertIn('["hand", "deck"]',json.dumps(saved))
        self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),g.snapshot())
        def corrupt(value):
            if isinstance(value,dict):
                if value.get('zone')==['hand','deck']:value['zone']=['deck','hand'];return True
                return any(corrupt(x)for x in value.values())
            return isinstance(value,list)and any(corrupt(x)for x in value)
        self.assertTrue(corrupt(saved))
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_hidden_deck_growth_has_no_hand_progress_projection_or_identity_leak(self):
        g=self.game(deck=(STEG,PLAIN));g.apply(EndTurn(1));e=self.entity(g,STEG,zone='deck');self.assertIsNone(public_progress(e))
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            self.assertNotIn(STEG,text);self.assertNotIn('SetCapturedMinionStats',text);self.assertNotIn('progress_keys',text)
        self.assertFalse(any(x.kind=='hand_progressed'and x.target_id==e.id for x in g.events));self.portable(g)
    def test_owner_only_hand_progress_and_board_has_no_stored_progress_view(self):
        g=self.game((STEG,),board=(STEG,));g.apply(EndTurn(1));hand=self.entity(g,STEG,zone='hand');board=self.entity(g,STEG)
        self.assertEqual(public_progress(hand)['completions'],1);self.assertIsNone(public_progress(board))
        own=g.for_player(1).observe()['observation'];other=g.for_player(2).observe()['observation']
        player=lambda obs,p:next(x for x in obs['players']if x['id']==p)
        self.assertIn('hand_progress',player(own,1)['hand'][0]);self.assertNotIn('hand_progress',json.dumps(player(other,1)['hand']))


if __name__=='__main__':unittest.main()
