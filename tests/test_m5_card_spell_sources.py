"""R-135: source composition and explicitly bounded, independently audited pools."""
import json
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import test_m5_combo_sources as foundation
from hs_sim.targets import canonical_digest,load_baseline,TargetValidationError
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Scenario,PlayerSetup,
    GenerationContext,Keyword,Ruleset,SpellRepeatSpec,SnapshotError,EndTurn,PlayCard,
    CounterMinion,Zone,ResolutionError,AddSpellRepeatModifier,DeckSpec,DeckPolicy,validate_deck)
from hs_sim.engine.effects import (Damage,GainArmor,AddToHand,CopyMinion,Destroy,ReplaceHero,
    Summon,ModifyCost,DamageBatch,Silence,RequestChoice,ChoiceOption)
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.engine.card_spell_sources import POOL_ID,INVENTORY_HASH
from hs_sim.engine.class_tags import classes_from_tags
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import PoolCard,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.representative import build_registry,metadata_from_record,CARD_LIMITATIONS
from hs_sim.engine.spell_casts import CastStoredSpell

ROOT=Path(__file__).resolve().parents[1]
CONTEXT=GenerationContext('local-2026-09-23','experimental')
QUERY=PoolQuery(kinds=(CardType.SPELL,),min_cost=5,collectible=True,class_mode='current')


