"""One actual equipped weapon Attack price input, no second combat system."""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    IllegalAction, IntrinsicCostSpec, Keyword, PlayerDrawCountCostSpec, PlayerSetup,
    PlayerWeaponAttackCostFact, PlayerWeaponAttackCostSpec, PlayCard, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChoiceOption, Destroy, EquipWeapon,
    InvokeBehavior, ModifyCost, ModifyWeapon, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_weapon_attack_costs import validate_definition, validate_prefix
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

CORSAIR='NEW1_022'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/player-weapon-attack-cost-basics.json'
PIN='c590ee9c88ed67b3caff20b8ae89a7e5f82446dafc6e1f0ae8e89256e1827393'


def evidence():
    value=json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(value)!=PIN:raise ValueError('Weapon price evidence changed')
    rows={}
    for row in value['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Weapon price raw changed')
        rows[row['id']]=row['data']
    return rows


def registry():
    r=opening_registry();raw=evidence()[CORSAIR]
    r.register_card(CardDefinition(CORSAIR,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],keywords=(Keyword.TAUNT,),
        metadata=metadata(rarity=Rarity.COMMON,tribes=('PIRATE',)),
        player_weapon_attack_cost=PlayerWeaponAttackCostSpec()))
    for cid,attack,durability in (('w.two',2,3),('w.three',3,4),('w.big',7,4),('w.zero',0,3)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,attack=attack,durability=durability))
    def weapon(c):return c.state.players[c.player_id].weapon_id
    def held(c):
        return next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id==CORSAIR)
    def board(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==CORSAIR)
    bodies={
        'w.up':lambda c:(ModifyWeapon(weapon(c),attack=1,source_id=c.source_id),),
        'w.low':lambda c:(ModifyWeapon(weapon(c),attack=-9,source_id=c.source_id),),
        'w.break':lambda c:(ModifyWeapon(weapon(c),durability=-3,source_id=c.source_id),),
        'w.equip':lambda c:(EquipWeapon(c.player_id,'w.three'),),
        'w.destroy':lambda c:(Destroy(weapon(c),c.source_id),),
        'w.hero':lambda c:(Buff(c.state.players[c.player_id].hero_id,6,0,c.source_id,
            expires_turn=c.state.turn),),
        'w.acquire':lambda c:(AddToHand(c.player_id,CORSAIR),),
        'w.local':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=3)),),
        'w.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_ids=(CORSAIR,))),),
        'w.copy.enemy':lambda c:(CopyCard(CardReference.capture(held(c)),3-c.player_id,mode='base'),),
        'w.silence':lambda c:(Silence(board(c)),),
        'w.bounce':lambda c:(ReturnToHand(board(c)),),
        'w.transform':lambda c:(Transform(board(c),'card.1'),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior('w.delayed.fail',lambda c:(
        ModifyWeapon(weapon(c),attack=1,source_id=c.source_id),
        AddToHand(c.player_id,'unknown.weapon.price')))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=CORSAIR:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('lower','Change original weapon after payment',
                (ModifyWeapon(weapon(c),attack=-1,source_id=c.source_id),AddToHand(c.player_id,CORSAIR))),
            ChoiceOption('replace','Replace original weapon after payment',
                (EquipWeapon(c.player_id,'w.three'),AddToHand(c.player_id,CORSAIR))),
            ChoiceOption('fault','Original delayed rollback',
                (InvokeBehavior('w.delayed.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('w.pause',pause)
    r.register_card(CardDefinition('w.watch','Original completed payment window',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_played','w.pause'),)))
    r.register_behavior('w.fail',lambda c:(AddToHand(c.player_id,'unknown.weapon.price'),)
        if c.state.entities[c.event.source_id].card_id==CORSAIR else ())
    r.register_card(CardDefinition('w.fail.watch','Whole root rollback probe',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_played','w.fail'),)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class PlayerWeaponAttackCostTests(unittest.TestCase):
    def game(self,hand=(CORSAIR,),*,weapon=None,enemy_weapon=None,enemy_hand=(),board=(),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,board=board,weapon_card_id=weapon,
                deck=('card.1',)*6,mana=mana,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,weapon_card_id=enemy_weapon,
                deck=('card.2',)*6,mana=10,max_mana=10)),seed=41),registry())

    def source(self,g,cid=CORSAIR,player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand
            if g.state.entities[eid].card_id==cid)

    def play(self,g,cid=CORSAIR):
        player=g.state.active_player;g.apply(PlayCard(player,self.source(g,cid,player).id))

    def choose(self,g,option='lower'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))

    def fact(self,g,player=1,state=None):
        return capture_quote_fact(g.state if state is None else state,g.registry,
            capture_cost_input(self.source(g,player=player)))

    def price(self,g,player=1):return self.fact(g,player).amount

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for player in (1,2):self.assertEqual(other.observe(player),g.observe(player))
        return saved

    def typed(self,g,stage):
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)

    def test_complete_raw_native_and_core_evidence_only_native_four_three_three_taunt_pirate(self):
        raw=evidence();rows=json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(set(raw),{CORSAIR,'CORE_NEW1_022'})
        for cid,value in raw.items():self.assertEqual(value,next(row for row in rows if row['id']==cid))
        r=registry();d=r.card(CORSAIR)
        self.assertEqual((d.cost,d.attack,d.health,d.metadata.classes,d.metadata.rarity,d.metadata.tribes),
            (4,3,3,(CardClass.NEUTRAL,),Rarity.COMMON,('PIRATE',)))
        self.assertEqual(d.keywords,(Keyword.TAUNT,));self.assertIsNone(d.on_play);self.assertIsNone(d.battlecry)
        self.assertNotIn('CORE_NEW1_022',r.cards)

    def test_finite_minion_declaration_rejects_other_types_profiles_and_extra_formulas(self):
        d=registry().card(CORSAIR)
        for value in (True,None,'cost.hero-total-attack','cost.opponent-weapon'):
            with self.subTest(value=value),self.assertRaises(ValueError):PlayerWeaponAttackCostSpec(value)
        for change in (dict(kind=CardType.SPELL),dict(choice_only=True),dict(player_weapon_attack_cost='formula'),
                dict(player_draw_count_cost=PlayerDrawCountCostSpec()),dict(intrinsic_costs=(IntrinsicCostSpec(delta=-1),))):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_definition(replace(d,**change))

    def test_absent_weapon_has_explicit_empty_equipment_fact_and_no_discount(self):
        g=self.game();f=self.fact(g).intrinsic.weapon_attack
        self.assertEqual((self.price(g),f.weapon_allocation,f.attack,f.durability,f.doomed,f.quantity),(4,None,None,None,None,0))
        with self.assertRaises(FrozenInstanceError):f.quantity=1
        self.typed(g,self.fact(g).intrinsic);self.portable(g)

    def test_actual_weapon_attack_two_has_complete_original_slot_allocation_and_price_two(self):
        g=self.game(weapon='w.two');f=self.fact(g).intrinsic.weapon_attack
        allocation=allocation_from_payload(f.weapon_allocation)
        self.assertEqual((self.price(g),f.attack,f.quantity,f.durability,f.doomed),(2,2,2,3,False))
        self.assertEqual((allocation.entity_id,allocation.kind,allocation.zone,allocation.controller),
            (g.state.players[1].weapon_id,CardType.WEAPON,Zone.WEAPON,1))
        self.assertEqual((allocation.next_entity_id,allocation.next_order),(f.next_entity_id,f.next_order))
        self.typed(g,self.fact(g).intrinsic);self.portable(g)

    def test_opponent_weapon_does_not_supply_actual_payer_discount(self):
        g=self.game(enemy_weapon='w.big');self.assertEqual(self.price(g),4)
        self.assertIsNone(self.fact(g).intrinsic.weapon_attack.weapon_allocation);self.portable(g)

    def test_zero_attack_live_weapon_retains_original_identity_without_discount(self):
        g=self.game(weapon='w.zero');f=self.fact(g).intrinsic.weapon_attack
        self.assertEqual((self.price(g),f.attack,f.quantity,f.durability),(4,0,0,3))
        self.assertIsNotNone(f.weapon_allocation);self.portable(g)

    def test_hero_temporary_attack_does_not_substitute_for_weapon_attack(self):
        g=self.game((CORSAIR,'w.hero'),weapon='w.two');self.play(g,'w.hero')
        hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.attack,self.fact(g).intrinsic.weapon_attack.attack,self.price(g)),(8,2,2))
        self.portable(g)

    def test_hero_attack_without_weapon_does_not_discount(self):
        g=self.game((CORSAIR,'w.hero'));self.play(g,'w.hero')
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].attack,self.price(g)),(6,4));self.portable(g)

    def test_original_weapon_modifier_changes_new_quote_but_preserves_old_fact(self):
        g=self.game((CORSAIR,'w.up'),weapon='w.two');old=self.fact(g).intrinsic;self.play(g,'w.up')
        weapon=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.base_attack,weapon.attack,self.price(g),old.amount),(2,3,1,2))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_negative_weapon_modifier_uses_original_zero_clamped_attack(self):
        g=self.game((CORSAIR,'w.low'),weapon='w.two');self.play(g,'w.low')
        self.assertEqual((self.fact(g).intrinsic.weapon_attack.attack,self.price(g)),(0,4));self.portable(g)

    def test_replacing_weapon_uses_new_slot_and_keeps_old_allocation_in_history(self):
        g=self.game((CORSAIR,'w.equip'),weapon='w.two');old=self.fact(g).intrinsic
        old_id=allocation_from_payload(old.weapon_attack.weapon_allocation).entity_id;self.play(g,'w.equip')
        self.assertNotEqual(g.state.players[1].weapon_id,old_id)
        self.assertEqual((self.price(g),g.state.entities[old_id].zone),(1,Zone.GRAVEYARD))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_original_weapon_destruction_returns_new_quote_to_printed_cost(self):
        g=self.game((CORSAIR,'w.destroy'),weapon='w.two');old=self.fact(g).intrinsic;self.play(g,'w.destroy')
        self.assertEqual((g.state.players[1].weapon_id,self.price(g)),(None,4))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_original_zero_durability_cleanup_returns_to_no_weapon_quote(self):
        g=self.game((CORSAIR,'w.break'),weapon='w.two');self.play(g,'w.break')
        self.assertEqual((g.state.players[1].weapon_id,self.price(g)),(None,4));self.portable(g)

    def test_pure_transient_broken_and_doomed_raw_slots_are_retained_but_excluded(self):
        g=self.game(weapon='w.two')
        for durability,doomed in ((0,False),(-2,False),(3,True)):
            state=g.state;raw=state.entities[state.players[1].weapon_id]
            raw.durability,raw.doomed=durability,doomed
            stage=self.fact(g,state=state).intrinsic;f=stage.weapon_attack
            self.assertEqual((stage.amount,f.attack,f.quantity,f.durability,f.doomed),(4,2,0,durability,doomed))
            self.assertIsNotNone(f.weapon_allocation);self.typed(g,stage)
            validate_intrinsic_origin(stage,state,g.registry)
        self.assertEqual(self.price(g),2)

    def test_unknown_excluded_face_missing_slot_or_other_payer_identity_rejects(self):
        g=self.game(weapon='w.two',enemy_weapon='w.three')
        for mode in ('unknown','nonweapon_face','missing','other_payer','wrong_zone'):
            state=g.state;raw=state.entities[state.players[1].weapon_id]
            if mode=='unknown':raw.card_id='unknown.weapon';raw.doomed=True
            elif mode=='nonweapon_face':raw.card_id='card.1'
            elif mode=='missing':state.players[1].weapon_id=state.next_entity_id+1
            elif mode=='other_payer':state.players[1].weapon_id=state.players[2].weapon_id
            else:raw.zone=Zone.GRAVEYARD
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.fact(g,state=state)

    def test_off_turn_weapon_price_is_independent_of_inactive_hero_contribution(self):
        g=self.game(weapon='w.two');old=self.fact(g).intrinsic;g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].weapon_attack,self.price(g)),(0,2))
        validate_intrinsic_history_prefix(old,g.state,g.registry);g.apply(EndTurn(2))
        self.assertEqual(self.price(g),2);self.portable(g)

    def test_weapon_before_card_acquisition_is_the_current_price_source(self):
        g=self.game(('w.up','w.acquire'),weapon='w.two');self.play(g,'w.up');self.play(g,'w.acquire')
        self.assertEqual((self.price(g),self.source(g).base_cost),(1,4));self.portable(g)

    def test_physical_generated_and_player_quotes_use_the_same_original_equipment(self):
        g=self.game(weapon='w.two');physical=self.fact(g);generated=capture_generated_quote_fact(g.state,g.registry,1,CORSAIR)
        self.assertEqual((physical.intrinsic,physical.amount),(generated.intrinsic,generated.amount))
        validate_generated_quote_fact(g.registry,generated)
        row=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']==CORSAIR)
        self.assertEqual(row['cost']['amount'],2);self.typed(g,physical.intrinsic)

    def test_actual_native_payment_is_once_before_original_three_three_taunt_entry(self):
        g=self.game(weapon='w.two');self.play(g);record=g.state.play_history[-1]
        self.assertEqual((record.cost,g.state.players[1].mana,record.submitted_cost.quote.intrinsic.weapon_attack.quantity),(2,8,2))
        native=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((native.base_cost,native.attack,native.health),(4,3,3));self.assertIn(Keyword.TAUNT,native.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,3);self.portable(g)

    def test_zero_price_floor_and_generated_minimum_follow_current_attack(self):
        g=self.game(weapon='w.big');generated=capture_generated_quote_fact(g.state,g.registry,1,CORSAIR,minimum_cost=2)
        self.assertEqual((self.price(g),generated.intrinsic.amount,generated.amount),(0,0,2))
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,10));self.portable(g)

    def test_player_command_pays_visible_price_and_uses_original_entry(self):
        g=self.game(weapon='w.two');port=g.for_player(1);dto=port.legal_actions()
        row=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']==CORSAIR)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(2,8));self.portable(g)

    def test_original_local_and_external_cost_layers_are_after_weapon_quantity(self):
        g=self.game((CORSAIR,'w.local','w.external'),weapon='w.two');self.play(g,'w.local');self.play(g,'w.external')
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(2,3,2))
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(2,8));self.portable(g)

    def test_insufficient_mana_preserves_original_slot_card_and_full_state(self):
        g=self.game(weapon='w.two',mana=1);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_printed_copy_requotes_new_payer_weapon_without_local_discount_cache(self):
        g=self.game((CORSAIR,'w.copy.enemy'),weapon='w.two',enemy_weapon='w.three');self.play(g,'w.copy.enemy')
        self.assertEqual((self.price(g),self.price(g,2),self.source(g,player=2).base_cost),(2,1,4));self.portable(g)

    def test_native_silence_and_bounce_reuse_printed_input_with_current_weapon(self):
        g=self.game((CORSAIR,'w.silence','w.up','w.bounce'),weapon='w.two');self.play(g)
        self.play(g,'w.silence');self.play(g,'w.up');self.play(g,'w.bounce')
        self.assertEqual((self.source(g).base_cost,self.price(g)),(4,1));self.portable(g)

    def test_transforming_priced_minion_follows_new_definition_and_clears_intrinsic_source(self):
        g=self.game((CORSAIR,'w.transform'),weapon='w.two');self.play(g);self.play(g,'w.transform')
        entity=g.state.entities[g.state.players[1].board[0]];self.assertEqual(entity.card_id,'card.1')
        generated=capture_generated_quote_fact(g.state,g.registry,1,entity.card_id)
        self.assertEqual(generated.amount,1);self.assertIsNone(generated.intrinsic.weapon_attack);self.portable(g)

    def test_completed_payment_choice_recovers_then_new_weapon_attack_does_not_reprice(self):
        g=self.game(weapon='w.two',board=('w.watch',));self.play(g)
        old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.play_history[-1].completed)
        saved=self.portable(g);other=Game.from_snapshot(saved,registry())
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((self.price(g),g.state.play_history[-1].cost,g.state.players[1].mana),(3,2,8))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_completed_choice_replacing_weapon_allows_legal_zone_epoch_progress(self):
        g=self.game(weapon='w.two',board=('w.watch',));self.play(g)
        old=g.state.play_history[-1].submitted_cost.quote.intrinsic;self.portable(g);self.choose(g,'replace')
        self.assertEqual((self.price(g),g.state.play_history[-1].cost),(1,2))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_delayed_error_rolls_back_weapon_change_and_keeps_original_paid_choice(self):
        g=self.game(weapon='w.two',board=('w.watch',));self.play(g);before=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_late_root_error_rolls_back_native_entry_payment_and_equipment(self):
        g=self.game(weapon='w.two',board=('w.fail.watch',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_exact_origin_rechecks_values_even_when_zero_floor_amount_is_unchanged(self):
        g=self.game(weapon='w.big');stage=self.fact(g).intrinsic
        forged=replace(stage,weapon_attack=replace(stage.weapon_attack,attack=8,quantity=8))
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)
        old=self.fact(g).intrinsic;validate_intrinsic_origin(old,g.state,g.registry)
        # Compact allocation alone cannot certify the original unsigned stats.
        validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_complete_fact_rejects_false_types_missing_values_wrong_payer_and_future_bounds(self):
        g=self.game(weapon='w.two');f=self.fact(g).intrinsic.weapon_attack
        for change in (dict(attack=True),dict(durability=True),dict(doomed=0),dict(quantity=3),
                dict(weapon_allocation=None),dict(weapon_allocation=f.weapon_allocation[:-1]),
                dict(weapon_allocation=tuple(reversed(f.weapon_allocation))),dict(next_entity_id=1),
                dict(player_id=2),dict(turn=False),dict(before=5)):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(f,**change)
        changed=tuple((k,'card.1' if k=='card_id' else v) for k,v in f.weapon_allocation)
        stage=replace(self.fact(g).intrinsic,weapon_attack=replace(f,weapon_allocation=changed))
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,stage)

    def test_compact_prefix_rejects_lost_physical_owner_epoch_or_allocator_but_not_new_stats(self):
        g=self.game(weapon='w.two');f=self.fact(g).intrinsic.weapon_attack
        eid=allocation_from_payload(f.weapon_allocation).entity_id
        for mode in ('missing','owner','allocator'):
            state=g.state
            if mode=='missing':del state.entities[eid]
            elif mode=='owner':state.entities[eid].owner=2
            else:state.next_order=f.next_order-1
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_prefix(f,state,g.registry)
        state=g.state;state.entities[eid].base_attack=9
        validate_prefix(f,state,g.registry)

    def test_rehashed_paid_fact_requires_complete_original_nullable_leaf_and_allocation(self):
        g=self.game(weapon='w.two');self.play(g);saved=self.portable(g)
        for mode in ('missing','none','payer','allocation','type','qualification','quantity'):
            bad=deepcopy(saved);stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f=stage['weapon_attack']
            if mode=='missing':del stage['weapon_attack']
            elif mode=='none':stage['weapon_attack']=None
            elif mode=='payer':f['player_id']=2
            elif mode=='allocation':f['weapon_allocation']=f['weapon_allocation'][:-1]
            elif mode=='type':f['attack']=True
            elif mode=='qualification':f['doomed']=True
            else:f['quantity']+=1
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_ordinary_card_explicit_none_is_required_in_dictionary_and_typed_stage(self):
        g=self.game();stage=capture_generated_quote_fact(g.state,g.registry,1,'card.1').intrinsic
        self.assertIsNone(stage.weapon_attack);wire=json.loads(json.dumps(asdict(stage)));del wire['weapon_attack']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(wire)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(stage);del wire['fields']['weapon_attack']
        with self.assertRaises(ValueError):codec.decode(wire)

    def test_quotes_and_player_views_are_pure_and_hide_original_price_allocation(self):
        g=self.game(weapon='w.two',enemy_hand=(CORSAIR,),enemy_weapon='w.three');before=g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g),2);capture_generated_quote_fact(g.state,g.registry,1,CORSAIR)
            for player in (1,2):
                text=json.dumps(g.observe(player))
                for hidden in ('weapon_allocation','submitted_cost','cost.player-equipped-weapon-attack-v1','player_weapon_attack_cost'):
                    self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_new_schema_rule_and_effect_versions_explicitly_reject_all_old_and_future_layouts(self):
        g=self.game(weapon='w.two');saved=self.portable(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,266))
        for version in (*range(1,218),217,True):
            bad=deepcopy(saved);bad['schema_version']=version
            with self.subTest(version=version),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())


if __name__=='__main__':unittest.main()
