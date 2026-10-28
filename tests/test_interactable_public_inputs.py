"""Existing inert BOARD projection in ordinary original-player inputs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, UseInteractable
from hs_sim.engine.body_target_origin import capture_origin
from hs_sim.engine.model import CardType, Keyword, Zone
from hs_sim.engine.player_target_inputs import (canonical, capture, decode, factory,
    validate_full_state, validate_origin)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from test_interactable_basics import OPEN, OBJECT, BEASTS, registry as rift_registry
from test_player_target_inputs import registry as input_registry


def registry(mode='normal'):
    # Reuse unchanged fixtures; no new body, grant, real card or effect declaration.
    r, donor = input_registry(mode), rift_registry()
    for cid in (OPEN, OBJECT, *BEASTS):
        r.register_card(donor.card(cid))
    for name in ('open.rift', 'use.rift'):
        r.register_behavior(name, donor.behavior(name))
    return r


class InteractablePublicInputTests(unittest.TestCase):
    def game(self, mode='normal', *, actor=1, other_hand='hidden', invest=False):
        own = PlayerSetup('hero', hand=(OPEN, 'unit', 'hidden'), board=('tiny', 'big'),
            mana=10, max_mana=10, deck=('hidden',)*4)
        enemy = PlayerSetup('hero', hand=(other_hand,), board=('tiny', 'big'),
            mana=10, max_mana=10, deck=('hidden',)*4)
        g = Game.from_scenario(Scenario((own, enemy) if actor == 1 else (enemy, own),
            active_player=actor, seed=79), registry(mode))
        g.apply(PlayCard(actor, g.state.players[actor].hand[0]))
        if invest:
            owner = g.state.players[actor]
            obj = next(i for i in owner.board if g.state.entities[i].card_id == OBJECT)
            held = next(i for i in owner.hand if g.state.entities[i].card_id == 'hidden')
            g.apply(UseInteractable(actor, obj, held))
        return g

    def source(self, g):
        p = g._state.players[g._state.active_player]
        return next(g._state.entities[i] for i in p.hand if g._state.entities[i].card_id == 'unit')

    def inputs(self, g):
        source = self.source(g)
        proof = capture(g, g._state, source)
        origin = capture_origin(g._state, source, g.state_hash(), proof)
        return source, proof, origin

    def object_row(self, value):
        return next(row for p in value['players'] for row in p['board'] if row['card_id'] == OBJECT)

    def command(self, g):
        port = g.for_player(g.state.active_player)
        view = port.observe()['observation']
        card = next(c['ref'] for c in view['players'][port.viewer-1]['hand'] if c['card_id']=='unit')
        q = port.independent_targets(card)
        self.assertIsNone(q['error'])
        route = q['choices'][0]
        self.assertEqual(len(route['bodies']), 1)  # One ordinary printed battlecry, no granted combo.
        return {'revision': q['revision'], 'action': {'type':'play_card', 'card':route['card'],
            'target':route['root_targets'][0], 'position':None, 'body_targets':[
                {'body':b['body'], 'target':b['targets'][0]} for b in route['bodies']]}}

    def paid(self, g):
        result = g.for_player(g.state.active_player).submit(self.command(g))
        self.assertTrue(result['accepted'], result.get('error'))
        self.assertFalse(g.state.combo_history)

    def portable(self, g, mode='normal'):
        snap = json.loads(json.dumps(g.snapshot()))
        for other in (g.clone(), Game.from_snapshot(snap, registry(mode)), replay(build_replay(g), registry(mode))):
            self.assertEqual(other.snapshot(), snap)
            self.assertEqual([other.observe(p) for p in (1,2)], [g.observe(p) for p in (1,2)])

    def altered_proof(self, proof, change):
        value = json.loads(proof.observation_json)
        change(value)
        return replace(proof, observation_json=canonical(value))

    def test_existing_unused_carrier_inputs_validate_in_both_active_seats(self):
        for actor in (1, 2):
            g = self.game(actor=actor)
            source, proof, origin = self.inputs(g)
            self.assertEqual(self.object_row(decode(proof))['interactable'], {'used':False, 'uses_per_turn':1})
            validate_origin(g.registry, origin, source, history_state=g._state)
            validate_full_state(g._state, g.registry, source, proof)

    def test_already_used_carrier_remains_valid_original_input_without_hidden_combat_stats(self):
        g = self.game(invest=True)
        source, proof, origin = self.inputs(g)
        row = self.object_row(decode(proof))
        self.assertEqual(set(row), {'ref','card_id','controller','zone','kind','interactable'})
        self.assertEqual(row['interactable'], {'used':True, 'uses_per_turn':1})
        validate_origin(g.registry, origin, source, history_state=g._state)
        validate_full_state(g._state, g.registry, source, proof)

    def test_public_context_is_detached_and_never_exposes_inert_physical_stats(self):
        g = self.game()
        source, proof, _ = self.inputs(g)
        obj = next(i for i in g.state.players[1].board if g.state.entities[i].card_id==OBJECT)
        context = factory(proof)(source.id, obj)
        self.assertEqual(set(context.target), {'ref','card_id','controller','zone','kind','interactable'})
        context.target['interactable']['used'] = True
        self.object_row(context.observation)['interactable']['used'] = True
        self.assertFalse(factory(proof)(source.id, obj).target['interactable']['used'])
        self.assertFalse(hasattr(context, 'state'))

    def test_original_input_rejects_extra_public_combat_or_private_fields_on_carrier(self):
        _, proof, _ = self.inputs(self.game())
        for key, value in (('attack',0),('health',1),('max_health',1),('durability',0),
                ('tribes',None),('keywords',[]),('cost',0),('bodies',[]),('abilities',[])):
            with self.subTest(field=key):
                with self.assertRaises(ValueError):
                    self.altered_proof(proof, lambda v: self.object_row(v).update({key:value}))

    def test_original_input_requires_exact_used_boolean_and_fixed_integer_limit(self):
        _, proof, _ = self.inputs(self.game())
        for value in (None, [], {}, {'used':0,'uses_per_turn':1}, {'used':'false','uses_per_turn':1},
                {'used':False,'uses_per_turn':True}, {'used':False,'uses_per_turn':2},
                {'used':False,'uses_per_turn':1,'receipts':[]}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.altered_proof(proof, lambda v: self.object_row(v).update(interactable=value))

    def test_original_input_rejects_foreign_carrier_identity_kind_controller_or_zone(self):
        _, proof, _ = self.inputs(self.game())
        for field, value in (('card_id',None),('card_id',''),('controller',True),('controller',2),
                ('kind',CardType.WEAPON.value),('zone',Zone.HAND.value)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.altered_proof(proof, lambda v: self.object_row(v).update({field:value}))
        def to_hand(value):
            p = value['players'][0]
            obj = self.object_row(value)
            p['board'].remove(obj)
            p['hand'].append(obj)
            obj['zone'] = Zone.HAND.value
        with self.assertRaises(ValueError):
            self.altered_proof(proof, to_hand)

    def test_normal_minion_cannot_claim_inert_dto_to_omit_its_original_stats(self):
        g = self.game()
        source, proof, origin = self.inputs(g)
        def conceal(value):
            row = value['players'][0]['board'][0]
            kept = {k:row[k] for k in ('ref','card_id','controller','zone','kind')}
            row.clear(); row.update(kept, interactable={'used':False,'uses_per_turn':1})
        forged = self.altered_proof(proof, conceal)
        with self.assertRaisesRegex(ValueError, 'cannot borrow'):
            validate_origin(g.registry, replace(origin, observation=forged), source, history_state=g._state)

    def test_registered_carrier_cannot_drop_the_required_minimal_use_state(self):
        g = self.game()
        source, proof, origin = self.inputs(g)
        forged = self.altered_proof(proof, lambda v:self.object_row(v).pop('interactable'))
        with self.assertRaisesRegex(ValueError, 'exact minimal'):
            validate_origin(g.registry, replace(origin, observation=forged), source, history_state=g._state)

    def test_original_carrier_fact_cannot_become_active_damaged_armed_or_keyworded(self):
        g = self.game()
        source, _, origin = self.inputs(g)
        index = next(i for i,f in enumerate(origin.entities) if f.card_id==OBJECT)
        for fields in ({'active':True}, {'attack':2}, {'health':0,'damage':1},
                {'durability':1}, {'keywords':(Keyword.DIVINE_SHIELD,)}, {'doomed':True}):
            facts = list(origin.entities)
            facts[index] = replace(facts[index], **fields)
            with self.assertRaisesRegex(ValueError, 'ordinary combat facts'):
                validate_origin(g.registry, replace(origin, entities=tuple(facts)), source, history_state=g._state)

    def test_live_full_projection_binds_the_actual_carrier_used_state(self):
        g = self.game(invest=True)
        source, proof, _ = self.inputs(g)
        forged = self.altered_proof(proof, lambda v:self.object_row(v)['interactable'].update(used=False))
        with self.assertRaisesRegex(ValueError, 'complete payment state projection'):
            validate_full_state(g._state, g.registry, source, forged)

    def test_ordinary_paid_input_accepts_existing_unused_carrier_and_restores_receipt(self):
        g = self.game()
        self.paid(g)
        proof = g.state.play_history[-1].body_targets.origin.observation
        self.assertFalse(self.object_row(decode(proof))['interactable']['used'])
        self.assertEqual(g.state.players[1].mana,3)
        self.portable(g)

    def test_ordinary_paid_input_accepts_existing_used_carrier_without_a_second_use(self):
        g = self.game(invest=True)
        self.paid(g)
        proof = g.state.play_history[-1].body_targets.origin.observation
        self.assertTrue(self.object_row(decode(proof))['interactable']['used'])
        self.assertEqual(len(g.state.interactable_history),1)
        self.portable(g)

    def test_inert_object_never_appears_as_an_ordinary_paid_root_or_body_target(self):
        g = self.game()
        port = g.for_player(1)
        view = port.observe()['observation']
        obj = self.object_row(view)['ref']
        source = next(row['ref'] for row in view['players'][0]['hand'] if row['card_id']=='unit')
        q = port.independent_targets(source)
        self.assertIsNone(q['error'])
        for route in q['choices']:
            self.assertNotIn(obj, route['root_targets'])
            for body in route['bodies']:
                self.assertNotIn(obj, body['targets'])

    def test_waiting_resume_clone_restore_and_replay_keep_original_minimal_carrier_row(self):
        g = self.game('wait')
        self.paid(g)
        self.assertIsNotNone(g.state.pending_choice)
        proof = g.state.play_history[-1].body_targets.origin.observation
        self.portable(g,'wait')
        branches = (g.clone(), Game.from_snapshot(g.snapshot(), registry('wait')))
        for current in (g,*branches):
            q = current.state.pending_choice
            current.apply(SelectChoice(q.player_id,q.id,('go',)))
            self.assertEqual(current.state.play_history[-1].body_targets.origin.observation,proof)
            self.portable(current,'wait')
        self.assertTrue(all(current.snapshot()==g.snapshot() for current in branches))

    def test_hidden_enemy_hand_does_not_change_queries_public_outcome_or_events(self):
        a, b = self.game(other_hand='hidden'), self.game(other_hand='big')
        self.assertEqual(self.command(a),self.command(b))
        self.paid(a); self.paid(b)
        for player in (1,):
            self.assertEqual(a.observe(player),b.observe(player))
            self.assertEqual(a.player_events(player),b.player_events(player))

    def test_rehashed_saved_receipt_rejects_inert_private_fields_and_false_original_facts(self):
        g = self.game()
        self.paid(g)
        for mode in ('health','active'):
            saved = deepcopy(g.snapshot())
            receipt = saved['state']['play_history'][-1]['body_targets']
            if mode=='health':
                proof = receipt['origin']['observation']
                value = json.loads(proof['observation_json'])
                self.object_row(value)['health'] = 1
                proof['observation_json'] = canonical(value)
            else:
                fact = next(f for f in receipt['origin']['entities'] if f['card_id']==OBJECT)
                fact['active'] = True
            receipt['origin_hash'] = canonical_hash(receipt['origin'])
            saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
                if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError) as error:
                Game.from_snapshot(saved,registry())
            self.assertNotIn('digest mismatch',str(error.exception))


if __name__ == '__main__':
    unittest.main()
