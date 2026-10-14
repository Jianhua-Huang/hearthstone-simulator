"""R-133: physical spell attachments, immutable plays and source boundaries."""
import json
import unittest
from dataclasses import replace
import test_m5_spell_repeats as foundation
from hs_sim.engine import (GrantCardSpellRepeat as Grant, RemoveCardSpellRepeat as Remove,
    AddSpellRepeatModifier,SpellRepeatSpec,Game,EndTurn,CardType,CardDefinition,Zone,
    TriggerSpec,RewindSpec,Keyword,SnapshotError,ResolutionError,IllegalAction,
    Ruleset,ResolutionLimitExceeded,CastWhenDrawnSpec,UpgradeHandCard,AbilityInstance,HandDerivativeSpec,HandRepeatSpec)
from hs_sim.engine.effects import (GainArmor,Damage,Draw,Destroy,Silence,ChangeControl,
    RequestChoice,ChoiceOption,InvokeBehavior,AddToHand)
from hs_sim.engine.resolver import ExpireTurn
from hs_sim.engine.zones import CardReference,MoveCard,CopyCard,AddToDeck
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.effects import RevealHandCard


class CardSpellRepeatTests(unittest.TestCase):
    minion=foundation.SpellRepeatTests.minion
    spell=foundation.SpellRepeatTests.spell
    game=foundation.SpellRepeatTests.game
    play=foundation.SpellRepeatTests.play
    hero=foundation.SpellRepeatTests.hero
    choose=foundation.SpellRepeatTests.choose
    check=foundation.SpellRepeatTests.check

    def setUp(self):
        foundation.SpellRepeatTests.setUp(self)
        self.spell('armor',lambda c:[GainArmor(c.player_id,2)],cost=1)
        self.spell('other',lambda c:[GainArmor(c.player_id,1)])
        self.granter('grant')
        self.minion('retainer',health=4,retain_rewind_outcomes=True)
    def cry(self,cid,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,health=4,battlecry=cid)
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,health=4,triggers=(TriggerSpec(event,cid),))
    def ref(self,c,cid='armor',player=1,zone=Zone.HAND,index=0):
        cards=[c.state.entities[i] for i in getattr(c.state.players[player],zone.value) if c.state.entities[i].card_id==cid]
        return CardReference.capture(cards[index])
    def granter(self,name,cid='armor',zone=Zone.HAND,temporary=False,extra=(),**kw):
        self.cry(name,lambda c:[Grant(self.ref(c,cid,zone=zone),source_id=c.source_id,
            expires_turn=c.state.turn if temporary else None,**kw),*extra])
    def ready(self,grant='grant',hand=('armor',),board=(),**kw):
        g=self.game(hand=(grant,*hand),board=board,**kw);self.play(g,grant);return g
    def armor(self,g,p=1):return self.hero(g,p).armor
    def entity(self,g,cid='armor',player=1,zone=Zone.HAND,index=0):
        return [g.state.entities[i] for i in getattr(g.state.players[player],zone.value) if g.state.entities[i].card_id==cid][index]
    def attached(self,e):return [a for a in e.abilities if a.kind=='card_spell_repeat']
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_only_selected_copy_repeats_and_pays_once(self):
        g=self.ready(hand=('armor','armor'));first=self.entity(g).id
        self.play(g,'armor');self.assertEqual((self.armor(g),g.state.players[1].mana),(4,9))
        p=g.state.play_history[-1];self.assertEqual((p.source_id,len(p.card_spell_repeats)),(first,1))
        self.play(g,'armor');self.assertEqual(self.armor(g),6);self.assertFalse(g.state.play_history[-1].card_spell_repeats)
        self.assertEqual((len(g.state.cast_history),len(g.state.spell_policy_receipts)),(3,0));self.check(g)

    def test_other_spell_first_does_not_take_attachment(self):
        g=self.ready(hand=('other','armor'));self.play(g,'other');self.assertEqual(self.armor(g),1)
        self.play(g,'armor');self.assertEqual(self.armor(g),5);self.check(g)

    def test_two_grants_use_max_with_independent_identities(self):
        self.granter('triple',casts=3);g=self.ready(hand=('triple','armor'));self.play(g,'triple')
        self.assertEqual([a.spell_repeat.casts for a in self.attached(self.entity(g))],[2,3])
        self.play(g,'armor');self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.play_history[-1].card_spell_repeats),2);self.check(g)

    def test_player_budget_merges_by_max_and_still_consumes(self):
        self.cry('policy',lambda c:[AddSpellRepeatModifier(1,SpellRepeatSpec(3,'any'),uses=1)])
        g=self.ready(hand=('policy','armor'));self.play(g,'policy');self.play(g,'armor')
        self.assertEqual(self.armor(g),6);self.assertFalse(g.state.players[1].spell_modifiers);self.check(g)

    def test_board_aura_merges_by_max(self):
        self.minion('triple',health=4,spell_repeats=(SpellRepeatSpec(3,'any'),))
        g=self.ready(board=('triple',));self.play(g,'armor');self.assertEqual(self.armor(g),6);self.check(g)

    def test_board_aura_keeps_later_window(self):
        self.minion('triple',health=4,spell_repeats=(SpellRepeatSpec(3,'any'),))
        self.watch('watch','card_committed',lambda c:[Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='triple'))]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready(board=('triple','watch'));self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_expiry_after_commit_does_not_change_frozen_repeat(self):
        self.granter('temp',temporary=True)
        self.watch('watch','card_committed',lambda c:[ExpireTurn(c.state.turn)] if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready('temp',board=('watch',));i=self.entity(g).id;self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertFalse(self.attached(g.state.entities[i]));self.check(g)

    def test_attachment_added_to_other_copy_in_commit_does_not_change_current(self):
        self.watch('watch','card_committed',lambda c:[Grant(self.ref(c))] if c.state.entities[c.event.source_id].kind==CardType.SPELL and c.state.players[1].hand else [])
        g=self.game(hand=('armor','armor'),board=('watch',));self.play(g,'armor');self.assertEqual(self.armor(g),2)
        self.play(g,'armor');self.assertEqual(self.armor(g),6);self.check(g)

    def test_unspent_attachment_survives_turns(self):
        g=self.ready();self.cycle(g);self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_turn_deadline_removes_attachment(self):
        self.granter('temp',temporary=True);g=self.ready('temp');self.cycle(g)
        self.assertFalse(self.attached(self.entity(g)));self.play(g,'armor');self.assertEqual(self.armor(g),2);self.check(g)

    def test_expiry_also_cleans_hidden_deck_attachment(self):
        self.cry('store',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top')])
        self.granter('temp',temporary=True);g=self.ready('temp',hand=('store','armor'));self.play(g,'store');self.cycle(g)
        self.assertFalse(self.attached(self.entity(g)));self.play(g,'armor');self.assertEqual(self.armor(g),2);self.check(g)

    def test_source_silence_does_not_revoke_card_attachment(self):
        self.cry('silence_source',lambda c:[Silence(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='grant'))])
        g=self.ready(hand=('silence_source','armor'));self.play(g,'silence_source');self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_source_death_and_control_change_do_not_revoke(self):
        self.cry('transfer',lambda c:[ChangeControl(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='grant'),2)])
        self.cry('kill_source',lambda c:[Destroy(next(i for i in c.state.players[2].board if c.state.entities[i].card_id=='grant'))])
        g=self.ready(hand=('transfer','kill_source','armor'));self.play(g,'transfer');self.play(g,'kill_source');self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_move_to_deck_and_draw_preserves_physical_attachment(self):
        self.cry('cycle',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),Draw(1)])
        g=self.ready(hand=('cycle','armor'));old=self.entity(g);self.play(g,'cycle')
        self.assertEqual(self.entity(g).id,old.id);self.assertEqual(self.attached(self.entity(g)),self.attached(old))
        self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_explicit_reset_move_removes_attachment(self):
        self.cry('reset',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top',reset=True),Draw(1)])
        g=self.ready(hand=('reset','armor'));self.play(g,'reset');self.play(g,'armor');self.assertEqual(self.armor(g),2);self.check(g)

    def test_hand_transfer_retains_attachment_for_new_controller(self):
        self.cry('transfer',lambda c:[MoveCard(self.ref(c),2,Zone.HAND)])
        g=self.ready(hand=('transfer','armor'));self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'armor')
        self.assertEqual(self.armor(g,2),4);self.assertTrue(g.state.play_history[-1].card_spell_repeats);self.check(g)

    def test_current_copy_inherits_and_base_copy_is_fresh(self):
        self.cry('copy_cards',lambda c:[CopyCard(self.ref(c),1,mode='current'),CopyCard(self.ref(c),1,mode='base')])
        g=self.ready(hand=('copy_cards','armor'));self.play(g,'copy_cards')
        cards=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([len(self.attached(e)) for e in cards],[1,1,0]);self.assertNotEqual(self.attached(cards[0])[0].id,self.attached(cards[1])[0].id)
        for _ in range(3):self.play(g,'armor')
        self.assertEqual(self.armor(g),10);self.check(g)

    def test_explicit_removal_affects_only_one_contributor(self):
        self.granter('triple',casts=3)
        self.cry('remove',lambda c:[Remove(self.ref(c),self.attached(c.state.entities[self.ref(c).entity_id])[-1].id,c.source_id)])
        g=self.ready(hand=('triple','remove','armor'));self.play(g,'triple');self.play(g,'remove');self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_removal_of_absent_or_other_kind_id_is_noop(self):
        self.cry('remove',lambda c:[Remove(self.ref(c),c.state.entities[self.ref(c).entity_id].abilities[0].id),Remove(self.ref(c),9999)])
        g=self.ready(hand=('remove','armor'));self.play(g,'remove');self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_hand_form_upgrade_keeps_dynamic_attachment(self):
        self.cry('upgrade',lambda c:[UpgradeHandCard(self.ref(c),'other')])
        g=self.ready(hand=('upgrade','armor'));self.play(g,'upgrade');self.play(g,'other');self.assertEqual(self.armor(g),2);self.check(g)

    def test_grant_in_deck_before_draw(self):
        self.cry('deck_grant',lambda c:[AddToDeck(1,'armor',position='top'),InvokeBehavior('grant_deck',c.source_id,1),Draw(1)])
        self.r.register_behavior('grant_deck',lambda c:[Grant(self.ref(c,zone=Zone.DECK))])
        g=self.game(hand=('deck_grant',),board=());self.play(g,'deck_grant');self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_stale_reference_after_roundtrip_does_not_regrant(self):
        self.cry('stale',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),Draw(1),Grant(self.ref(c),casts=3)])
        g=self.ready(hand=('stale','armor'));self.play(g,'stale');self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_stale_reference_after_form_change_does_not_grant(self):
        self.cry('stale',lambda c:[UpgradeHandCard(self.ref(c),'other'),Grant(self.ref(c),casts=3)])
        g=self.game(hand=('stale','armor'),board=());self.play(g,'stale');self.play(g,'other');self.assertEqual(self.armor(g),1);self.check(g)

    def test_nonspell_target_rejects_and_rolls_back(self):
        self.granter('bad','plain');g=self.game(hand=('bad','plain'),board=());before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'stored spell'):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_source_or_past_expiry_rolls_back(self):
        self.cry('bad_source',lambda c:[Grant(self.ref(c),source_id=99999)])
        self.cry('bad_expiry',lambda c:[Grant(self.ref(c),expires_turn=1)])
        g=self.game(hand=('bad_source','bad_expiry','armor'),board=());self.cycle(g)
        for cid in ('bad_source','bad_expiry'):
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),before)

    def test_invalid_cast_count_and_carrier_spec_rejected(self):
        ref=CardReference(1,1,Zone.HAND,'armor',0)
        for value in (True,0,1,2.5):
            with self.subTest(value=value),self.assertRaises(ValueError):Grant(ref,value)
        for kw in (dict(spell_repeat=SpellRepeatSpec()),dict(origin='printed'),dict(consumed=True),dict(remove_on_silence=False),dict(magnetic_id=1)):
            values=dict(spell_repeat=SpellRepeatSpec(2,'any'));values.update(kw)
            with self.subTest(kw=kw),self.assertRaises(ValueError):AbilityInstance(1,'card_spell_repeat',**values)

    def test_generated_cast_with_same_identity_does_not_inherit(self):
        self.cry('auto',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.ready(hand=('auto','armor'));self.play(g,'auto');self.assertEqual(self.armor(g),2)
        self.play(g,'armor');self.assertEqual(self.armor(g),6);self.check(g)

    def test_automatic_cast_of_annotated_physical_card_does_not_repeat(self):
        self.cry('auto',lambda c:[CastStoredSpell(self.ref(c),1,c.source_id)])
        g=self.ready(hand=('auto','armor'));i=self.entity(g).id;self.play(g,'auto')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.cast_history),1)
        self.assertTrue(self.attached(g.state.entities[i]));self.assertFalse(g.state.spell_repeats);self.check(g)

    def test_draw_cast_of_annotated_deck_card_does_not_repeat(self):
        self.spell('drawn',lambda c:[GainArmor(1,2)],keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        self.r.register_behavior('grant_deck',lambda c:[Grant(self.ref(c,'drawn',zone=Zone.DECK))])
        self.cry('draw',lambda c:[AddToDeck(1,'drawn',position='top'),InvokeBehavior('grant_deck',c.source_id,1),Draw(1)])
        g=self.game(hand=('draw',),board=());self.play(g,'draw');self.assertEqual(self.armor(g),2)
        self.assertFalse(g.state.spell_repeats);self.check(g)

    def test_history_recast_uses_base_payload_without_attachment(self):
        self.cry('recast',lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.ready(hand=('armor','recast'));self.play(g,'armor');self.play(g,'recast')
        self.assertEqual(self.armor(g),6);self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat','history']);self.check(g)

    def test_countered_play_retains_capture_but_starts_no_repeat(self):
        self.cry('arm',lambda c:[SetSecret(2,'EX1_287')]);g=self.ready(hand=('arm','armor'));self.play(g,'arm');self.play(g,'armor')
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[-1].card_spell_repeats)
        self.assertFalse(g.state.spell_repeats);self.check(g)

    def test_lethal_first_iteration_interrupts_captured_second(self):
        self.spell('fatal',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id)]);self.granter('fatal_grant','fatal')
        g=self.ready('fatal_grant',hand=('fatal',));self.play(g,'fatal')
        self.assertEqual(g.state.winner,1);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.spell_repeats[-1].casts,2);self.assertTrue(g.state.spell_repeats[-1].interrupted);self.check(g)

    def test_terminal_commit_retains_capture_without_payload(self):
        self.watch('watch','card_committed',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id)]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready(board=('watch',));self.play(g,'armor');self.assertTrue(g.state.play_history[-1].card_spell_repeats)
        self.assertFalse(g.state.spell_repeats);self.assertFalse(g.state.cast_history);self.check(g)

    def test_failed_payload_rolls_back_payment_capture_and_all_iterations(self):
        self.spell('bad',lambda c:[GainArmor(1,2),AddToHand(1,'missing')]);self.granter('bad_grant','bad')
        g=self.ready('bad_grant',hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_repeated_choice_pause_restores_each_iteration_once(self):
        self.spell('pause',lambda c:[self.pause(c),GainArmor(1,2)]);self.granter('pause_grant','pause')
        g=self.ready('pause_grant',hand=('pause',));self.play(g,'pause');self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):self.choose(match,'ok');self.choose(match,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),4);self.check(g)

    def test_commit_pause_restores_frozen_capture_before_repeat_plan(self):
        self.watch('watch','card_committed',lambda c:[self.pause(c)] if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready(board=('watch',));self.play(g,'armor');self.assertFalse(g.state.spell_repeats);self.check(g)
        self.choose(g,'ok');self.assertEqual(self.armor(g),4);self.check(g)

    def test_failed_choice_preserves_original_pending_state(self):
        self.spell('pause',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',(
            Grant(self.ref(c),source_id=99999),)),),source_id=c.source_id)])
        self.granter('pause_grant','pause');g=self.ready('pause_grant',hand=('pause','armor'));self.play(g,'pause');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'ok')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_ordinary_rewind_restores_attachment_and_recaptures_once(self):
        self.spell('rewind',lambda c:[GainArmor(1,2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1));self.granter('rewind_grant','rewind')
        g=self.ready('rewind_grant',hand=('rewind',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(len(g.state.play_history[-1].card_spell_repeats),1);self.check(g)

    def test_retained_rewind_outcomes_share_physical_repeat_plan(self):
        self.spell('rewind',lambda c:[GainArmor(1,2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1));self.granter('rewind_grant','rewind')
        g=self.ready('rewind_grant',hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual(self.armor(g),8);self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_excessive_count_rolls_back_instead_of_becoming_game_result(self):
        self.granter('huge',casts=100000);g=self.ready('huge');before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'armor')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.status,'playing')

    def test_own_hand_projects_only_count_and_expiry(self):
        g=self.ready();view=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']=='armor')
        self.assertEqual(view['card_spell_repeats'],[dict(casts=2,expires_turn=None)])
        self.assertNotIn('ability_id',json.dumps(view));self.check(g)

    def test_opponent_observation_and_revision_ignore_private_grant(self):
        g=self.game(hand=('grant','armor'),board=());before=g.for_player(2).observe()
        # The public granter play is observable; only the private modifier event
        # must disappear from opponent logs and hidden hand attributes.
        self.play(g,'grant');view=g.for_player(2).observe()
        self.assertNotEqual(before['revision'],view['revision'])
        self.assertNotIn('card_spell_repeat',json.dumps(view))
        self.assertFalse(any(e['kind'].startswith('card_spell_repeat') for e in g.player_events(2)));self.check(g)

    def test_revealed_enemy_identity_does_not_expose_later_attachment(self):
        self.cry('reveal',lambda c:[RevealHandCard(self.ref(c).entity_id,(1,2))])
        g=self.game(hand=('reveal','grant','armor'),board=());self.play(g,'reveal');self.play(g,'grant')
        card=next(c for c in g.observe(2)['players'][0]['hand'] if c.get('card_id')=='armor')
        self.assertEqual(set(card),{'ref','card_id'});self.check(g)

    def test_hidden_deck_attachment_creates_no_tracking_handle(self):
        self.cry('store',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),InvokeBehavior('deck_grant',c.source_id,1)])
        self.r.register_behavior('deck_grant',lambda c:[Grant(self.ref(c,zone=Zone.DECK))])
        g=self.game(hand=('store','armor'),board=());self.play(g,'store')
        for p in (1,2):self.assertNotIn('card_spell_repeat',json.dumps(g.observe(p)))
        self.check(g)

    def test_hidden_grant_does_not_change_opponent_revision_in_paired_states(self):
        self.cry('conditional_grant',lambda c:[Grant(self.ref(c))] if any(
            c.state.entities[i].card_id=='armor' for i in c.state.players[1].hand) else [])
        a=self.game(hand=('conditional_grant','armor'),board=())
        b=self.game(hand=('conditional_grant','other'),board=())
        for g in (a,b):self.play(g,'conditional_grant');self.check(g)
        self.assertEqual(a.for_player(2).observe(),b.for_player(2).observe())
        self.assertEqual(a.player_events(2),b.player_events(2))

    def test_snapshot_rejects_live_invalid_carrier_or_consumption(self):
        g=self.ready()
        for changes in ({'consumed':True},{'origin':'printed'},{'source_id':99999}):
            s=g.snapshot();a=next(a for a in s['state']['entities'][str(self.entity(g).id)]['abilities'] if a['kind']=='card_spell_repeat')
            a.update(changes);self.reject(s)
        s=g.snapshot();source=s['state']['entities'][str(self.entity(g).id)];a=source['abilities'].pop()
        s['state']['entities'][str(g.state.players[1].board[0])]['abilities'].append(a);self.reject(s)

    def test_snapshot_rejects_capture_ids_or_content_differing_from_live(self):
        g=self.ready();self.play(g,'armor')
        for change in ({'id':99999},{'source_id':99999},{'expires_turn':True}):
            s=g.snapshot();s['state']['play_history'][-1]['card_spell_repeats'][0].update(change);self.reject(s)
        s=g.snapshot();s['state']['play_history'][-1]['card_spell_repeats'][0]['spell_repeat']['casts']=3;self.reject(s)

    def test_snapshot_rejects_duplicate_capture_and_wrong_kind(self):
        g=self.ready();self.play(g,'armor');s=g.snapshot();rows=s['state']['play_history'][-1]['card_spell_repeats'];rows.append(rows[0].copy());self.reject(s)
        s=g.snapshot();s['state']['play_history'][-1]['card_spell_repeats'][0]['kind']='spell_repeat';self.reject(s)

    def test_snapshot_rejects_repeat_plan_smaller_than_capture(self):
        self.granter('triple',casts=3);g=self.ready('triple');self.play(g,'armor');s=g.snapshot()
        s['state']['spell_repeats'][0].update(casts=2,completed=2);self.reject(s)

    def test_snapshot_rejects_private_event_leak_and_invalid_amount(self):
        g=self.ready()
        for amount,player in ((1,1),(2,2)):
            s=g.snapshot();events=s['information']['players']['1']['events']
            event=next(e for e in events if e['kind']=='card_spell_repeat_added');event.update(amount=amount,player_id=player);self.reject(s)

    def test_old_snapshot_schema_is_rejected(self):
        g=self.ready();s=g.snapshot();self.assertEqual(s['schema_version'],265);s['schema_version']=86;self.reject(s)

    def test_twinspell_derivatives_do_not_inherit_source_attachment(self):
        self.spell('terminal',lambda c:[GainArmor(1,1)])
        self.spell('twin',lambda c:[GainArmor(1,2)],keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'terminal'),))
        self.granter('twin_grant','twin');g=self.ready('twin_grant',hand=('twin',));self.play(g,'twin')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.players[1].hand),2)
        self.assertTrue(all(not self.attached(g.state.entities[i]) for i in g.state.players[1].hand))
        self.play(g,'terminal');self.assertEqual(self.armor(g),5);self.check(g)

    def test_echo_copy_does_not_inherit_source_attachment(self):
        self.spell('echo',lambda c:[GainArmor(1,1)],keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec(echo=True))
        self.granter('echo_grant','echo');g=self.ready('echo_grant',hand=('echo',));self.play(g,'echo')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertFalse(self.attached(self.entity(g,'echo')));self.play(g,'echo');self.assertEqual(self.armor(g),3);self.check(g)

    def test_synthetic_terminal_example_restores_with_fresh_registry(self):
        from examples.card_spell_repeats import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual((len(g.history),len(g.state.cast_history),len(g.state.spell_repeats)),(11,6,2))
        self.assertEqual(g.state.winner,1)


if __name__=='__main__':unittest.main()
