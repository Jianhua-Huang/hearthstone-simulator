"""Two actual Armor prices share the original hero, payment and execution."""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    IllegalAction, IntrinsicCostSpec, PlayerArmorCostFact, PlayerArmorCostSpec, PlayerDrawCountCostSpec,
    PlayerSetup, PlayCard, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, DamageBatch,
    GainArmor, Heal, InvokeBehavior, ModifyCost, ReplaceHero, RequestChoice)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.player_armor_costs import validate_definition, validate_prefix
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SHATTER='AV_108'
GOGGLES='TOY_907'
ZERO='cost.player-current-hero-no-armor-zero-v1'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/player-armor-cost-basics.json'
PIN='f69b09850d0b0a174d0921680520dfa22764ea5bf6dd1cb33542e87b1de95fd5'


def evidence():
    v=json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(v)!=PIN:raise ValueError('Armor price evidence changed')
    rows={}
    for row in v['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Armor raw changed')
        rows[row['id']]=row['data']
    return rows


def registry():
    r=opening_registry();raw=evidence()
    def shatter(c):
        return (DamageBatch(tuple(Damage(eid,5,c.source_id,DamageKind.SPELL)
            for p in c.state.players.values() for eid in p.board
            if c.state.entities[eid].kind==CardType.MINION and c.state.entities[eid].active)),)
    r.register_behavior('a.shatter',shatter)
    r.register_behavior('a.goggles',lambda c:(GainArmor(c.player_id,6),))
    r.register_card(CardDefinition(SHATTER,raw[SHATTER]['name'],CardType.SPELL,cost=10,
        metadata=metadata(CardClass.WARRIOR,rarity=Rarity.RARE),spell_school=SpellSchool.FROST,
        on_play='a.shatter',player_armor_cost=PlayerArmorCostSpec()))
    r.register_card(CardDefinition(GOGGLES,raw[GOGGLES]['name'],CardType.SPELL,cost=2,
        metadata=metadata(CardClass.WARRIOR),on_play='a.goggles',player_armor_cost=PlayerArmorCostSpec(ZERO)))
    r.register_card(CardDefinition('a.new.hero','Original replacement hero',CardType.HERO,health=30,
        initial_hero_power='mage.power',metadata=metadata(CardClass.MAGE,collectible=False)))
    r.register_card(CardDefinition('a.victim','Original batch victim',CardType.MINION,health=6))
    def hero(c):return c.state.players[c.player_id].hero_id
    def held(c):return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
        if c.state.entities[e].card_id in (SHATTER,GOGGLES))
    bodies={
        'a.gain':lambda c:(GainArmor(c.player_id,5),),
        'a.damage':lambda c:(Damage(hero(c),3,c.source_id),),
        'a.big.damage':lambda c:(Damage(hero(c),9,c.source_id),),
        'a.lose':lambda c:(LoseHealth(hero(c),7,c.source_id),),
        'a.heal':lambda c:(Heal(hero(c),7,c.source_id),),
        'a.replace':lambda c:(ReplaceHero(c.player_id,'a.new.hero',armor=2),),
        'a.acquire':lambda c:(AddToHand(c.player_id,SHATTER),),
        'a.local':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=4)),),
        'a.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(SHATTER,GOGGLES))),),
        'a.copy.enemy':lambda c:(CopyCard(CardReference.capture(held(c)),3-c.player_id,mode='base'),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior('a.delayed.fail',lambda c:(GainArmor(c.player_id,5),AddToHand(c.player_id,'unknown.armor.price')))
    def pause(c):
        cid=c.state.entities[c.event.source_id].card_id
        if cid not in (SHATTER,GOGGLES):return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('gain','Change current Armor after payment',(GainArmor(c.player_id,5),AddToHand(c.player_id,cid))),
            ChoiceOption('replace','Replace current hero after payment',
                (ReplaceHero(c.player_id,'a.new.hero',armor=2),AddToHand(c.player_id,cid))),
            ChoiceOption('fault','Delayed original rollback',(InvokeBehavior('a.delayed.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('a.pause',pause)
    r.register_card(CardDefinition('a.watch','Completed payment probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_played','a.pause'),)))
    r.register_behavior('a.fail',lambda c:(AddToHand(c.player_id,'unknown.armor.price'),)
        if c.state.entities[c.event.source_id].card_id in (SHATTER,GOGGLES) else ())
    r.register_card(CardDefinition('a.fail.watch','Late rollback probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_played','a.fail'),)))
    r.register_behavior('a.counter',lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id in (SHATTER,GOGGLES) else ())
    r.register_card(CardDefinition('a.counter.watch','Original counter probe',CardType.MINION,health=9,
        triggers=(TriggerSpec('card_committed','a.counter'),)))
    return r


