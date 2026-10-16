"""A real current-Health threshold reuses original hero price facts and combat."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, BoardMinionCostSpec, CardClass, CardDefinition, CardType,
    CostSpec, EndTurn, Game, HeroMissingHealthCostFact, HeroMissingHealthCostSpec,
    IllegalAction, InteractableSpec, Keyword, PlayerSetup, PlayCard, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage,
    GainArmor, Heal, InvokeBehavior, ModifyCost, ReplaceHero, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.health_loss import ChangeHeroMaxHealth, GainMaxHealth, LoseHealth
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_hero_missing_health_cost_basics import registry as original_health_registry, MOLTEN
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='AV_141t'
PROFILE='cost.hero-health-at-most-fifteen-v1'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/hero-health-threshold-cost-basics.json'
PIN='2e105d39947cdeba792d70b5867bbbc84323ff91f508f4ffa6d3411a32e217c6'


def evidence():
    support=json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Health threshold evidence changed')
    item=support['records'][0]
    if canonical_digest(item['data'])!=item['data_sha256']:raise ValueError('Health threshold raw changed')
    return item['data']


def registry():
    r=original_health_registry();raw=evidence()
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=10,attack=8,health=8,
        metadata=metadata(rarity=Rarity.LEGENDARY,tribes=('ELEMENTAL',)),
        keywords=(Keyword.RUSH,Keyword.WINDFURY),hero_missing_health_cost=HeroMissingHealthCostSpec(PROFILE)))
    r.register_card(CardDefinition('t.target','Original combat target',CardType.MINION,attack=1,health=20))
    def hero(c):return c.state.players[c.player_id].hero_id
    def held(c):return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
        if c.state.entities[e].card_id==NATIVE)
    def first(c):return c.state.players[c.player_id].board[-1]
    bodies={
        't.heal':lambda c:(Heal(hero(c),5,c.source_id),),
        't.lose.one':lambda c:(LoseHealth(hero(c),1,c.source_id),),
        't.damage':lambda c:(Damage(hero(c),10,c.source_id),),
        't.gain.armor':lambda c:(GainArmor(c.player_id,100),),
        't.enemy15':lambda c:(LoseHealth(c.state.players[3-c.player_id].hero_id,15,c.source_id),),
        't.grow':lambda c:(GainMaxHealth(c.player_id,5,c.source_id),),
        't.shrink':lambda c:(ChangeHeroMaxHealth(c.player_id,-5,c.source_id),),
        't.grow.clamp':lambda c:(ChangeHeroMaxHealth(c.player_id,61,c.source_id,'clamp_current'),),
        't.shrink.clamp':lambda c:(ChangeHeroMaxHealth(c.player_id,-15,c.source_id,'clamp_current'),),
        't.replace':lambda c:(ReplaceHero(c.player_id,'hero.forty',health=25),),
        't.acquire':lambda c:(AddToHand(c.player_id,NATIVE),),
        't.local':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=4)),),
        't.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(NATIVE,))),),
        't.zero':lambda c:(ModifyCost(held(c).id,CostSpec(delta=-8)),),
        't.copy.enemy':lambda c:(CopyCard(CardReference.capture(held(c)),3-c.player_id,mode='base'),),
        't.silence':lambda c:(Silence(first(c)),),
        't.bounce':lambda c:(ReturnToHand(first(c)),),
        't.transform':lambda c:(Transform(first(c),'card.1'),),
    }
    for value in (1,10,14,15,16,20,25):
        bodies['t.health.'+str(value)]=lambda c,h=value:(LoseHealth(hero(c),30-h,c.source_id),)
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior('t.delayed.fail',lambda c:(Heal(hero(c),5,c.source_id),AddToHand(c.player_id,'unknown.health.threshold')))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('heal','Change current Health after payment',(Heal(hero(c),5,c.source_id),AddToHand(c.player_id,NATIVE))),
            ChoiceOption('replace','Replace current hero after payment',(ReplaceHero(c.player_id,'hero.forty',health=25),AddToHand(c.player_id,NATIVE))),
            ChoiceOption('fault','Delayed rollback',(InvokeBehavior('t.delayed.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('t.pause',pause)
    r.register_card(CardDefinition('t.watch','Completed payment probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_played','t.pause'),)))
    r.register_card(CardDefinition('t.commit.watch','Committed payment probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_committed','t.pause'),)))
    r.register_behavior('t.fail',lambda c:(AddToHand(c.player_id,'unknown.health.threshold'),)
        if c.state.entities[c.event.source_id].card_id==NATIVE else ())
    r.register_card(CardDefinition('t.fail.watch','Late root rollback probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_played','t.fail'),)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({key:value for key,value in saved.items()
        if key not in ('schema_version','events','events_hash','state_hash')})
    return saved


class HeroHealthThresholdCostTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),*,health=30,armor=0,enemy_hand=(),board=(),enemy_board=(),mana=10):
        init=() if health==30 else ('t.health.'+str(health),)
        game=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand+init,armor=armor,board=board,
                deck=('card.1',)*5,mana=mana,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,
                deck=('card.2',)*5,mana=10,max_mana=10)),seed=47),registry())
        if init:self.play(game,init[0])
        return game

    def source(self,g,cid=NATIVE,player=1):return next(g.state.entities[e] for e in g.state.players[player].hand
        if g.state.entities[e].card_id==cid)
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def play(self,g,cid=NATIVE):
        player=g.state.active_player;eid=self.source(g,cid,player).id;g.apply(PlayCard(player,eid));return eid
    def choose(self,g,option='heal'):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(option,)))
    def fact(self,g,cid=NATIVE,player=1,state=None):return capture_quote_fact(
        g.state if state is None else state,g.registry,capture_cost_input(self.source(g,cid,player)))
    def price(self,g,cid=NATIVE,player=1):return self.fact(g,cid,player).amount
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for player in (1,2):self.assertEqual(g.observe(player),other.observe(player))
        return saved

    def test_complete_native_raw_and_printed_metadata_keywords_have_no_extra_body(self):
        row=evidence();raw=json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(row,next(item for item in raw if item['id']==NATIVE))
        definition=registry().card(NATIVE)
        self.assertEqual((row['cost'],row['attack'],row['health']),
            (definition.cost,definition.attack,definition.health))
        self.assertEqual((definition.cost,definition.attack,definition.health),(10,8,8))
        self.assertEqual(definition.metadata.classes,(CardClass.NEUTRAL,))
        self.assertEqual((definition.metadata.rarity,definition.metadata.tribes),(Rarity.LEGENDARY,('ELEMENTAL',)))
        self.assertEqual(definition.keywords,(Keyword.RUSH,Keyword.WINDFURY))
        self.assertIsNone(definition.on_play);self.assertIn('15 Health or less',row['text_en'])

    def test_two_finite_policies_keep_old_default_and_reject_unsupported_declarations(self):
        self.assertEqual(HeroMissingHealthCostSpec().profile_id,'cost.hero-missing-health-v1')
        for profile in (None,True,'cost.hero-any-threshold-v1','damage.history'):
            with self.subTest(profile=profile),self.assertRaises(ValueError):HeroMissingHealthCostSpec(profile)
        r=registry()
        for change in ({'kind':CardType.SPELL,'health':0},{'hero_missing_health_cost':'expression'},
            {'interactable':InteractableSpec('hero.inert')},{'board_minion_cost':BoardMinionCostSpec()}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                r.register_card(replace(r.card(NATIVE),id='bad.threshold',**change))

    def test_actual_boundary_fourteen_fifteen_and_sixteen_is_fixed_five_or_zero(self):
        for health,price,quantity in ((14,5,5),(15,5,5),(16,10,0),(1,5,5),(30,10,0)):
            with self.subTest(health=health):
                g=self.game(health=health);fact=self.fact(g).intrinsic.hero_missing_health
                self.assertEqual((fact.health,fact.quantity,fact.before,fact.after),(health,quantity,10,price))
                self.assertEqual(self.price(g),price)

    def test_current_payer_hero_excludes_opponent_and_off_turn_has_same_threshold(self):
        g=self.game((NATIVE,'t.enemy15'),enemy_hand=(NATIVE,),health=16);self.play(g,'t.enemy15')
        self.assertEqual((self.price(g),self.price(g,player=2)),(10,5))
        self.assertEqual(self.fact(g,player=2).intrinsic.hero_missing_health.hero_id,g.state.players[2].hero_id)
        g.apply(EndTurn(1));self.assertEqual((self.price(g),self.price(g,player=2)),(10,5));self.portable(g)

    def test_current_health_not_missing_health_even_after_maximum_increase(self):
        g=self.game((NATIVE,MOLTEN,'t.grow.clamp'),health=16);self.play(g,'t.grow.clamp')
        self.assertEqual((self.hero(g).max_health,self.hero(g).health),(91,16))
        self.assertEqual((self.price(g),self.price(g,MOLTEN)),(10,0))
        self.assertEqual((self.fact(g).intrinsic.hero_missing_health.quantity,
            self.fact(g,MOLTEN).intrinsic.hero_missing_health.quantity),(0,75));self.portable(g)

    def test_fully_healthy_low_maximum_qualifies_without_any_missing_health(self):
        g=self.game((NATIVE,MOLTEN,'t.shrink.clamp'),health=15);self.play(g,'t.shrink.clamp')
        self.assertEqual((self.hero(g).max_health,self.hero(g).health),(15,15))
        self.assertEqual((self.price(g),self.price(g,MOLTEN)),(5,20));self.portable(g)

    def test_original_health_loss_and_healing_cross_boundary_and_old_quote_stays_frozen(self):
        g=self.game((NATIVE,'t.lose.one','t.heal'),health=16);old=self.fact(g).intrinsic
        self.play(g,'t.lose.one');self.assertEqual(self.price(g),5)
        validate_intrinsic_history_prefix(old,g.state,g.registry)
        self.play(g,'t.heal');self.assertEqual((self.hero(g).health,self.price(g)),(20,10));self.portable(g)

    def test_armor_gain_and_absorbed_damage_do_not_substitute_for_health_threshold(self):
        g=self.game((NATIVE,'t.gain.armor','t.damage'),health=16);self.play(g,'t.gain.armor');self.play(g,'t.damage')
        self.assertEqual((self.hero(g).health,self.hero(g).armor,self.price(g)),(16,90,10));self.portable(g)

    def test_damage_beyond_armor_uses_final_health_when_it_crosses_threshold(self):
        g=self.game((NATIVE,'t.damage'),health=20,armor=5);self.play(g,'t.damage')
        self.assertEqual((self.hero(g).health,self.hero(g).armor,self.price(g)),(15,0,5));self.portable(g)

    def test_preserve_missing_maximum_growth_and_shrink_use_final_current_health(self):
        g=self.game((NATIVE,'t.grow','t.shrink'),health=15);self.play(g,'t.grow')
        self.assertEqual((self.hero(g).max_health,self.hero(g).health,self.price(g)),(35,20,10))
        self.play(g,'t.shrink');self.assertEqual((self.hero(g).max_health,self.hero(g).health,self.price(g)),(30,15,5));self.portable(g)

    def test_original_hero_replacement_requotes_new_hero_and_keeps_old_physical_fact(self):
        g=self.game((NATIVE,'t.replace'),health=15);old=self.fact(g).intrinsic;self.play(g,'t.replace')
        new=self.fact(g).intrinsic.hero_missing_health
        self.assertNotEqual(new.hero_id,old.hero_missing_health.hero_id)
        self.assertEqual((new.hero_card_id,new.health,self.price(g)),('hero.forty',25,10))
        self.assertEqual(g.state.entities[old.hero_missing_health.hero_id].zone,Zone.GRAVEYARD)
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_acquisition_after_health_change_has_no_per_hand_counter(self):
        g=self.game(('t.acquire',),health=15);self.play(g,'t.acquire')
        self.assertEqual((self.source(g).base_cost,self.price(g)),(10,5));self.portable(g)

    def test_pure_physical_generated_display_dictionary_and_typed_facts_share_input(self):
        g=self.game(health=15);before=g.snapshot();stage=self.fact(g).intrinsic
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual(generated.intrinsic.hero_missing_health,stage.hero_missing_health)
        self.assertEqual(generated.amount,5);validate_generated_quote_fact(g.registry,generated)
        self.assertEqual(next(row['cost']['amount'] for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE),5)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)
        g.legal_actions();self.assertEqual(g.snapshot(),before)

    def test_generated_minimum_and_original_local_external_layers_follow_threshold(self):
        g=self.game((NATIVE,'t.local','t.external'),health=15)
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,NATIVE,minimum_cost=7).amount,7)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE,cost=CostSpec(delta=-8))
        self.assertEqual((generated.intrinsic.amount,generated.amount),(5,0));validate_generated_quote_fact(g.registry,generated)
        self.play(g,'t.local');self.play(g,'t.external');self.assertEqual(self.price(g),2)
        self.play(g);self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost),(8,2));self.portable(g)

    def test_native_payment_once_installs_original_eight_eight_rush_windfury(self):
        for health,cost in ((15,5),(16,10)):
            with self.subTest(health=health):
                g=self.game(health=health);eid=self.play(g);entity=g.state.entities[eid];play=g.state.play_history[-1]
                self.assertEqual((entity.attack,entity.health,entity.zone),(8,8,Zone.BOARD))
                self.assertIn(Keyword.RUSH,entity.keywords);self.assertIn(Keyword.WINDFURY,entity.keywords)
                self.assertEqual((play.cost,play.submitted_cost.quote.amount,g.state.players[1].mana),(cost,cost,10-cost))
                self.assertEqual(sum(record.card_id==NATIVE for record in g.state.play_history),1);self.portable(g)

    def test_native_original_rush_windfury_attack_limits_use_existing_combat(self):
        g=self.game(health=15,enemy_board=('t.target',));eid=self.play(g);enemy=g.state.players[2].board[0]
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,g.state.players[2].hero_id))
        g.apply(Attack(1,eid,enemy));g.apply(Attack(1,eid,enemy))
        self.assertEqual((g.state.entities[eid].attacks_this_turn,g.state.entities[enemy].health),(2,4))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,enemy))
        self.portable(g)

    def test_original_zero_local_cost_allows_one_zero_payment(self):
        g=self.game((NATIVE,'t.zero'),health=15,mana=0);self.play(g,'t.zero');self.play(g)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,0));self.portable(g)

    def test_player_port_visible_price_and_insufficient_payment_rollback_share_quote(self):
        g=self.game(health=15,mana=4);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(health=15);port=g.for_player(1);dto=port.legal_actions()
        row=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        action=next(action for action in dto['actions'] if action.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.play_history[-1].cost,5);self.portable(g)

    def test_original_printed_copy_to_other_payer_reads_other_current_hero(self):
        g=self.game((NATIVE,'t.copy.enemy'),health=15);self.play(g,'t.copy.enemy')
        self.assertEqual((self.price(g),self.price(g,player=2)),(5,10));self.portable(g)

    def test_native_silence_bounce_and_reacquire_do_not_install_permanent_price(self):
        g=self.game((NATIVE,'t.silence','t.bounce','t.heal'),health=15);eid=self.play(g)
        self.play(g,'t.silence');self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)
        self.play(g,'t.bounce');self.assertEqual((self.source(g).base_cost,self.price(g)),(10,5))
        self.play(g,'t.heal');self.assertEqual(self.price(g),10);self.portable(g)

    def test_native_transform_uses_current_definition_without_new_threshold_ability(self):
        g=self.game((NATIVE,'t.transform'),health=15);eid=self.play(g);self.play(g,'t.transform')
        self.assertEqual((g.state.entities[eid].card_id,quote_cost(g.state,g.registry,g.state.entities[eid]).amount),('card.1',1))
        self.assertIsNone(g.registry.card('card.1').hero_missing_health_cost);self.portable(g)

    def test_completed_paid_wait_restore_then_heal_keeps_original_fee_and_requotes_new_card(self):
        g=self.game(health=15,board=('t.watch',));self.play(g);old=g.state.play_history[-1].submitted_cost
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.play_history[-1].completed)
        saved=self.portable(g);other=Game.from_snapshot(saved,registry());self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.play_history[-1].submitted_cost,old)
        self.assertEqual((self.hero(g).health,self.price(g),g.state.players[1].mana),(20,10,5));self.portable(g)

    def test_committed_preentry_wait_restore_and_heal_keep_original_payment(self):
        for health,cost in ((15,5),(16,10)):
            with self.subTest(health=health):
                g=self.game(health=health,board=('t.commit.watch',));self.play(g)
                self.assertIsNotNone(g.state.pending_choice);original=g.state.play_history[-1].submitted_cost
                self.assertFalse(g.state.play_history[-1].completed)
                self.assertFalse(any(g.state.entities[eid].card_id==NATIVE for eid in g.state.players[1].board))
                saved=self.portable(g);other=Game.from_snapshot(saved,registry());self.choose(g);self.choose(other)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.play_history[-1].submitted_cost,original)
                self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,self.price(g)),(cost,10-cost,10))
                self.assertTrue(g.state.play_history[-1].completed);self.portable(g)

    def test_committed_preentry_delayed_error_restores_paid_unentered_boundary(self):
        g=self.game(health=15,board=('t.commit.watch',));self.play(g);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'unknown.health.threshold'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.assertFalse(g.state.play_history[-1].completed)

    def test_completed_paid_wait_hero_replacement_retains_original_physical_hero(self):
        g=self.game(health=15,board=('t.watch',));self.play(g);old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.portable(g);self.choose(g,'replace')
        self.assertEqual((self.hero(g).health,self.price(g),g.state.play_history[-1].cost),(25,10,5))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_delayed_error_rolls_back_health_and_keeps_paid_choice(self):
        g=self.game(health=15,board=('t.watch',));self.play(g);before=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'unknown.health.threshold'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_late_root_error_rolls_back_payment_native_installation_and_history(self):
        g=self.game(health=15,board=('t.fail.watch',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unknown.health.threshold'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_origin_rechecks_raw_health_even_when_threshold_and_amount_are_identical(self):
        g=self.game(health=14);stage=self.fact(g).intrinsic
        forged=replace(stage,hero_missing_health=replace(stage.hero_missing_health,health=13))
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)
        validate_intrinsic_origin(stage,g.state,g.registry)
        # Compact retained-hero proof cannot authenticate unsigned original stats.
        validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_frozen_fact_types_finite_quantity_and_both_original_health_values_are_strict(self):
        fact=self.fact(self.game(health=15)).intrinsic.hero_missing_health
        with self.assertRaises(FrozenInstanceError):fact.health=14
        for change in ({'health':True},{'max_health':False},{'health':31},{'player_id':True},
            {'hero_id':fact.next_entity_id},{'hero_card_id':''},{'quantity':15},{'quantity':0},
            {'before':True},{'after':0},{'spec':None}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(fact,**change)
        changed=replace(fact,max_health=91);self.assertEqual((changed.health,changed.quantity,changed.after),(15,5,5))

    def test_false_threshold_still_requires_original_supported_correct_hero_identity(self):
        g=self.game(health=16)
        for mode in ('missing','unknown','nonhero','kind','zone','owner','controller'):
            state=deepcopy(g.state);hero=state.entities[state.players[1].hero_id]
            if mode=='missing':del state.entities[hero.id]
            elif mode=='unknown':hero.card_id='unknown.threshold.hero'
            elif mode=='nonhero':hero.card_id='card.1'
            elif mode=='kind':hero.kind=CardType.MINION
            elif mode=='zone':hero.zone=Zone.GRAVEYARD
            elif mode=='owner':hero.owner=2
            elif mode=='controller':hero.controller=2
            with self.subTest(mode=mode),self.assertRaises((ValueError,KeyError)):self.fact(g,state=state)

    def test_compact_prefix_rejects_missing_foreign_hero_and_pinned_face_changes(self):
        g=self.game(health=15);stage=self.fact(g).intrinsic
        for mode in ('missing','owner','controller','face','allocator'):
            state=deepcopy(g.state);hero=state.entities[stage.hero_missing_health.hero_id]
            if mode=='missing':del state.entities[hero.id]
            elif mode=='owner':hero.owner=2
            elif mode=='controller':hero.controller=2
            elif mode=='face':hero.card_id='warrior.hero'
            elif mode=='allocator':state.next_entity_id=hero.id
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_intrinsic_history_prefix(stage,state,g.registry)

    def test_rehashed_paid_save_requires_complete_existing_health_leaf_and_finite_policy(self):
        g=self.game(health=15,board=('t.watch',));self.play(g);saved=self.portable(g)
        for mode in ('missing','null','quantity','profile','maxhealth','healthtype'):
            bad=deepcopy(saved);stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic'];fact=stage['hero_missing_health']
            if mode=='missing':fact.pop('health')
            elif mode=='null':stage['hero_missing_health']=None
            elif mode=='quantity':fact['quantity']=15
            elif mode=='profile':fact['spec']['profile_id']='cost.hero-any-threshold-v1'
            elif mode=='maxhealth':fact.pop('max_health')
            elif mode=='healthtype':fact['health']=True
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_player_projection_hides_frozen_profile_receipt_and_opponent_prices(self):
        g=self.game(health=15,enemy_hand=(NATIVE,));before=g.snapshot();visible=g.observe(1);text=json.dumps(visible)
        self.assertEqual(visible['players'][0]['hand'][0]['cost']['amount'],5)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in visible['players'][1]['hand']))
        for hidden in ('hero_missing_health','next_entity_id','submitted_cost','payment_state',PROFILE):self.assertNotIn(hidden,text)
        g.for_player(1).legal_actions();self.assertEqual(g.snapshot(),before)

    def test_same_schema_new_rules_and_effects_reject_old_semantics_and_wrong_layout(self):
        g=self.game();saved=self.portable(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'],g.for_player(1).observe()['version']),('player-view-v86','player-actions-v12'))
        for field,value in (('rules','prototype-v218'),('effects','core-effects-v212'),('schema',203),('schema',217),('schema',True)):
            bad=deepcopy(saved)
            if field=='rules':bad['ruleset']['id']=value
            elif field=='effects':bad['mechanics_version']['version']=value
            else:bad['schema_version']=value
            with self.subTest(field=field,value=value),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())


if __name__=='__main__':unittest.main()