class CardSpellSourceTests(unittest.TestCase):
    script=foundation.ComboSourceTests.script
    watch=foundation.ComboSourceTests.watch
    play=foundation.ComboSourceTests.play
    choose=foundation.ComboSourceTests.choose
    cycle=foundation.ComboSourceTests.cycle
    board=foundation.ComboSourceTests.board
    check=foundation.ComboSourceTests.check
    def setUp(self):self.r=build_registry()
    def game(self,hand=('JAIL_123',),board=(),enemy=(),hero='HERO_08',context=CONTEXT,rules=None):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('CS2_182',)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_01',board=enemy,deck=('CS2_182',)*8)),seed=94,generation_context=context),self.r,rules)
    def discover(self,g,cid='EX1_279'):
        self.play(g,'JAIL_123');self.choose(g,cid);return self.hand(g,cid)[-1]
    def hand(self,g,cid=None,p=1):return [g.state.entities[i] for i in g.state.players[p].hand if cid is None or g.state.entities[i].card_id==cid]
    def repeat(self,e):return [a for a in e.abilities if a.kind=='card_spell_repeat']
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def pool(self,**kw):
        key=(POOL_ID,CONTEXT.target_id,CONTEXT.mode);self.r._pools[key]=replace(self.r.pools[key],**kw)
    def minion(self,cid,**kw):self.r.register_card(CardDefinition(cid,cid,CardType.MINION,**kw))
    def inventory(self):return json.loads((ROOT/'data/support/card-spell-source-inventory.json').read_text(encoding='utf-8'))

    def test_class_mask_precedes_primary_even_neutral_or_absent(self):
        for primary in (12,4,None):
            tags={'MULTIPLE_CLASSES':130}
            if primary is not None:tags['CLASS']=primary
            self.assertEqual(classes_from_tags(tags),(CardClass.DRUID,CardClass.SHAMAN))
        self.assertEqual(classes_from_tags({'MULTIPLE_CLASSES':520}),(CardClass.MAGE,CardClass.WARRIOR))
        self.assertEqual(classes_from_tags({'MULTIPLE_CLASSES':8193}),(CardClass.DEATH_KNIGHT,CardClass.DEMON_HUNTER))

    def test_zero_mask_falls_back_to_primary_and_preserves_input(self):
        tags={'CLASS':4,'MULTIPLE_CLASSES':0};before=dict(tags)
        self.assertEqual(classes_from_tags(tags),(CardClass.MAGE,));self.assertEqual(tags,before)
        self.assertEqual(classes_from_tags({'CLASS':12}),(CardClass.NEUTRAL,))

    def test_unknown_class_bits_types_and_mixed_neutral_rejected(self):
        for tags in ({},{'CLASS':0},{'CLASS':11},{'CLASS':13},{'CLASS':True},{'CLASS':4.0},
            {'MULTIPLE_CLASSES':True},{'MULTIPLE_CLASSES':-1},{'MULTIPLE_CLASSES':2**32},
            {'MULTIPLE_CLASSES':1<<10},{'MULTIPLE_CLASSES':1<<12},{'MULTIPLE_CLASSES':(1<<11)|8}):
            with self.subTest(tags=tags),self.assertRaises(TargetValidationError):classes_from_tags(tags)

    def test_gidra_corrected_to_two_classes_and_not_neutral(self):
        self.assertEqual(self.r.card('SCH_182').metadata.classes,(CardClass.DRUID,CardClass.SHAMAN))
        self.assertEqual(self.r.card('SC_999t').metadata.classes,(CardClass.PALADIN,CardClass.SHAMAN,CardClass.WARRIOR))

    def test_corrected_gidra_rejected_by_mage_construction(self):
        policy=DeckPolicy('test','test','experimental',('SCH_182',),deck_size=1)
        mage=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,('SCH_182',))
        druid=DeckSpec('HERO_06','HERO_06bp',CardClass.DRUID,('SCH_182',))
        self.assertIn('class',[i.code for i in validate_deck(mage,self.r,policy).issues])
        self.assertTrue(validate_deck(druid,self.r,policy).valid)

    def test_all_broad_raw_candidates_preserved_with_class_and_alias_audit(self):
        inv=self.inventory();self.assertEqual(canonical_digest(inv),INVENTORY_HASH)
        self.assertEqual(len(inv['raw_spells']),436);self.assertFalse(inv['complete']);self.assertFalse(inv['generation_rules_applied'])
        self.assertEqual(len(inv['raw_class_scopes']['mage']),67)
        self.assertIn('END_023',inv['raw_class_scopes']['mage'])
        self.assertIn('END_005',inv['raw_class_scopes']['demon_hunter'])
        self.assertEqual(len(inv['name_groups_for_review']),56)
        self.assertTrue(all(not g['identity_merged'] for g in inv['name_groups_for_review']))
        self.assertTrue(any(e['data']['id'] not in self.r.cards for e in inv['raw_spells']))
        for entry in inv['raw_spells']:
            self.assertEqual(entry['data_sha256'],canonical_digest(entry['data']))
            self.assertEqual(entry['classes'],[c.value for c in classes_from_tags(entry['data']['tags'])])

    def test_pool_is_explicit_six_member_scope_and_four_new_records_only(self):
        inv=self.inventory();self.assertEqual(len(inv['experimental_pool']['members']),6);self.assertFalse(inv['experimental_pool']['complete'])
        for cid in ('JAIL_123','CS2_028','CS2_032','EX1_279'):self.assertIn('R-135',CARD_LIMITATIONS[cid])
        self.assertEqual((self.r.card('JAIL_123').cost,self.r.card('JAIL_123').attack,self.r.card('JAIL_123').health),(5,4,5))
        self.assertEqual(self.r.version,'representative-m5-v64')

    def test_pool_current_class_type_and_cost_controls(self):
        def candidates(cls):return [m.card_id for m in resolve_candidates(self.r,CONTEXT,POOL_ID,QUERY,current_class=cls)]
        self.assertEqual(candidates(CardClass.MAGE),['CS2_028','CS2_032','EX1_279'])
        self.assertEqual(candidates(CardClass.DRUID),['EX1_164']);self.assertEqual(candidates(CardClass.WARRIOR),[])
        self.assertNotIn('CS2_029',candidates(CardClass.MAGE));self.assertNotIn('JAIL_123',candidates(CardClass.MAGE))

    def test_changed_inventory_rejected_before_registry_construction(self):
        original=Path.read_text
        def corrupt(path,*args,**kw):
            text=original(path,*args,**kw)
            return text.replace('representative-architect-spells-v1','changed') if path.name=='card-spell-source-inventory.json' else text
        with patch.object(Path,'read_text',corrupt),self.assertRaisesRegex(TargetValidationError,'Card spell source inventory'):build_registry()

    def test_unimplemented_eligible_candidate_is_not_filtered_before_rng(self):
        raw=next(e['data'] for e in self.inventory()['raw_spells'] if e['data']['id']=='AT_001')
        self.r.register_pool_card(PoolCard(raw['id'],CardType.SPELL,raw['cost'],metadata_from_record(raw),battlecry=False))
        key=(POOL_ID,CONTEXT.target_id,CONTEXT.mode);self.pool(members=(*self.r.pools[key].members,PoolMember(raw['id'])))
        g=self.game();before=g.snapshot()
        with patch('hs_sim.engine.discovery.sample_candidates',side_effect=AssertionError('RNG too soon')):
            with self.assertRaisesRegex(ResolutionError,'AT_001'):self.play(g,'JAIL_123')
        self.assertEqual(g.snapshot(),before)

    def test_formal_context_or_absent_context_never_falls_back(self):
        for context in (None,GenerationContext(CONTEXT.target_id,'standard'),GenerationContext(CONTEXT.target_id,'wild')):
            g=self.game(context=context);before=g.snapshot()
            with self.assertRaises(ValueError):self.play(g,'JAIL_123')
            self.assertEqual(g.snapshot(),before)

    def test_battlecry_choice_does_not_preallocate_card_or_player_policy(self):
        g=self.game();self.play(g,'JAIL_123')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'CS2_028','CS2_032','EX1_279'})
        self.assertFalse(self.hand(g));self.assertFalse(g.state.players[1].spell_modifiers);self.check(g)

    def test_summoning_source_does_not_execute_battlecry(self):
        self.script('summon',lambda c:[Summon(1,'JAIL_123')]);g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.hand(g));self.check(g)

    def test_minion_counter_prevents_discovery(self):
        self.watch('counter','minion_counter_check',lambda c:[CounterMinion(dict(c.event.data)['window_id'])])
        g=self.game(enemy=('counter',));self.play(g,'JAIL_123');self.assertTrue(g.state.play_history[-1].countered)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.hand(g));self.check(g)

    def test_existing_identical_spell_remains_unmodified(self):
        g=self.game(hand=('JAIL_123','EX1_279'));new=self.discover(g)
        old=self.hand(g,'EX1_279')[0];self.assertNotEqual(old.id,new.id);self.assertFalse(self.repeat(old))
        self.cycle(g);self.play(g,'EX1_279',self.hero(g).id);self.assertEqual(self.hero(g).health,20)
        self.cycle(g);self.play(g,'EX1_279',self.hero(g).id);self.assertEqual(g.state.winner,1)
        self.assertEqual(len(g.state.cast_history),3);self.check(g)

    def test_other_spell_does_not_consume_discovered_property(self):
        g=self.game(hand=('JAIL_123','CS2_029'));new=self.discover(g)
        self.play(g,'CS2_029',self.hero(g).id);self.assertEqual(self.hero(g).health,24)
        self.cycle(g);self.play(g,'EX1_279',self.hero(g).id);self.assertEqual(self.hero(g).health,4)
        self.assertEqual(len(g.state.play_history[-1].card_spell_repeats),1);self.check(g)

    def test_one_payment_for_two_pyroblasts_and_same_chosen_target(self):
        g=self.game();self.discover(g);self.cycle(g);target=self.hero(g).id;self.play(g,'EX1_279',target)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(10,0))
        casts=g.state.cast_history;self.assertEqual(len(casts),2);self.assertEqual({c.target_id for c in casts},{target});self.check(g)

    def test_lethal_first_iteration_interrupts_second(self):
        self.script('hurt',lambda c:[Damage(c.state.players[2].hero_id,25)])
        g=self.game(hand=('hurt','JAIL_123'));self.play(g,'hurt');self.discover(g);self.cycle(g);self.play(g,'EX1_279',self.hero(g).id)
        self.assertEqual(g.state.winner,1);self.assertEqual(sum(c.card_id=='EX1_279' for c in g.state.cast_history),1);self.check(g)

    def test_blizzard_batch_freezes_enemies_not_friends_and_uses_spell_damage(self):
        self.minion('tough',attack=2,health=10)
        g=self.game(board=('EX1_012','tough'),enemy=('tough','tough'));self.discover(g,'CS2_028');self.cycle(g)
        self.play(g,'CS2_028');self.assertEqual([e.health for e in self.board(g,2)],[4,4])
        self.assertTrue(all(e.frozen for e in self.board(g,2)));self.assertTrue(all(not e.frozen for e in self.board(g)))
        self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_blizzard_divine_shield_absorbs_one_batch_but_does_not_prevent_freeze(self):
        self.minion('shield',attack=1,health=8,keywords=(Keyword.DIVINE_SHIELD,))
        g=self.game(enemy=('shield',));self.discover(g,'CS2_028');self.cycle(g);self.play(g,'CS2_028')
        e=self.board(g,2)[0];self.assertEqual(e.health,6);self.assertTrue(e.frozen);self.assertNotIn(Keyword.DIVINE_SHIELD,e.keywords);self.check(g)

    def test_flamestrike_repetitions_keep_existing_deferred_death_contract(self):
        self.minion('tough',attack=1,health=8)
        g=self.game(enemy=('FP1_007','tough'));self.discover(g,'CS2_032');self.cycle(g);self.play(g,'CS2_032')
        self.assertEqual([(e.card_id,e.health) for e in self.board(g,2)],[('FP1_007t',4)])
        self.assertEqual(len(g.state.death_history),2);self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_untargeted_spell_casts_on_empty_board(self):
        g=self.game();self.discover(g,'CS2_032');self.cycle(g);self.play(g,'CS2_032')
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_board_aura_and_local_attachment_take_max_not_product(self):
        self.minion('repeat',health=4,spell_repeats=(SpellRepeatSpec(3,'any'),))
        g=self.game(board=('repeat',));self.discover(g);self.cycle(g);self.play(g,'EX1_279',self.hero(g).id)
        self.assertEqual(len(g.state.cast_history),3);self.assertEqual(g.state.winner,1);self.check(g)

    def test_player_budget_is_consumed_once_even_with_local_attachment(self):
        self.script('policy',lambda c:[AddSpellRepeatModifier(1,SpellRepeatSpec(2,'any'),uses=1)])
        g=self.game(hand=('policy','JAIL_123'));self.play(g,'policy');self.discover(g);self.cycle(g);self.play(g,'EX1_279',self.hero(g).id)
        self.assertFalse(g.state.players[1].spell_modifiers);self.assertEqual(len(g.state.spell_policy_receipts),1);self.assertEqual(self.hero(g).health,10);self.check(g)

    def test_brann_creates_two_independent_discoveries_and_attachments(self):
        g=self.game(board=('LOE_077',));self.play(g,'JAIL_123');self.choose(g,'CS2_032');self.check(g)
        self.choose(g,'CS2_032');cards=self.hand(g,'CS2_032')
        self.assertEqual(len(cards),2);self.assertEqual(len({self.repeat(e)[0].id for e in cards}),2)
        self.assertEqual([self.repeat(e)[0].spell_repeat.casts for e in cards],[2,2]);self.check(g)

    def test_changed_hero_class_uses_current_class_and_nourish_branch(self):
        self.script('druid',lambda c:[ReplaceHero(1,'HERO_06')]);g=self.game(hand=('druid','JAIL_123'))
        self.play(g,'druid');self.discover(g,'EX1_164');self.cycle(g)
        card=self.hand(g,'EX1_164')[0];g.apply(PlayCard(1,card.id,branch_id='draw'))
        self.assertEqual(sum(c.card_id=='EX1_164' for c in g.state.cast_history),2);self.assertEqual(len(g.state.players[1].deck),1);self.check(g)

    def test_source_dies_after_choice_without_revoking_attachment(self):
        self.script('remove',lambda c:[Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='JAIL_123'))])
        g=self.game(hand=('JAIL_123','remove'));created=self.discover(g);self.play(g,'remove')
        self.assertEqual(g.state.entities[self.repeat(created)[0].source_id].zone,Zone.GRAVEYARD)
        self.cycle(g);self.play(g,'EX1_279',self.hero(g).id);self.assertEqual(self.hero(g).health,10);self.check(g)

    def test_source_death_during_selection_does_not_lose_frozen_delivery(self):
        self.watch('kill','choice_selected',lambda c:[Destroy(c.event.source_id)])
        g=self.game(board=('kill',));created=self.discover(g)
        self.assertEqual(g.state.entities[self.repeat(created)[0].source_id].zone,Zone.GRAVEYARD);self.check(g)

    def test_full_hand_burns_new_modified_card_without_upgrading_old_copy(self):
        self.watch('fill','choice_selected',lambda c:[AddToHand(1,'CS2_182')])
        g=self.game(hand=('JAIL_123','EX1_279')+('CS2_182',)*8,board=('fill',));self.play(g,'JAIL_123');self.choose(g,'EX1_279')
        self.assertFalse(self.repeat(self.hand(g,'EX1_279')[0]))
        burned=[e for e in g.state.entities.values() if e.card_id=='EX1_279' and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),1);self.assertEqual(len(self.repeat(burned[0])),1);self.check(g)

    def test_acquisition_reaction_copies_already_attached_card(self):
        self.watch('copy','card_added_to_hand',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.event.target_id]),1)]
            if c.state.entities[c.event.target_id].card_id=='EX1_279' and c.state.entities[c.event.target_id].origin_entity_id is None else [])
        g=self.game(board=('copy',));self.discover(g);cards=self.hand(g,'EX1_279')
        self.assertEqual(len(cards),2);self.assertEqual(len({self.repeat(e)[0].id for e in cards}),2);self.check(g)

    def test_countered_discovered_spell_does_not_cast_any_iteration(self):
        from hs_sim.engine.secrets import SetSecret
        self.script('arm',lambda c:[SetSecret(2,'EX1_287')]);g=self.game(hand=('arm','JAIL_123'));self.play(g,'arm')
        self.discover(g);self.cycle(g);self.play(g,'EX1_279',self.hero(g).id)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_failed_acquisition_restores_same_choice_and_random_state(self):
        self.watch('bad','card_added_to_hand',lambda c:[GainArmor(1,-1)])
        g=self.game(board=('bad',));self.play(g,'JAIL_123');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'EX1_279')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_automatic_stored_spell_does_not_use_hand_play_property(self):
        self.script('auto',lambda c:[CastStoredSpell(CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='EX1_279')),
            1,c.source_id,targeting='random')])
        g=self.game(hand=('JAIL_123','auto'));self.discover(g);self.play(g,'auto')
        self.assertEqual(sum(c.card_id=='EX1_279' for c in g.state.cast_history),1);self.check(g)

    def test_saved_discovery_restores_with_fresh_registry_and_same_delivery(self):
        g=self.game();self.play(g,'JAIL_123');restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),build_registry())
        for match in (g,restored):self.choose(match,'EX1_279');self.cycle(match);self.play(match,'EX1_279',self.hero(match).id)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_hidden_pool_and_attachment_id_never_enter_player_view(self):
        g=self.game();self.play(g,'JAIL_123');other=g.observe(2);self.assertEqual(other['pending_choice'],{'player_id':1})
        self.choose(g,'EX1_279');self.assertNotIn('card_spell_repeat',json.dumps(g.observe(2)))
        own=next(e for e in g.observe(1)['players'][0]['hand'] if e['card_id']=='EX1_279')
        self.assertEqual(own['card_spell_repeats'],[dict(casts=2,expires_turn=None)])
        self.assertNotIn('ability_id',json.dumps(own));self.assertNotIn('raw_spells',json.dumps(g.for_player(1).observe()));self.check(g)

    def test_source_silence_does_not_revoke_delivered_property(self):
        self.script('silence',lambda c:[Silence(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='JAIL_123'))])
        g=self.game(hand=('silence','JAIL_123'));self.discover(g);self.play(g,'silence');self.cycle(g)
        self.play(g,'EX1_279',self.hero(g).id);self.assertEqual(self.hero(g).health,10);self.check(g)

    def test_hero_change_between_brann_choices_keeps_old_pick_and_refreshes_new_scope(self):
        self.watch('change','choice_selected',lambda c:[ReplaceHero(1,'HERO_06')])
        g=self.game(board=('LOE_077','change'));self.play(g,'JAIL_123');self.choose(g,'EX1_279')
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['EX1_164']);self.check(g)
        self.choose(g,'EX1_164');self.assertTrue(all(self.repeat(e) for e in self.hand(g)));self.check(g)

    def test_physical_transfer_to_opponent_preserves_source_attachment(self):
        self.script('give',lambda c:[MoveCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='EX1_279')),2,Zone.HAND)])
        g=self.game(hand=('give','JAIL_123'));created=self.discover(g);self.play(g,'give')
        card=self.hand(g,'EX1_279',2)[0];self.assertEqual(card.id,created.id);self.assertEqual(self.repeat(card),self.repeat(created));self.check(g)

    def test_native_representative_example_restores_and_finishes(self):
        from examples.card_spell_sources import run
        g,s=run();self.assertEqual(g.state.winner,1);self.assertEqual(s['schema_version'],265)


if __name__=='__main__':unittest.main()