def rehash(v):
    v['events_hash']=canonical_hash(v['events'])
    v['state_hash']=canonical_hash({k:x for k,x in v.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return v


class PlayerArmorCostTests(unittest.TestCase):
    def game(self,hand=(SHATTER,),*,armor=0,enemy_armor=0,board=(),enemy_board=(),enemy_hand=(),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,armor=armor,board=board,deck=('card.1',)*5,mana=mana,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,armor=enemy_armor,board=enemy_board,
                deck=('card.2',)*5,mana=10,max_mana=10)),seed=43),registry())

    def source(self,g,cid=SHATTER,player=1):return next(g.state.entities[e] for e in g.state.players[player].hand
        if g.state.entities[e].card_id==cid)
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def play(self,g,cid=SHATTER):
        player=g.state.active_player;g.apply(PlayCard(player,self.source(g,cid,player).id))
    def choose(self,g,option='gain'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def fact(self,g,cid=SHATTER,player=1,state=None):return capture_quote_fact(
        g.state if state is None else state,g.registry,capture_cost_input(self.source(g,cid,player)))
    def price(self,g,cid=SHATTER,player=1):return self.fact(g,cid,player).amount
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in (1,2):self.assertEqual(g.observe(p),other.observe(p))
        return saved
    def typed(self,g,stage):
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)

    def test_complete_two_raw_native_rows_and_exact_printed_types_metadata_bodies(self):
        rows=evidence();all_rows=json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(set(rows),{SHATTER,GOGGLES})
        for cid,raw in rows.items():self.assertEqual(raw,next(r for r in all_rows if r['id']==cid))
        r=registry();a,b=r.card(SHATTER),r.card(GOGGLES)
        self.assertEqual((a.cost,a.kind,a.metadata.classes,a.metadata.rarity,a.spell_school),
            (10,CardType.SPELL,(CardClass.WARRIOR,),Rarity.RARE,SpellSchool.FROST))
        self.assertEqual((b.cost,b.kind,b.metadata.classes,b.metadata.rarity,b.spell_school),
            (2,CardType.SPELL,(CardClass.WARRIOR,),Rarity.COMMON,None))
        self.assertIsNone(a.battlecry);self.assertIsNone(b.battlecry)

    def test_only_two_finite_profiles_ordinary_spell_and_one_original_input(self):
        for value in ('unknown','cost.player-hero-health-v1',False):
            with self.assertRaises(ValueError):PlayerArmorCostSpec(value)
        d=registry().card(SHATTER)
        for change in (dict(kind=CardType.MINION),dict(choice_only=True),dict(player_armor_cost='bad'),
            dict(player_draw_count_cost=PlayerDrawCountCostSpec()),dict(intrinsic_costs=(IntrinsicCostSpec(),))):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_definition(replace(d,**change))

    def test_zero_armor_keeps_complete_hero_allocation_and_printed_linear_price(self):
        g=self.game();f=self.fact(g).intrinsic.player_armor;a=allocation_from_payload(f.hero_allocation)
        self.assertEqual((f.armor,f.quantity,f.before,f.after,a.entity_id,a.zone),(0,0,10,10,self.hero(g).id,Zone.HERO))
        self.typed(g,self.fact(g).intrinsic)

    def test_current_actual_payer_armor_excludes_opponent_and_health(self):
        g=self.game(armor=4,enemy_armor=30,enemy_hand=(SHATTER,))
        self.assertEqual((self.price(g),self.price(g,player=2)),(6,0))
        self.assertEqual(self.fact(g).intrinsic.player_armor.armor,4)

    def test_original_gain_requotes_current_armor_and_old_fact_stays_frozen(self):
        g=self.game((SHATTER,'a.gain'),armor=4);old=self.fact(g).intrinsic;self.play(g,'a.gain')
        self.assertEqual((self.hero(g).armor,self.price(g),old.amount),(9,1,6))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_original_damage_absorption_requotes_remaining_armor_not_total_gain(self):
        g=self.game((SHATTER,'a.damage'),armor=4);self.play(g,'a.damage')
        self.assertEqual((self.hero(g).armor,self.hero(g).health,self.price(g)),(1,30,9));self.portable(g)

    def test_absorption_exhausts_armor_while_excess_health_damage_is_not_quantity(self):
        g=self.game((SHATTER,'a.big.damage'),armor=4);self.play(g,'a.big.damage')
        self.assertEqual((self.hero(g).armor,self.hero(g).health,self.price(g)),(0,25,10));self.portable(g)

    def test_direct_health_loss_and_heal_do_not_change_armor_price(self):
        g=self.game((SHATTER,'a.lose','a.heal'),armor=4);self.play(g,'a.lose')
        self.assertEqual((self.hero(g).health,self.hero(g).armor,self.price(g)),(23,4,6))
        self.play(g,'a.heal');self.assertEqual((self.hero(g).health,self.price(g)),(30,6));self.portable(g)

    def test_original_hero_replacement_requotes_new_slot_but_preserves_old_allocation(self):
        g=self.game((SHATTER,'a.replace'),armor=4);old=self.fact(g).intrinsic;old_id=self.hero(g).id
        self.play(g,'a.replace');self.assertNotEqual(self.hero(g).id,old_id)
        self.assertEqual((self.hero(g).armor,self.price(g),g.state.entities[old_id].zone),(6,4,Zone.GRAVEYARD))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_before_acquisition_current_armor_is_used_without_per_hand_history(self):
        g=self.game(('a.gain','a.acquire'),armor=4);self.play(g,'a.gain');self.play(g,'a.acquire')
        self.assertEqual(self.price(g),1);self.portable(g)

    def test_off_turn_current_armor_price_has_no_own_turn_gate(self):
        g=self.game(armor=4);old=self.fact(g).intrinsic;g.apply(EndTurn(1))
        self.assertEqual(self.price(g),6);validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_physical_generated_display_and_typed_quote_share_original_hero(self):
        g=self.game(armor=4);f=self.fact(g);v=capture_generated_quote_fact(g.state,g.registry,1,SHATTER)
        self.assertEqual(f.intrinsic,v.intrinsic);self.assertEqual((f.amount,v.amount),(6,6))
        validate_generated_quote_fact(g.registry,v)
        self.assertEqual(next(c['cost']['amount'] for c in g.observe(1)['players'][0]['hand'] if c['card_id']==SHATTER),6)
        self.typed(g,f.intrinsic)

    def test_linear_floor_and_generated_minimum_are_original_layers(self):
        g=self.game(armor=12);v=capture_generated_quote_fact(g.state,g.registry,1,SHATTER,minimum_cost=2)
        self.assertEqual((self.price(g),v.intrinsic.amount,v.amount),(0,0,2));self.typed(g,v.intrinsic)

    def test_actual_shatter_once_payment_and_original_five_damage_to_both_boards(self):
        g=self.game(armor=4,board=('a.victim',),enemy_board=('a.victim',));self.play(g)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,self.hero(g).armor),(6,4,4))
        self.assertEqual([g.state.entities[p.board[0]].health for p in g.state.players.values()],[1,1])
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30));self.portable(g)

    def test_actual_shatter_zero_mana_and_original_batch_deaths(self):
        g=self.game(armor=12,mana=0,board=('card.1',),enemy_board=('card.2',));self.play(g)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,0))
        self.assertEqual([len(p.board) for p in g.state.players.values()],[0,0]);self.portable(g)

    def test_player_command_pays_visible_price_through_original_spell_entry(self):
        g=self.game(armor=4);port=g.for_player(1);dto=port.legal_actions()
        row=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']==SHATTER)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.play_history[-1].cost,6);self.portable(g)

    def test_original_local_and_external_layers_follow_current_armor_stage(self):
        g=self.game((SHATTER,'a.local','a.external'),armor=4);self.play(g,'a.local');self.play(g,'a.external')
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(6,4,2))
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(2,8));self.portable(g)

    def test_insufficient_mana_does_not_change_hero_payment_hand_or_rng(self):
        g=self.game(armor=4,mana=5);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_printed_copy_to_other_payer_uses_other_current_hero_armor(self):
        g=self.game((SHATTER,'a.copy.enemy'),armor=4,enemy_armor=7);self.play(g,'a.copy.enemy')
        self.assertEqual((self.price(g),self.price(g,player=2)),(6,3));self.portable(g)

    def test_no_armor_profile_zero_uses_same_complete_current_hero_fact(self):
        g=self.game((GOGGLES,));f=self.fact(g,GOGGLES).intrinsic
        self.assertEqual((f.player_armor.spec.profile_id,f.player_armor.armor,f.amount),(ZERO,0,0))
        self.typed(g,f)

    def test_no_armor_profile_nonzero_is_printed_two_not_linear_subtraction(self):
        for armor in (1,2,12):
            with self.subTest(armor=armor):
                g=self.game((GOGGLES,),armor=armor);self.assertEqual(self.price(g,GOGGLES),2)

    def test_no_armor_profile_gain_switches_future_price_and_keeps_old_zero(self):
        g=self.game((GOGGLES,'a.gain'));old=self.fact(g,GOGGLES).intrinsic;self.play(g,'a.gain')
        self.assertEqual((self.price(g,GOGGLES),old.amount),(2,0))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_no_armor_profile_absorption_to_exact_zero_switches_future_price(self):
        g=self.game((GOGGLES,'a.damage'),armor=3);self.play(g,'a.damage')
        self.assertEqual((self.hero(g).armor,self.hero(g).health,self.price(g,GOGGLES)),(0,30,0));self.portable(g)

    def test_actual_zero_goggles_pays_original_zero_then_gains_six_without_reprice(self):
        g=self.game((GOGGLES,),mana=0);self.play(g,GOGGLES);record=g.state.play_history[-1]
        self.assertEqual((record.cost,g.state.players[1].mana,self.hero(g).armor),(0,0,6))
        self.assertEqual(record.submitted_cost.quote.intrinsic.player_armor.armor,0)
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,GOGGLES).amount,2);self.portable(g)

    def test_actual_nonzero_goggles_pays_two_and_adds_six_to_original_armor(self):
        g=self.game((GOGGLES,),armor=3);self.play(g,GOGGLES)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,self.hero(g).armor),(2,8,9));self.portable(g)

    def test_original_counter_preserves_payment_and_skips_each_native_body(self):
        for cid,cost,armor in ((SHATTER,6,4),(GOGGLES,0,0)):
            with self.subTest(cid=cid):
                g=self.game((cid,),armor=armor,board=('a.victim',),enemy_board=('a.counter.watch',));self.play(g,cid)
                r=g.state.play_history[-1]
                self.assertEqual((r.countered,r.cost,g.state.players[1].mana,self.hero(g).armor),(True,cost,10-cost,armor))
                self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,6);self.portable(g)

    def test_completed_payment_wait_restore_then_armor_gain_keeps_original_price(self):
        g=self.game(armor=4,board=('a.watch',));self.play(g);old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.play_history[-1].completed)
        saved=self.portable(g);other=Game.from_snapshot(saved,registry());self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual((self.price(g),g.state.play_history[-1].cost),(1,6))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_completed_payment_wait_hero_replacement_preserves_original_hero_allocation(self):
        g=self.game(armor=4,board=('a.watch',));self.play(g);old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.portable(g);self.choose(g,'replace');self.assertEqual((self.price(g),g.state.play_history[-1].cost),(4,6))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_completed_zero_goggles_wait_restore_keeps_pre_gain_quote(self):
        g=self.game((GOGGLES,),board=('a.watch',));self.play(g,GOGGLES);self.portable(g)
        self.choose(g);self.assertEqual((self.price(g,GOGGLES),g.state.play_history[-1].cost,self.hero(g).armor),(2,0,11))
        self.portable(g)

    def test_delayed_error_rolls_back_armor_and_keeps_original_paid_choice(self):
        g=self.game(armor=4,board=('a.watch',));self.play(g);before=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_late_root_failure_rolls_back_payment_native_body_and_armor(self):
        for cid,armor in ((SHATTER,4),(GOGGLES,0)):
            with self.subTest(cid=cid):
                g=self.game((cid,),armor=armor,board=('a.fail.watch',));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),before)

    def test_origin_rechecks_original_armor_even_with_identical_zero_amount(self):
        g=self.game(armor=12);old=self.fact(g).intrinsic
        forged=replace(old,player_armor=replace(old.player_armor,armor=13,quantity=13))
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)
        validate_intrinsic_origin(old,g.state,g.registry)
        # Structural compact allocation cannot authenticate unsigned original Armor.
        validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_fact_is_frozen_and_rejects_false_types_missing_reordered_or_foreign_allocation(self):
        g=self.game(armor=4);f=self.fact(g).intrinsic.player_armor
        with self.assertRaises(FrozenInstanceError):f.armor=5
        for change in (dict(armor=True),dict(armor=-1),dict(quantity=5),dict(before=11),dict(hero_allocation=None),
            dict(hero_allocation=f.hero_allocation[:-1]),dict(hero_allocation=tuple(reversed(f.hero_allocation))),
            dict(player_id=2),dict(next_order=1),dict(turn=False)):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(f,**change)

    def test_capture_rejects_unknown_or_missing_hero_and_wrong_identity_even_at_zero(self):
        g=self.game()
        for mode in ('missing','unknown','nonhero','zone','owner','controller','armor'):
            state=g.state;h=state.entities[state.players[1].hero_id]
            if mode=='missing':del state.entities[h.id]
            elif mode=='unknown':h.card_id='unknown.armor.hero'
            elif mode=='nonhero':h.card_id='card.1'
            elif mode=='zone':h.zone=Zone.GRAVEYARD
            elif mode=='owner':h.owner=2
            elif mode=='controller':h.controller=2
            else:h.armor=True
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.fact(g,state=state)

    def test_fact_and_prefix_reject_unknown_face_lost_owner_epoch_or_allocator(self):
        g=self.game(armor=4);old=self.fact(g).intrinsic.player_armor
        changed=tuple((k,'card.1' if k=='card_id' else v) for k,v in old.hero_allocation)
        bad=replace(self.fact(g).intrinsic,player_armor=replace(old,hero_allocation=changed))
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,bad)
        for mode in ('missing','owner','allocator'):
            state=g.state;a=allocation_from_payload(old.hero_allocation)
            if mode=='missing':del state.entities[a.entity_id]
            elif mode=='owner':state.entities[a.entity_id].owner=2
            else:state.next_order=old.next_order-1
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_prefix(old,state,g.registry)

    def test_rehashed_paid_save_requires_explicit_complete_armor_leaf_and_allocation(self):
        g=self.game(armor=4);self.play(g);saved=self.portable(g)
        for mode in ('missing','none','payer','allocation','type','quantity','profile'):
            bad=deepcopy(saved);stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic'];f=stage['player_armor']
            if mode=='missing':del stage['player_armor']
            elif mode=='none':stage['player_armor']=None
            elif mode=='payer':f['player_id']=2
            elif mode=='allocation':f['hero_allocation']=f['hero_allocation'][:-1]
            elif mode=='type':f['armor']=True
            elif mode=='quantity':f['quantity']+=1
            else:f['spec']['profile_id']=ZERO
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_ordinary_card_none_leaf_is_required_in_dictionary_and_typed_frame(self):
        g=self.game();stage=capture_generated_quote_fact(g.state,g.registry,1,'card.1').intrinsic
        self.assertIsNone(stage.player_armor);wire=json.loads(json.dumps(asdict(stage)));del wire['player_armor']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(wire)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(stage);del wire['fields']['player_armor']
        with self.assertRaises(ValueError):codec.decode(wire)

    def test_player_prices_are_pure_and_hide_frozen_hero_allocation_and_declaration(self):
        g=self.game(armor=4,enemy_hand=(GOGGLES,));before=g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g),6);capture_generated_quote_fact(g.state,g.registry,1,SHATTER)
            for p in (1,2):
                text=json.dumps(g.observe(p))
                for hidden in ('hero_allocation','player_armor_cost','submitted_cost',ZERO):self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_current_schema_versions_explicitly_reject_all_old_future_and_boolean_layouts(self):
        g=self.game(armor=4);saved=self.portable(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,265))
        for value in (*range(1,218),217,True):
            bad=deepcopy(saved);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())


if __name__=='__main__':unittest.main()
