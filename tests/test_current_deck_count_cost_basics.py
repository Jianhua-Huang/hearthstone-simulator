"""Current DECK conditional prices over the original intrinsic and payment pipeline."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, DeckSpec, Game,
    IntrinsicCostSpec, MatchSetup, OpeningHook, PaymentType, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals, ChoiceOption,
    Damage, DamageBatch, Draw, GainArmor, InvokeBehavior, ModifyCost, RequestChoice, Summon)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_origin, validate_intrinsic_stage_fact,
    validate_intrinsic_history_prefix, validate_generated_quote_fact)
from hs_sim.engine.model import CurrentDeckCountMatch, DamageKind
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash, _intrinsic_stage_from_dict
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DestroyDeckMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='JAIL_307'
HISTORY='deck.current-count-v1'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/current-deck-count-cost-basics.json'
PIN='c00c1684dcbb1de833c090ec20dbcdf02ca4e6a035fb9d5ec6c6280029998102'


def evidence():
    value=json.loads(SUPPORT.read_bytes())
    if canonical_digest(value)!=PIN or [r['id'] for r in value['records']]!=[NATIVE]:
        raise ValueError('Complete conditional deck-price evidence changed')
    row=value['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Complete source card changed')
    return row['data']


def spec(count=25,comparison='at_least',**kwargs):
    return IntrinsicCostSpec(delta=kwargs.pop('delta',-2),condition='current_deck_count',
        history_profile_id=HISTORY,card_count=count,comparison=comparison,**kwargs)


def pause(player):
    return RequestChoice(player,(ChoiceOption('ok','Continue',()),))


def registry():
    r=opening_registry();raw=evidence()
    for i in range(1,71):
        r.register_card(CardDefinition(f'price.fill.{i}','Experimental physical deck slot',
            CardType.MINION,cost=1,health=2,metadata=metadata()))
    r.register_behavior('price.nop',lambda c:())
    for cid,kind,fields in (
        ('price.spell',CardType.SPELL,{}),
        ('price.weapon',CardType.WEAPON,{'attack':1,'durability':1}),
        ('price.location',CardType.LOCATION,{'durability':1,'on_use':'price.nop'}),
        ('price.hero',CardType.HERO,{'health':30,'hero_card':True,'initial_hero_power':'mage.power','on_play':'price.nop'}),
    ):
        r.register_card(CardDefinition(cid,cid,kind,
            metadata=metadata(CardClass.MAGE if kind==CardType.HERO else CardClass.NEUTRAL),**fields))
    r.register_card(CardDefinition('price.no_meta','Known definition without class metadata',CardType.MINION,health=1))
    r.register_card(CardDefinition('price.body','Experimental live target',CardType.MINION,health=6,metadata=metadata()))
    r.register_card(CardDefinition('price.bonus','Experimental ordinary spell-damage source',CardType.MINION,health=8,spell_damage=1,metadata=metadata()))
    r.register_card(CardDefinition('price.token','Experimental new second-batch target',CardType.MINION,health=3,metadata=metadata(collectible=False)))
    r.register_behavior('price.fragile.death',lambda c:(Summon(c.player_id,'price.token'),))
    r.register_card(CardDefinition('price.fragile','Experimental first-batch death',CardType.MINION,health=1,
        deathrattle='price.fragile.death',metadata=metadata()))

    def volley(c):
        ids=tuple(i for p in (1,2) for i in c.state.players[p].board
            if (e:=c.state.entities[i]).kind==CardType.MINION and e.active and e.health>0 and not e.doomed)
        return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL) for i in ids)),)
    r.register_behavior('price.volley',volley)
    r.register_behavior('price.native',lambda c:tuple(InvokeBehavior('price.volley',c.source_id,c.player_id) for _ in range(2)))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.FIRE,
        metadata=metadata_from_record(raw),intrinsic_costs=(spec(),),on_play='price.native'))
    r.register_card(CardDefinition('price.low','Experimental inverse inclusive comparator',CardType.SPELL,cost=5,
        metadata=metadata(CardClass.WARRIOR),intrinsic_costs=(spec(10,'at_most'),),on_play='price.nop'))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id,9),AddToHand(c.player_id,NATIVE))
    r.register_behavior('price.prepare',prepare)
    r.register_card(CardDefinition('price.fixture.prepare','Experimental opening preparation',CardType.MINION,
        health=1,metadata=metadata(),opening_hooks=(OpeningHook('after_mulligan','price.prepare'),)))

    def fail(c):
        raise ResolutionError('Expected late conditional deck-price failure')
    r.register_behavior('price.fail',fail)
    subject=lambda c:c.state.entities[next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==NATIVE)]
    scripts={
        'price.draw':lambda c:(Draw(c.player_id),),
        'price.add':lambda c:(AddToDeck(c.player_id,'price.fill.70'),),
        'price.clear':lambda c:(DestroyDeckMatching(c.player_id,count=70,reveal=False),),
        'price.copy':lambda c:(CopyCard(CardReference.capture(subject(c)),3-c.player_id),),
        'price.transfer':lambda c:(MoveCard(CardReference.capture(subject(c)),3-c.player_id,Zone.HAND),),
        'price.layers':lambda c:(ModifyCost(subject(c).id,CostSpec(set_to=4)),
            AddCostModifier(c.player_id,CostSpec(delta=-1,card_ids=(NATIVE,)))),
        'price.health.pay':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(NATIVE,))),),
    }
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    for cid,fn in (
        ('price.wait',lambda c:(Draw(c.player_id),pause(c.player_id),GainArmor(c.player_id,1))),
        ('price.action.fail',lambda c:(Draw(c.player_id),GainArmor(c.player_id,1),InvokeBehavior('price.fail',c.source_id,c.player_id))),
        ('price.wait.fail',lambda c:(Draw(c.player_id),pause(c.player_id),InvokeBehavior('price.fail',c.source_id,c.player_id))),
    ):
        r.register_behavior(cid,fn)
        r.register_card(CardDefinition(cid,'Explicit price-window instrumentation',CardType.SPELL,cost=5,
            intrinsic_costs=(spec(),),on_play=cid,metadata=metadata(CardClass.WARRIOR)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class CurrentDeckCountCostTests(unittest.TestCase):
    def game(self,count=25,hand=(NATIVE,),*,other_count=24,other_hand=(),board=(),other_board=(),active=1,deck=None):
        own=tuple(f'price.fill.{i}' for i in range(1,count+1)) if deck is None else tuple(deck)
        other=tuple(f'price.fill.{i}' for i in range(1,other_count+1))
        return Game.from_scenario(Scenario((
            PlayerSetup('warrior.hero',hand=hand,deck=own,board=board,mana=10,max_mana=10,hero_power_card_id='warrior.power'),
            PlayerSetup('mage.hero',hand=other_hand,deck=other,board=other_board,mana=10,max_mana=10,hero_power_card_id='mage.power')),
            active_player=active,seed=86),registry())

    def source(self,g,player=1,cid=NATIVE):
        return next(g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)

    def fact(self,g,player=1,cid=NATIVE):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,player,cid)))

    def play(self,g,cid=NATIVE):
        player=g.state.active_player;eid=self.source(g,player,cid).id
        g.apply(PlayCard(player,eid));return eid

    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        return restored

    def reject(self,saved):
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())

    def test_complete_raw_pin_printed_native_spell_and_declared_count_price(self):
        raw=evidence();card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.kind,card.spell_school,card.metadata.classes,card.metadata.rarity),
            (5,CardType.SPELL,SpellSchool.FIRE,(CardClass.WARRIOR,),Rarity.RARE))
        self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual(card.intrinsic_costs,(spec(),))
        self.assertIn('25 or more cards',raw['text_en']);self.assertIn('twice',raw['text_en'])
        self.assertEqual(raw['tags']['SPELL_SCHOOL'],2)

    def test_24_25_26_counts_quote_five_three_three_and_pay_once(self):
        for count,price in ((24,5),(25,3),(26,3)):
            with self.subTest(count=count):
                g=self.game(count);q=self.fact(g)
                self.assertEqual((q.intrinsic.amount,q.amount),(price,price))
                self.assertEqual(q.intrinsic.condition_facts[0].deck,tuple(g.state.players[1].deck))
                self.play(g)
                self.assertEqual(g.state.players[1].mana,10-price)
                self.assertEqual(len(g.state.play_history),1)
                paid=g.state.play_history[-1].submitted_cost.quote
                self.assertEqual(paid.amount,q.amount)
                self.assertEqual(paid.intrinsic.condition_facts[0].deck,q.intrinsic.condition_facts[0].deck)
                self.assertEqual(paid.intrinsic.boundary.action,g.state.action_number)
                self.assertEqual(g.state.cost_use_history[-1].current_deck,paid.intrinsic.condition_facts[0])
                self.portable(g)

    def test_every_kind_and_duplicate_face_counts_as_physical_slot(self):
        deck=('price.spell','price.weapon','price.location','price.hero')+('price.fill.1',)*21
        g=self.game(deck=deck)
        self.assertEqual(self.fact(g).amount,3)
        match=self.fact(g).intrinsic.condition_facts[0]
        self.assertEqual(len(match.deck),25);self.assertEqual(len(set(match.deck)),25)
        self.portable(g)

    def test_known_deck_definition_without_class_metadata_still_counts(self):
        g=self.game(deck=('price.no_meta',)*25)
        self.assertEqual(self.fact(g).amount,3)
        self.play(g);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_empty_and_inverse_inclusive_thresholds_use_current_inventory(self):
        for count in (0,10,11):
            g=self.game(count,('price.low',))
            self.assertEqual(self.fact(g,cid='price.low').amount,3 if count<=10 else 5)
        self.assertEqual(self.fact(self.game(0)).amount,5)

    def test_actual_payer_and_inactive_player_use_their_own_deck(self):
        g=self.game(26,other_count=24,other_hand=(NATIVE,),active=2)
        self.assertEqual((self.fact(g,1).amount,self.fact(g,2).amount),(3,5))
        self.play(g);self.assertEqual(g.state.players[2].mana,5)
        self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_draw_and_shuffle_cross_boundary_without_persistent_discount_cache(self):
        g=self.game(25,('price.draw','price.add',NATIVE))
        self.assertEqual(self.fact(g).amount,3)
        self.play(g,'price.draw');self.assertEqual(self.fact(g).amount,5)
        self.play(g,'price.add');self.assertEqual(self.fact(g).amount,3)
        self.portable(g)

    def test_current_clear_requotes_and_original_paid_fact_remains(self):
        g=self.game(26,(NATIVE,NATIVE,'price.clear'))
        self.play(g);stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.play(g,'price.clear');self.assertEqual(self.fact(g).amount,5)
        self.assertEqual(stage.amount,3)
        validate_intrinsic_history_prefix(stage,g.state,g.registry)
        self.portable(g)

    def test_physical_and_generated_quotes_are_pure_and_share_same_count(self):
        g=self.game();before=g.snapshot()
        for _ in range(3):
            physical=self.fact(g);generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
            self.assertEqual((physical.amount,generated.amount),(3,3))
            self.assertEqual(physical.intrinsic.condition_facts,generated.intrinsic.condition_facts)
            validate_generated_quote_fact(g.registry,generated)
        self.assertEqual(g.snapshot(),before)

    def test_intrinsic_discount_precedes_original_local_and_external_layers(self):
        g=self.game(25,('price.layers',NATIVE));self.play(g,'price.layers')
        q=self.fact(g);self.assertEqual((q.intrinsic.amount,q.local_amount,q.amount),(3,4,3))
        self.play(g);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_original_health_account_pays_accepted_amount_once(self):
        g=self.game(25,('price.health.pay',NATIVE));self.play(g,'price.health.pay')
        self.assertEqual((self.fact(g).payment,self.fact(g).amount),(PaymentType.HEALTH,3))
        self.play(g);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.portable(g)

    def test_hand_copy_quotes_for_destination_player_without_copying_discount(self):
        g=self.game(26,('price.copy',NATIVE),other_count=24)
        self.play(g,'price.copy')
        self.assertEqual((self.fact(g,1).amount,self.fact(g,2).amount),(3,5))
        self.assertNotEqual(self.source(g,1).id,self.source(g,2).id);self.portable(g)

    def test_hand_transfer_requotes_for_controller_even_with_original_owner(self):
        g=self.game(26,('price.transfer',NATIVE),other_count=24)
        original=self.source(g).id;self.play(g,'price.transfer')
        entity=self.source(g,2);self.assertEqual((entity.id,entity.owner,entity.controller),(original,1,2))
        self.assertEqual(self.fact(g,2).amount,5);self.portable(g)

    def test_waiting_after_payment_keeps_original_price_through_deck_change(self):
        g=self.game(25,('price.wait',NATIVE));self.play(g,'price.wait')
        stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((stage.amount,self.fact(g).amount,g.state.players[1].mana),(3,5,7))
        validate_intrinsic_history_prefix(stage,g.state,g.registry)
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.players[1].mana,7)
        self.portable(g)

    def test_failed_action_rolls_back_payment_deck_history_and_discount_window(self):
        g=self.game(25,('price.action.fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'price.action.fail')
        self.assertEqual(g.snapshot(),before)

    def test_failed_waiting_choice_preserves_already_paid_root_and_pending_deck(self):
        g=self.game(25,('price.wait.fail',));self.play(g,'price.wait.fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,7)
        self.portable(g)

    def test_complete_quote_dictionary_and_typed_codec_roundtrip(self):
        g=self.game();stage=self.fact(g).intrinsic;codec=FrameCodec(g.mechanics,g.registry)
        wire=json.loads(json.dumps(codec.encode(stage)))
        self.assertEqual(codec.decode(wire),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)
        match=codec.encode(stage.condition_facts[0])
        self.assertEqual(set(match['fields']),{'player_id','turn','action','next_entity_id','deck','card_count','comparison','matched'})
        self.assertEqual(set(codec.encode(spec())['fields']),{'delta','set_to','minimum','condition','history_profile_id','profile_id','card_count','comparison','mana_crystals','card_ids'})
        validate_intrinsic_origin(stage,g.state,g.registry)

    def test_original_window_rejects_same_price_omitted_or_reordered_inventory(self):
        g=self.game(26);stage=self.fact(g).intrinsic;match=stage.condition_facts[0]
        for deck in (match.deck[:-1],tuple(reversed(match.deck))):
            changed=replace(stage,condition_facts=(replace(match,deck=deck),))
            validate_intrinsic_stage_fact(g.registry,changed)
            with self.assertRaises(ValueError):validate_intrinsic_origin(changed,g.state,g.registry)

    def test_original_window_rejects_foreign_physical_inventory_even_same_count(self):
        g=self.game(25,other_count=25);stage=self.fact(g).intrinsic;match=stage.condition_facts[0]
        changed=replace(stage,condition_facts=(replace(match,deck=tuple(g.state.players[2].deck)),))
        validate_intrinsic_stage_fact(g.registry,changed)
        with self.assertRaises(ValueError):validate_intrinsic_origin(changed,g.state,g.registry)

    def test_strict_match_player_clock_allocator_ids_comparator_and_aggregate(self):
        g=self.game();match=self.fact(g).intrinsic.condition_facts[0]
        for changes in ({'player_id':True},{'turn':0},{'action':True},{'next_entity_id':0},
                        {'deck':list(match.deck)},{'deck':match.deck+(match.deck[0],)},
                        {'deck':(match.next_entity_id,)},{'card_count':True},{'card_count':-1},
                        {'comparison':'greater'},{'matched':False},{'matched':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(match,**changes)

    def test_stage_rejects_changed_window_threshold_payer_or_missing_match(self):
        g=self.game();stage=self.fact(g).intrinsic;match=stage.condition_facts[0]
        for changes in ({'turn':match.turn+1},{'action':match.action+1},{'card_count':24},{'player_id':2}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(stage,condition_facts=(replace(match,**changes),))
        with self.assertRaises(ValueError):replace(stage,condition_facts=())

    def test_declarations_reject_ambiguous_counts_profiles_operations_and_foreign_kind(self):
        for make in (lambda:spec(True),lambda:spec(-1),lambda:spec(25,'greater'),lambda:spec(set_to=1),
                     lambda:spec(delta=1),lambda:spec(minimum=1),
                     lambda:IntrinsicCostSpec(condition='current_deck_count',card_count=25,comparison='at_least'),
                     lambda:IntrinsicCostSpec(card_count=25),lambda:IntrinsicCostSpec(comparison='at_least')):
            with self.subTest(make=make),self.assertRaises(ValueError):make()
        for card in (CardDefinition('invalid.minion','Unsupported source',CardType.MINION,health=1,intrinsic_costs=(spec(),)),
                     CardDefinition('invalid.multiple','Unsupported multiple declarations',CardType.SPELL,intrinsic_costs=(spec(),spec()))):
            with self.subTest(card=card.id),self.assertRaises(ValueError):registry().register_card(card)

    def test_old_history_declarations_keep_none_new_operands_and_roundtrip(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry)
        for rule in (IntrinsicCostSpec(),IntrinsicCostSpec(condition='previous_owner_turn_elemental'),
                     IntrinsicCostSpec(condition='hero_healed_this_turn',history_profile_id='healing.hero-this-turn-v1')):
            self.assertIsNone(rule.card_count);self.assertIsNone(rule.comparison)
            self.assertEqual(codec.decode(codec.encode(rule)),rule)

    def test_late_unknown_definition_and_wrong_deck_controller_reject_capture(self):
        g=self.game();entity=self.source(g);state=g.state
        state.entities[state.players[1].deck[-1]].card_id='unknown.price.face'
        with self.assertRaises(UnsupportedDefinitionError):capture_quote_fact(state,g.registry,capture_cost_input(entity))
        state=g.state;state.entities[state.players[1].deck[-1]].controller=2
        with self.assertRaises(ValueError):capture_quote_fact(state,g.registry,capture_cost_input(entity))

    def test_rehashed_paid_record_cannot_omit_same_price_inventory_or_full_condition(self):
        g=self.game(26);self.play(g)
        for omit_all in (False,True):
            saved=g.snapshot();conditions=saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts']
            if omit_all:conditions.clear()
            else:conditions[0]['deck'].pop()
            self.reject(saved)
        for remove_all in (False,True):
            saved=g.snapshot();row=saved['state']['cost_use_history'][-1]
            if remove_all:row['current_deck']=None
            else:row['current_deck']['deck'].pop()
            self.reject(saved)

    def test_native_two_batches_hit_both_sides_and_new_deathrattle_body(self):
        g=self.game(board=('price.fragile',),other_board=('price.body',))
        self.play(g)
        own=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.card_id,e.health) for e in own],[('price.token',1)])
        other=g.state.entities[g.state.players[2].board[0]];self.assertEqual(other.health,2)
        for p in (1,2):self.assertEqual(g.state.entities[g.state.players[p].hero_id].health,30)
        self.portable(g)

    def test_native_spell_damage_uses_each_current_batch_and_keeps_price_independent(self):
        g=self.game(board=('price.bonus',),other_board=('price.body',))
        self.assertEqual(self.fact(g).amount,3);self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,2)
        self.assertEqual(g.state.players[2].board,[]);self.assertEqual(g.state.players[1].mana,7)
        self.portable(g)

    def test_public_commands_show_price_submit_once_and_hide_private_count_proof(self):
        g=self.game();port=g.for_player(1);dto=port.legal_actions()
        row=next(r for r in g.observe(1)['players'][0]['hand'] if r['card_id']==NATIVE)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.players[1].mana,7)
        for p in (1,2):
            text=json.dumps((g.observe(p),g.for_player(p).legal_actions(),g.player_events(p)))
            for value in ('CurrentDeckCountMatch','card_count','condition_facts','history_profile_id','price.fill.25'):
                self.assertNotIn(value,text)
        self.portable(g)

    def test_constructed_thirty_slots_and_mulligan_keep_current_price_distinct(self):
        r=registry();own=(NATIVE,'price.fixture.prepare')+tuple(f'price.fill.{i}' for i in range(1,29))
        other=tuple(f'price.fill.{i}' for i in range(1,31))
        g=Game.from_decks(MatchSetup((DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,own),
            DeckSpec('mage.hero','mage.power',CardClass.MAGE,other)),policy(r),'coin',86,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual((len(g.state.players[1].original_deck),len(g.state.players[1].deck)),(30,26))
        self.assertEqual(self.fact(g).amount,3);self.play(g)
        self.assertEqual((g.state.players[1].mana,len(g.state.players[1].deck)),(7,26));self.portable(g)

    def test_new_protocol_identity_rejects_previous_schema_and_handler(self):
        g=self.game();self.assertEqual((g.snapshot()['schema_version'],g.ruleset.id,g.mechanics.version),
            (SNAPSHOT_SCHEMA_VERSION,'prototype-v302',CORE_EFFECTS_VERSION))
        saved=g.snapshot();saved['schema_version']=216;self.reject(saved)
        saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v239';self.reject(saved)


if __name__=='__main__':unittest.main()
