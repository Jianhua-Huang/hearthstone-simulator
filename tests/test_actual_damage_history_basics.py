"""Original settled damage facts and one isolated Mordresh consumer."""
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, DamageKind,
    DamageRecord, DeckSpec, EndTurn, Game, HealthFlow, HealthLayer, HealthOp, HealthRule,
    Keyword, MatchSetup, PlayCard, PlayerSetup, Rarity, ResolutionError, RewindSpec,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, Zone,
    damage_records, health_result, hero_damage_taken, hero_power_damage, healing_records)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.damage_history import validate_state
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    DamageBatch, Destroy, Draw, Effect, GainArmor, Heal, InvokeBehavior, ReplaceHeroPower,
    RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'BAR_547'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/actual-damage-history-basics.json'
PIN = '55c50055663b956d698eafdafa9b4eb63dd18d0a42134d08e5305c10ea46d1bf'


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or len(packet['records']) != 3:
        raise ValueError('Complete original damage evidence changed')
    for row in packet['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original damage row changed')
    return {row['id']: row['data'] for row in packet['records']}


@dataclass(frozen=True)
class SavedDamage(Effect):
    row: DamageRecord

    def __post_init__(self):
        if type(self.row) is not DamageRecord: raise ValueError('Expected complete original damage row')
        self.row.__post_init__()


def mechanics():
    return default_mechanics('b76-damage-typed-test').register(SavedDamage,
        lambda r, work: (GainArmor(work.row.health_result.target_controller, work.row.health_result.damage_dealt),))


def registry():
    r = opening_registry(); raw = evidence()[NATIVE]
    def native(c):
        if hero_power_damage(c.state, r, c.player_id) < 10: return ()
        enemy = c.state.players[3 - c.player_id]
        targets = (enemy.hero_id,) + tuple(e for e in enemy.board if
            c.state.entities[e].kind is CardType.MINION and c.state.entities[e].active)
        return (DamageBatch(tuple(Damage(e, 10, c.source_id, DamageKind.MINION_ABILITY) for e in targets)),)
    r.register_behavior('damage.native', native)
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry='damage.native', metadata=metadata_from_record(raw)))
    for cid, keywords in (('plain', ()), ('other', ()), ('shield', (Keyword.DIVINE_SHIELD,)),
                          ('immune', (Keyword.IMMUNE,)), ('life', (Keyword.LIFESTEAL,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=10, keywords=keywords))
    r.register_card(CardDefinition('blade', 'Weapon fixture', CardType.WEAPON, attack=3, durability=1))
    hero = lambda c, p=None: c.state.players[c.player_id if p is None else p].hero_id
    body = lambda c, p=1, i=0: c.state.players[p].board[i]
    scripts = {
        'hurt': lambda c: (Damage(hero(c), 5, c.source_id),),
        'two': lambda c: (Damage(hero(c), 2, c.source_id),),
        'batch': lambda c: (DamageBatch((Damage(hero(c), 5, c.source_id),
            Damage(hero(c, 2), 2, c.source_id), Damage(body(c), 3, c.source_id))),),
        'unknown': lambda c: (Damage(hero(c), 5),),
        'zero': lambda c: (Damage(hero(c), 0),),
        'body.hit': lambda c: (Damage(body(c), 5, c.source_id),),
        'body.source': lambda c: (Damage(hero(c, 2), 2, body(c)),),
        'other.source': lambda c: (Damage(hero(c), 2, body(c, 2)),),
        'heal': lambda c: (Heal(hero(c), 5, c.source_id),),
        'grow': lambda c: (Buff(hero(c), health=5),),
        'armor': lambda c: (GainArmor(c.player_id, 5),),
        'transfer.source': lambda c: (ChangeControl(body(c), 2),),
        'transform.source': lambda c: (Transform(body(c), 'other'),),
        'destroy.source': lambda c: (Destroy(body(c), c.source_id),),
        'transform.target': lambda c: (Transform(body(c), 'other'),),
        'transfer.target': lambda c: (ChangeControl(body(c), 2),),
        'bounce.target': lambda c: (ReturnToHand(body(c)),),
        'stale': lambda c: (ReturnToHand(body(c)), Damage(body(c), 5, c.source_id)),
        'replace.power': lambda c: (ReplaceHeroPower(c.player_id, 'power.10'),),
        'fatigue': lambda c: (Draw(c.player_id, 9),),
        'enable': lambda c: (Summon(c.player_id, 'damage.to.heal'),),
        'wait': lambda c: (Damage(hero(c), 5, c.source_id, on_result='damage.wait'),),
        'fail': lambda c: (Damage(hero(c), 5, c.source_id), AddToHand(c.player_id, 'unknown.damage.card')),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    for amount in (9, 10):
        cid = 'power.' + str(amount)
        r.register_behavior(cid, lambda c, n=amount: (Damage(hero(c, 3 - c.player_id), n, c.source_id),))
        r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=2, on_use=cid))
    r.register_behavior('power.wait', lambda c: (Damage(hero(c, 3-c.player_id), 1, c.source_id, on_result='damage.wait'),))
    r.register_card(CardDefinition('power.wait', 'Waiting power', CardType.HERO_POWER, cost=2, on_use='power.wait'))
    r.register_behavior('damage.wait', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('accept', 'Accept', (SavedDamage(c.state.damage_history[-1]),)),
        ChoiceOption('fault', 'Failure probe', (InvokeBehavior('damage.choice.fail', c.source_id, c.player_id),)),
    ), c.source_id),))
    r.register_behavior('damage.choice.fail', lambda c: (AddToHand(c.player_id, 'unknown.damage.choice'),))
    r.register_behavior('retry.hit', lambda c: (Damage(hero(c), 5, c.source_id),))
    r.register_card(CardDefinition('retry.hit', 'Damage retry', CardType.SPELL,
        on_play='retry.hit', keywords=(Keyword.REWIND,), rewind=RewindSpec()))
    r.register_behavior('damage.inspect', lambda c: () if (
        c.state.entities[c.event.source_id].card_id != 'batch' or
        len(damage_records(c.state)) == 3 and hero_damage_taken(c.state, 1) == 5
    ) else (_ for _ in ()).throw(ResolutionError('First event missed complete settled damage batch')))
    r.register_card(CardDefinition('watch', 'First event capture probe', CardType.MINION,
        health=4, triggers=(TriggerSpec('damage_dealt', 'damage.inspect'),)))
    for cid, flow, op in (('prevent', HealthFlow.DAMAGE, HealthOp.PREVENT),
                         ('heal.to.damage', HealthFlow.HEALING, HealthOp.CONVERT),
                         ('damage.to.heal', HealthFlow.DAMAGE, HealthOp.CONVERT)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=4,
            health_rules=(HealthRule(flow, op, source_relation='friendly', layer=HealthLayer.SOURCE),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class ActualDamageTests(unittest.TestCase):
    def game(self, hand=(), *, board=('plain',), enemy=('plain',), enemy_hand=(), armor=0,
             power=None, weapon=None, typed=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, armor=armor, mana=10, max_mana=10,
                        hero_power_card_id='mage.power' if power is None else power,
                        weapon_card_id=weapon, deck=('card.1',)*8),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy, hero_power_card_id='warrior.power',
                        mana=10, max_mana=10, deck=('card.1',)*8)),
            seed=76), registry(), mechanics=mechanics() if typed else None)

    def play(self, g, cid):
        p = g.state.active_player
        source = next(e for e in g.state.players[p].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(p, source)); return source

    def rows(self, g): return damage_records(g.state)
    def check(self, g, *, typed=False):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry(), mechanics=mechanics() if typed else None).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(), mechanics=mechanics() if typed else None).snapshot(), saved)

    def reject(self, saved):
        with self.assertRaises(SnapshotError) as err: Game.from_snapshot(rehash(saved), registry())
        self.assertNotIn('digest mismatch', str(err.exception))

    def test_native_full_raw_pin_metadata_and_evidence_only_other_cards(self):
        raw = evidence()[NATIVE]; card = registry().card(NATIVE)
        self.assertEqual((raw['cost'], raw['attack'], raw['health'], raw['tags']['CARDRACE']), (8, 8, 8, 11))
        self.assertEqual((card.cost, card.attack, card.health), (8, 8, 8))
        self.assertEqual(card.metadata, metadata_from_record(raw))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.tribes), ((CardClass.MAGE,), Rarity.LEGENDARY, ('undead',)))
        self.assertIn('10 damage', raw['text_en'])
        for cid in ('TTN_462', 'TRL_316'):
            with self.assertRaises(UnsupportedDefinitionError): registry().card(cid)

    def test_native_thirty_slot_experimental_constructed_fixture(self):
        r = registry(); own = tuple(f'card.{i}' for i in range(1,30)) + (NATIVE,)
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero','mage.power',CardClass.MAGE,own),
            DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,tuple(f'card.{i}' for i in range(1,31)))),
            policy(r), 'coin', 76, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30,30))
        self.assertEqual((self.rows(g), hero_power_damage(g.state,r,1)), ((),0))

    def test_initial_health_healing_armor_and_growth_are_not_damage(self):
        g = self.game(('heal','armor','grow'))
        for cid in ('heal','armor','grow'): self.play(g,cid)
        self.assertEqual((self.rows(g), g.state.next_damage_id, hero_damage_taken(g.state,1)), ((),1,0)); self.check(g)

    def test_armor_counts_received_damage_separately_from_lost_health(self):
        g = self.game(('hurt',), armor=3); self.play(g,'hurt'); row = self.rows(g)[0].health_result
        self.assertEqual((row.damage_dealt,row.armor_absorbed,row.health_lost), (5,3,2))
        self.assertEqual(hero_damage_taken(g.state,1,own_turn_only=True,turn=1),5); self.check(g)

    def test_complete_original_batch_payload_order_and_target_scope(self):
        g = self.game(('batch',),armor=3); self.play(g,'batch'); rows=self.rows(g)
        self.assertEqual([r.result for r in rows], [health_result(e).payload() for e in g.events if e.kind=='health_resolved'])
        self.assertEqual([r.id for r in rows], [1,2,3])
        self.assertEqual([r.health_result.packet_index for r in rows], [1,2,3])
        self.assertEqual(len({r.health_result.batch_id for r in rows}),1)
        self.assertEqual((hero_damage_taken(g.state,1),hero_damage_taken(g.state,2)),(5,2))
        self.assertEqual(damage_records(g.state,target_kind=CardType.MINION), (rows[2],))
        self.assertEqual(damage_records(g.state,before_id=2), (rows[0],)); self.check(g)

    def test_own_turn_uses_original_active_player_and_target_not_source(self):
        g=self.game(('other.source',),enemy_hand=('other.source',));self.play(g,'other.source')
        g.apply(EndTurn(1));g.apply(UseHeroPower(2,g.state.players[2].hero_power_id))
        self.assertEqual((hero_damage_taken(g.state,1),hero_damage_taken(g.state,1,own_turn_only=True)),(3,2))
        self.assertEqual((hero_damage_taken(g.state,1,turn=1),hero_damage_taken(g.state,1,turn=2)),(2,1))
        self.assertEqual((self.rows(g)[0].health_result.source_controller,self.rows(g)[0].health_result.active_player),(2,1));self.check(g)

    def test_zero_immunity_shield_and_rule_prevention_keep_zero_rows(self):
        for hand,board,prevention in ((('zero',),('plain',),'zero_damage'),(('body.hit',),('immune',),'immune'),
                (('body.hit',),('shield',),'divine_shield'),(('hurt',),('plain','prevent'),'rule_prevention')):
            with self.subTest(prevention=prevention):
                g=self.game(hand,board=board);self.play(g,hand[0]);row=self.rows(g)[0].health_result
                self.assertEqual((row.prevention,row.damage_dealt),(prevention,0));self.check(g)

    def test_damage_converted_to_healing_keeps_fact_with_zero_damage_units(self):
        g=self.game(('hurt','enable','two'));self.play(g,'hurt');self.play(g,'enable');self.play(g,'two')
        row=self.rows(g)[-1].health_result
        self.assertEqual((row.original_flow,row.flow,row.converted,row.damage_dealt,row.healed),('damage','healing',True,0,2))
        self.assertEqual(hero_damage_taken(g.state,1),5);self.assertEqual(len(healing_records(g.state)),1);self.check(g)

    def test_healing_converted_to_damage_is_counted_by_final_actual_units(self):
        g=self.game(('heal',),board=('plain','heal.to.damage'));self.play(g,'heal');row=self.rows(g)[0].health_result
        self.assertEqual((row.original_flow,row.flow,row.converted,row.damage_dealt,row.healed),('healing','damage',True,5,0))
        self.assertEqual((hero_damage_taken(g.state,1),len(healing_records(g.state))),(5,1));self.check(g)

    def test_lifesteal_healing_does_not_duplicate_original_damage(self):
        g=self.game(('hurt','body.source'),board=('life',));self.play(g,'hurt');self.play(g,'body.source')
        self.assertEqual([r.health_result.damage_dealt for r in self.rows(g)],[5,2])
        self.assertEqual((len(healing_records(g.state)),healing_records(g.state)[0].health_result.healed),(1,2));self.check(g)

    def test_stale_target_skip_does_not_create_a_damage_occurrence(self):
        g=self.game(('stale',));self.play(g,'stale')
        self.assertEqual((self.rows(g),g.state.next_damage_id),((),1));self.check(g)

    def test_unknown_positive_source_is_explicit_but_target_scope_is_available(self):
        g=self.game(('unknown',));self.play(g,'unknown')
        self.assertEqual(hero_damage_taken(g.state,1),5)
        for fn in (lambda:damage_records(g.state,source_player=1),lambda:hero_power_damage(g.state,g.registry,1)):
            with self.assertRaises(UnsupportedDefinitionError):fn()
        self.assertEqual(damage_records(g.state,source_player=1,target_player=2),())
        self.assertEqual(damage_records(g.state,source_player=1,turn=2),());self.check(g)

    def test_unknown_zero_source_is_not_guessed_as_hero_power_credit(self):
        g=self.game(('zero',));self.play(g,'zero')
        self.assertEqual((hero_power_damage(g.state,g.registry,1),damage_records(g.state,source_player=1)),(0,()));self.check(g)

    def test_known_systemic_fatigue_counts_received_damage_without_source_credit(self):
        g=self.game(('fatigue',));self.play(g,'fatigue');row=self.rows(g)[0].health_result
        self.assertEqual((row.damage_kind,row.source_id,hero_damage_taken(g.state,1)),('fatigue',None,1))
        self.assertEqual((hero_damage_taken(g.state,1,own_turn_only=True),hero_power_damage(g.state,g.registry,1)),(1,0))
        self.assertEqual(damage_records(g.state,source_player=1),());self.check(g)

    def test_hero_power_credit_uses_original_card_kind_not_damage_kind(self):
        g=self.game();g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));row=self.rows(g)[0].health_result
        self.assertEqual(row.damage_kind,DamageKind.EFFECT.value)
        self.assertEqual((hero_power_damage(g.state,g.registry,1),hero_power_damage(g.state,g.registry,2)),(1,0));self.check(g)

    def test_spell_and_minion_damage_do_not_increase_hero_power_credit(self):
        g=self.game(('batch','body.source'));self.play(g,'batch');self.play(g,'body.source')
        self.assertEqual(hero_power_damage(g.state,g.registry,1),0);self.check(g)

    def test_replacement_and_later_turn_retain_old_power_source_and_units(self):
        g=self.game(('replace.power',));old=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,old));self.play(g,'replace.power')
        self.assertEqual((self.rows(g)[0].health_result.source_id,self.rows(g)[0].health_result.source_card_id),(old,'mage.power'))
        self.assertNotEqual(g.state.players[1].hero_power_id,old)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual((hero_power_damage(g.state,g.registry,1),hero_power_damage(g.state,g.registry,1,turn=1)),(11,1));self.check(g)

    def test_native_exact_threshold_and_ordinary_aoe_with_one_payment(self):
        for amount in (9,10):
            with self.subTest(amount=amount):
                g=self.game((NATIVE,),enemy=('plain','shield'),power='power.'+str(amount));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g,NATIVE)
                self.assertEqual(g.state.players[1].mana,0)
                self.assertEqual(hero_power_damage(g.state,g.registry,1),amount)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30-amount-(10 if amount==10 else 0))
                self.assertEqual(len(g.state.players[2].board),1 if amount==10 else 2)
                self.assertEqual((g.state.entities[g.state.players[1].board[-1]].attack,g.state.entities[g.state.players[1].board[-1]].health),(8,8));self.check(g)

    def test_native_player_command_remains_ordinary_minion_play(self):
        g=self.game((NATIVE,),power='power.10');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        source=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==NATIVE)
        self.assertIn(PlayCard(1,source,position=len(g.state.players[1].board)),g.legal_actions());self.play(g,NATIVE);self.check(g)

    def test_source_lifecycle_preserves_original_card_controller_and_physical_id(self):
        g=self.game(('body.source','transform.source','transfer.source'));source=g.state.players[1].board[0]
        self.play(g,'body.source');original=self.rows(g)[0];self.play(g,'transform.source');self.play(g,'transfer.source')
        self.assertEqual(self.rows(g)[0],original)
        self.assertEqual((original.health_result.source_id,original.health_result.source_card_id,original.health_result.source_controller),(source,'plain',1));self.check(g)

    def test_target_lifecycle_preserves_original_target_card_and_owner(self):
        g=self.game(('body.hit','transform.target','transfer.target'));target=g.state.players[1].board[0]
        self.play(g,'body.hit');original=self.rows(g)[0];self.play(g,'transform.target');self.play(g,'transfer.target')
        self.assertEqual(self.rows(g)[0],original)
        self.assertEqual((original.health_result.target_id,original.health_result.target_card_id,original.health_result.target_controller),(target,'plain',1));self.check(g)

    def test_death_and_bounce_do_not_remove_committed_history(self):
        for later in ('destroy.source','bounce.target'):
            with self.subTest(later=later):
                g=self.game(('body.hit',later));self.play(g,'body.hit');old=self.rows(g);self.play(g,later)
                self.assertEqual(self.rows(g),old);self.check(g)

    def test_first_original_event_capture_sees_complete_damage_batch(self):
        g=self.game(('batch',),board=('plain','watch'));self.play(g,'batch')
        self.assertEqual(len(self.rows(g)),3);self.check(g)

    def test_transaction_failure_rolls_back_history_and_original_numbers(self):
        g=self.game(('fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_typed_damage_waiting_restoration_and_choice_continuation(self):
        g=self.game(('wait',),typed=True);self.play(g,'wait');self.check(g,typed=True)
        for branch in (g.clone(),Game.from_snapshot(g.snapshot(),registry(),mechanics=mechanics()),
                       replay(build_replay(g),registry(),mechanics=mechanics())):
            q=branch.state.pending_choice;branch.apply(SelectChoice(q.player_id,q.id,('accept',)))
            self.assertEqual((len(self.rows(branch)),branch.state.entities[branch.state.players[1].hero_id].armor),(1,5));self.check(branch,typed=True)

    def test_hero_power_waiting_preserves_original_source_credit(self):
        g=self.game(power='power.wait',typed=True);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.check(g,typed=True)
        self.assertEqual(hero_power_damage(g.state,g.registry,1),1)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('accept',)))
        self.assertEqual(hero_power_damage(g.state,g.registry,1),1);self.check(g,typed=True)

    def test_waiting_failure_preserves_exact_committed_boundary(self):
        g=self.game(('wait',),typed=True);self.play(g,'wait');before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),before)

    def test_real_rewind_retires_damage_attempt_and_reuses_logical_cursor(self):
        g=self.game(('retry.hit',));self.play(g,'retry.hit');first=self.rows(g)[0].health_result.batch_id;self.check(g)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('retry',)))
        self.assertEqual((len(self.rows(g)),self.rows(g)[0].id,hero_damage_taken(g.state,1),g.state.next_damage_id),(1,1,5,2))
        self.assertGreater(self.rows(g)[0].health_result.batch_id,first);self.check(g)

    def test_frozen_typed_result_keeps_full_original_payload(self):
        g=self.game(('batch',));self.play(g,'batch');row=self.rows(g)[0];codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(row)))),row)
        with self.assertRaises(FrozenInstanceError):row.id=9
        with self.assertRaises(ValueError):replace(row,id=True)
        with self.assertRaises(ValueError):replace(row,result=tuple(reversed(row.result)))

    def test_original_nested_floor_plan_roundtrips_and_rejects_missing_fields(self):
        from test_v146_health_floor import registry as floor_registry
        r=floor_registry();g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('heal',),mana=10,max_mana=10),
            PlayerSetup('hero',board=('convert_h','self'))),seed=76),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0],g.state.players[2].board[-1]));row=self.rows(g)[0]
        self.assertIsNotNone(row.health_result.floor_plan)
        codec=FrameCodec(g.mechanics,r);self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(row)))),row)
        self.assertEqual(Game.from_snapshot(g.snapshot(),floor_registry()).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),floor_registry()).snapshot(),g.snapshot())
        saved=json.loads(json.dumps(g.snapshot()));next(pair for pair in saved['state']['damage_history'][0]['result'] if pair[0]=='floor_plan')[1].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),floor_registry())

    def test_original_nested_split_packet_keeps_exact_unit_links(self):
        from test_v155_whole_budget_split import expanded_registry
        r=expanded_registry();g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('hurt','convert_split'),mana=10,max_mana=10),PlayerSetup('hero')),seed=76),r)
        self.play(g,'hurt');self.play(g,'convert_split');rows=self.rows(g)
        self.assertEqual([row.health_result.split_packet.index for row in rows if row.health_result.split_packet is not None],[1,2,3])
        self.assertEqual([row.health_result.damage_dealt for row in rows[-3:]],[0,0,0])
        self.assertEqual(Game.from_snapshot(g.snapshot(),expanded_registry()).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),expanded_registry()).snapshot(),g.snapshot())
        saved=json.loads(json.dumps(g.snapshot()));link=next(pair for pair in saved['state']['damage_history'][-1]['result'] if pair[0]=='split_packet')[1]
        next(pair for pair in link if pair[0]=='index')[1]=True
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),expanded_registry())

    def test_original_combat_weapon_identity_survives_durability_destruction(self):
        g=self.game(weapon='blade');weapon=g.state.players[1].weapon_id;g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        row=self.rows(g)[0].health_result
        self.assertEqual((row.weapon_id,row.damage_kind,row.damage_dealt),(weapon,'combat',3))
        self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD);self.check(g)
        saved=json.loads(json.dumps(g.snapshot()));next(pair for pair in saved['state']['damage_history'][0]['result'] if pair[0]=='weapon_zone_epoch')[1]=99999;self.reject(saved)

    def test_saved_cursor_order_clock_and_numeric_types_are_strict(self):
        g=self.game(('batch',));self.play(g,'batch')
        for field,value in (('id',True),('action',2.0),('action',99999)):
            saved=g.snapshot();saved['state']['damage_history'][0][field]=value;self.reject(saved)
        for value in (1,True,4.0):
            saved=g.snapshot();saved['state']['next_damage_id']=value;self.reject(saved)
        saved=g.snapshot();saved['state']['damage_history'].reverse();self.reject(saved)

    def test_complete_result_payload_and_allocation_are_required(self):
        g=self.game(('batch',));self.play(g,'batch')
        for mode in ('missing','duplicate','reverse','amount','identity','turn','flow'):
            with self.subTest(mode=mode):
                saved=json.loads(json.dumps(g.snapshot()));result=saved['state']['damage_history'][0]['result']
                if mode=='missing':result.pop()
                elif mode=='duplicate':result.append(deepcopy(result[0]))
                elif mode=='reverse':result.reverse()
                else:
                    name,value={'amount':('damage_dealt',True),'identity':('target_id',99999),'turn':('turn',99),'flow':('original_flow','unknown')}[mode]
                    next(pair for pair in result if pair[0]==name)[1]=value
                self.reject(saved)

    def test_rehashed_omission_and_changed_original_attribution_are_rejected(self):
        g=self.game(('batch',));self.play(g,'batch');saved=g.snapshot();saved['state']['damage_history']=[];saved['state']['next_damage_id']=1;self.reject(saved)
        for name,value in (('source_controller',2),('source_card_id','unknown.damage.source'),('source_zone_epoch',99999),
                           ('target_entered_order',g.state.next_order),('original_target_id',99999)):
            saved=json.loads(json.dumps(g.snapshot()));next(pair for pair in saved['state']['damage_history'][0]['result'] if pair[0]==name)[1]=value;self.reject(saved)

    def test_schema_and_required_history_fields_are_strict(self):
        g=self.game();saved=g.snapshot()
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,266))
        for value in (*range(1,218),217,True,216.0):
            changed=deepcopy(saved);changed['schema_version']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(changed,registry())
        for field in ('damage_history','next_damage_id'):
            changed=deepcopy(saved);del changed['state'][field];self.reject(changed)

    def test_queries_are_strict_pure_and_private_for_both_players(self):
        g=self.game(('batch',));self.play(g,'batch');before=g.snapshot()
        for _ in range(3):
            self.assertEqual(hero_damage_taken(g.state,1),5)
            for p in (1,2):
                view=json.dumps(g.observe(p))
                for private in ('damage_history','next_damage_id','HealthResult','health_resolved'):self.assertNotIn(private,view)
        self.assertEqual(g.snapshot(),before)
        for kw in ({'source_player':True},{'target_player':1.0},{'target_kind':'HERO'},{'target_kind':CardType.SPELL},
                   {'turn':0},{'turn':True},{'before_id':1.0},{'target_own_turn':True},{'target_own_turn':1}):
            with self.assertRaises(ValueError):damage_records(g.state,**kw)
        for p in (None,True,1.0,0,3):
            with self.assertRaises(ValueError):hero_damage_taken(g.state,p)
            with self.assertRaises(ValueError):hero_power_damage(g.state,g.registry,p)
        with self.assertRaises(ValueError):hero_damage_taken(g.state,1,own_turn_only=1)
        invalid=deepcopy(g.state);invalid.next_damage_id=True
        with self.assertRaises(ValueError):validate_state(invalid,g.registry)
