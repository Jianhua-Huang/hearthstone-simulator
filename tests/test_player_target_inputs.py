"""Real paid DTO predicates, original inputs, retries and player isolation."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, EndTurn, Game, GrantCombo, PlayCard,
    PlayerSetup, PlayerTargetRuleSpec, Registry, Scenario, SelectChoice, SnapshotError, Keyword,
    TargetMode, TargetSpec, Zone)
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, GainArmor, RandomDamage, RequestChoice, Summon
from hs_sim.engine.model import CardClass, CardMetadata, PaidTargetObservation
from hs_sim.engine.player_api import UnsupportedPlayerRule, context_factory
from hs_sim.engine.player_target_inputs import canonical, factory, validate_full_state
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
import examples.paid_body_retry as retry_fixture


FRIEND = TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,), 'friendly')
ENEMY = replace(FRIEND, relation='enemy')


def registry(mode='normal', *, version='v1', calls=None):
    r = Registry('player-target-inputs-' + mode)
    def condition(c):
        if calls is not None: calls.append((c.source['card_id'], c.target['card_id']))
        assert not hasattr(c, 'state') and not hasattr(c, 'target_id')
        if mode == 'bool': return 1
        if mode == 'raise': raise ValueError('deliberately invalid callback')
        if mode in ('blind', 'blind_rejected'): return c.target['zone'] == 'hand'
        own = c.observation['players'][c.player_id - 1]
        valid = c.target['health'] <= (own['mana'] if mode == 'mana' else 4)
        if mode == 'mutate':
            c.target['health'] = 999
            c.source['health'] = 999
            own['mana'] = 999
        return valid
    if mode == 'unconnected':
        r.register_target_rule('visible', condition, visibility='player')
    else:
        r.register_player_target_rule(PlayerTargetRuleSpec('visible', version), condition)
    plain = CardMetadata(collectible=False, classes=(CardClass.NEUTRAL,), rarity=None, tribes=())
    r.register_body_target_profile(BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment'))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=50, metadata=plain))
    for name, hp in (('tiny', 3), ('big', 6)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=hp, metadata=plain))
    r.register_card(CardDefinition('hidden', 'Hidden', CardType.SPELL, metadata=plain))
    def first(c):
        effects = [GainArmor(c.player_id, 1)]
        if mode == 'change': effects.append(Buff(c.target_id, health=8, source_id=c.source_id))
        if mode == 'wait':
            return [RequestChoice(c.player_id, (ChoiceOption('go', 'Continue', tuple(effects)),), c.source_id)]
        return effects
    def second(c):
        if mode == 'fail':
            return [RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), Summon(c.player_id, 'unsupported.target.body')]
        return [Damage(c.target_id, 1, c.source_id)]
    r.register_behavior('first', first)
    r.register_behavior('second', second)
    r.register_behavior('ordinary', lambda c: [Damage(c.target_id, 1, c.source_id)]
        if c.state.entities[c.target_id].zone == Zone.BOARD else [GainArmor(c.player_id, 1)])
    domain = (TargetSpec(TargetMode.REQUIRED, (Zone.HAND,),
        (CardType.MINION,) if mode == 'blind_rejected' else
        (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO), 'enemy')
        if mode in ('blind', 'blind_rejected') else FRIEND)
    r.register_card(CardDefinition('unit', 'Carrier', CardType.MINION, cost=2, health=6,
        on_play='ordinary', battlecry='first', targeting=domain, target_rule='visible', metadata=plain))
    r.register_card(CardDefinition('donor', 'Combo body', CardType.MINION, health=6,
        combo='second', targeting=domain, target_rule='visible', keywords=(Keyword.COMBO,), metadata=plain))
    for name, family in (('unit', 'battlecry'), ('donor', 'combo')):
        r.register_body_target_binding(BodyTargetBinding(name, family, 'paid', carrier_card_ids=('unit',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'explicit_root',
        domain if mode in ('blind', 'blind_rejected') else ENEMY, 'visible'))
    r.register_card(CardDefinition('empty', 'Empty route', CardType.MINION, cost=2, health=6,
        on_play='ordinary', targeting=ENEMY, target_rule='visible', metadata=plain))
    r.register_body_root_target_binding(BodyRootTargetBinding('empty', 'paid', 'preserve_root'))
    def setup(c):
        source = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == 'unit')
        return [GrantCombo(BodyReference.capture(source), 'donor', c.source_id)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup', metadata=plain))
    return r


def game(mode='normal', *, setup=True, empty=False, enemy_hand='hidden', calls=None):
    g = Game.from_scenario(Scenario((
        PlayerSetup('hero', hand=('empty',) if empty else ('setup', 'unit'), board=('tiny', 'big'), mana=6, max_mana=6),
        PlayerSetup('hero', board=('tiny', 'big'), hand=(enemy_hand,), mana=6, max_mana=6)), seed=23), registry(mode, calls=calls))
    if setup and not empty: g.apply(PlayCard(1, g.state.players[1].hand[0]))
    return g


def command(g, *, name='unit', target_card=None):
    port = g.for_player(1)
    view = port.observe()['observation']
    card = next(c['ref'] for c in view['players'][0]['hand'] if c['card_id'] == name)
    q = port.independent_targets(card)
    if q['error'] is not None: return q
    route = q['choices'][0]
    target_refs = {c['card_id']: c['ref'] for c in view['players'][0]['board']}
    action = {'type': 'play_card', 'card': route['card'], 'target': route['root_targets'][0],
        'position': None, 'body_targets': [{'body': b['body'],
            'target': target_refs[target_card] if target_card is not None else b['targets'][0]} for b in route['bodies']]}
    if not route['bodies']: action['body_route'] = route['body_route']
    return {'revision': q['revision'], 'action': action}


def retry_registry(mode='normal'):
    r = retry_fixture.registry(mode)
    r.register_player_target_rule(PlayerTargetRuleSpec('visible', 'retry-v1'),
        lambda c: c.target is not None and c.observation['players'][c.player_id - 1]['mana'] >= 0)
    for name in retry_fixture.FACES:
        r._cards[name] = replace(r.card(name), target_rule='visible')
        key = (name, 'paid')
        r._body_root_target_bindings[key] = replace(r._body_root_target_bindings[key], target_rule='visible')
    return r


class PlayerTargetInputTests(unittest.TestCase):
    def paid(self, g, **kwargs):
        result = g.for_player(1).submit(command(g, **kwargs))
        self.assertTrue(result['accepted'], result.get('error'))

    def check(self, g, mode='normal', *, retry_mode=None):
        make = (lambda: retry_registry(retry_mode)) if retry_mode is not None else (lambda: registry(mode))
        snap = g.snapshot()
        for other in (Game.from_snapshot(snap, make()), g.clone(), replay(build_replay(g), make())):
            self.assertEqual(other.snapshot(), snap)
            self.assertEqual([other.for_player(p).observe() for p in (1, 2)], [g.for_player(p).observe() for p in (1, 2)])

    def reject_observation(self, g, mutate):
        snap = g.snapshot(); receipt = snap['state']['play_history'][-1]['body_targets']
        observed = receipt['origin']['observation']
        value = json.loads(observed['observation_json'])
        mutate(value, observed)
        observed['observation_json'] = canonical(value)
        receipt['origin_hash'] = canonical_hash(receipt['origin'])
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(snap, registry())
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_rule_registration_requires_exact_immutable_identity_and_version(self):
        for args in (('', 'v1'), ('ok', ''), ('ok', True)):
            with self.assertRaises(ValueError): PlayerTargetRuleSpec(*args)
        r = registry()
        with self.assertRaises(ValueError): r.register_player_target_rule({'id': 'x'}, lambda c: True)
        with self.assertRaises(ValueError): r.register_player_target_rule(PlayerTargetRuleSpec('visible','v2'), lambda c: True)
        r.freeze()
        with self.assertRaises(ValueError): r.register_player_target_rule(PlayerTargetRuleSpec('later','v1'), lambda c: True)

    def test_original_rule_version_changes_fingerprint_and_refuses_old_inputs(self):
        g=game(); self.paid(g)
        self.assertNotEqual(registry().fingerprint(), registry(version='v2').fingerprint())
        with self.assertRaises(SnapshotError): Game.from_snapshot(g.snapshot(), registry(version='v2'))

    def test_unconnected_legacy_player_callbacks_are_not_implicitly_authorized(self):
        g=game('unconnected',setup=False)
        before=g.snapshot()
        self.assertEqual(command(g)['error'], 'unsupported_rule')
        self.assertEqual(g.snapshot(),before)

    def test_grant_authority_does_not_execute_player_predicates(self):
        calls=[]; g=game(setup=False,calls=calls)
        before=len(calls)
        g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertEqual(len(calls),before)
        self.assertEqual(len([a for a in g.state.entities[g.state.players[1].hand[0]].abilities if a.kind=='combo']),1)

    def test_paid_root_and_two_bodies_capture_independent_player_candidates(self):
        g=game(); before=g.snapshot(); q=command(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(len(q['action']['body_targets']),2)
        self.paid(g)
        play=g.state.play_history[-1]
        self.assertEqual([r.failure for r in (*g.state.battlecry_history,*g.state.combo_history)], [None,None])
        self.assertEqual(g.state.players[1].mana,4)
        observation=json.loads(play.body_targets.origin.observation.observation_json)
        self.assertEqual(observation['players'][0]['mana'],6)
        self.assertEqual(observation['players'][0]['cards_played_total'],1)
        self.check(g)

    def test_later_body_rechecks_current_target_without_rewriting_original_view(self):
        g=game('change'); self.paid(g)
        self.assertEqual(g.state.combo_history[-1].failure,'invalid_target')
        original=json.loads(g.state.play_history[-1].body_targets.origin.observation.observation_json)
        self.assertEqual(original['players'][0]['board'][0]['health'],3)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,11)
        self.check(g,'change')

    def test_original_mana_predicate_is_retained_but_live_body_uses_after_payment_mana(self):
        g=game('mana'); self.paid(g,target_card='big')
        self.assertEqual([r.failure for r in (*g.state.battlecry_history,*g.state.combo_history)], ['invalid_target','invalid_target'])
        self.assertEqual(g.state.players[1].mana,4)
        original=g.state.play_history[-1].body_targets
        self.assertEqual(len(original.body_choices[0]),2)
        self.assertEqual(json.loads(original.origin.observation.observation_json)['players'][0]['mana'],6)
        self.check(g,'mana')

    def test_each_callback_gets_detached_observation_source_and_target(self):
        g=game('mutate'); self.paid(g)
        self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,2)
        proof=g.state.play_history[-1].body_targets.origin.observation
        c=factory(proof)(g.state.play_history[-1].source_id,g.state.players[1].board[0])
        c.observation['players'][0]['mana']=999
        self.assertEqual(json.loads(proof.observation_json)['players'][0]['mana'],6)
        self.check(g,'mutate')

    def test_waiting_restore_clone_replay_and_resume_keep_same_original_inputs(self):
        g=game('wait'); self.paid(g); self.assertIsNotNone(g.state.pending_choice)
        proof=g.state.play_history[-1].body_targets.origin.observation
        self.check(g,'wait')
        for other in (g.clone(), Game.from_snapshot(g.snapshot(),registry('wait'))):
            choice=other.state.pending_choice
            other.apply(SelectChoice(choice.player_id,choice.id,('go',)))
            self.assertEqual(other.state.play_history[-1].body_targets.origin.observation,proof)
            self.assertEqual(other.state.players[1].mana,4)
            self.check(other,'wait')

    def test_body_failure_rolls_back_payment_rng_inputs_history_and_handles(self):
        g=game('fail'); before=g.snapshot(); history=g.history
        result=g.for_player(1).submit(command(g))
        self.assertFalse(result['accepted']); self.assertEqual(result['error'],'resolution_failed')
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.history,history)

    def test_empty_vector_has_real_player_root_inputs_without_fake_body(self):
        g=game(empty=True); self.paid(g,name='empty')
        play=g.state.play_history[-1]
        self.assertEqual(play.body_targets.selected,()); self.assertIsNotNone(play.body_targets.origin.observation)
        self.assertFalse(g.state.battlecry_history); self.assertFalse(g.state.combo_history)
        self.check(g)

    def test_opposing_hidden_cards_produce_same_queries_and_public_events(self):
        a=game(enemy_hand='hidden'); b=game(enemy_hand='big')
        self.assertEqual(a.for_player(1).observe(),b.for_player(1).observe())
        self.assertEqual(command(a),command(b))
        self.paid(a); self.paid(b)
        self.assertEqual(a.for_player(1).observe(),b.for_player(1).observe())
        self.assertEqual(a.for_player(1).events(),b.for_player(1).events())

    def test_blind_hand_predicate_gets_only_visible_back_and_all_hand_kinds(self):
        a=game('blind'); b=game('blind',enemy_hand='big')
        self.assertEqual(command(a),command(b))
        self.paid(a); proof=a.state.play_history[-1].body_targets.origin.observation
        self.assertEqual(set(json.loads(proof.observation_json)['players'][1]['hand'][0]),{'ref','card_id'})
        self.check(a,'blind')

    def test_hidden_kind_filter_refuses_before_any_callback(self):
        calls=[]; g=game('blind_rejected',setup=False,calls=calls)
        self.assertEqual(command(g)['error'],'unsupported_target_domain')
        self.assertEqual(calls,[])

    def test_observation_inputs_and_physical_map_never_enter_player_json(self):
        g=game('wait'); self.paid(g)
        for p in (1,2):
            raw=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).events())
            for private in ('observation_json','references','original_state_hash','source_json','origin_hash','registry_fingerprint'):
                self.assertNotIn(private,raw)

    def test_rehashed_foreign_viewer_or_turn_cannot_replace_original_inputs(self):
        g=game(); self.paid(g)
        for field,value in (('viewer',2),('turn',2),('active_player',2)):
            self.reject_observation(g,lambda v,o,f=field,n=value:v.update({f:n}))

    def test_rehashed_observed_target_stats_cannot_disagree_with_original_facts(self):
        g=game(); self.paid(g)
        self.reject_observation(g,lambda v,o:v['players'][0]['board'][0].update(health=999))

    def test_rehashed_original_hand_or_board_cannot_drop_or_reorder_members(self):
        g=game(); self.paid(g)
        self.reject_observation(g,lambda v,o:v['players'][0]['hand'].pop())
        self.reject_observation(g,lambda v,o:v['players'][0]['board'].reverse())

    def test_rehashed_future_or_borrowed_physical_reference_is_rejected(self):
        g=game(); self.paid(g)
        self.reject_observation(g,lambda v,o:o['references'][0].__setitem__(0,999999))
        self.reject_observation(g,lambda v,o:o['references'][0].__setitem__(1,o['references'][1][1]))

    def test_rehashed_hidden_hand_attributes_and_engine_data_are_rejected(self):
        g=game(); self.paid(g)
        self.reject_observation(g,lambda v,o:v['players'][1]['hand'][0].update(health=7))
        self.reject_observation(g,lambda v,o:v['players'][0]['hero'].update(abilities=[]))

    def test_rehashed_prior_play_counts_and_mana_crystals_are_rejected(self):
        g=game(); self.paid(g)
        for field in ('max_mana','cards_played_total','cards_played_this_turn'):
            self.reject_observation(g,lambda v,o,f=field:v['players'][0].update({f:999}))

    def test_full_payment_projection_checks_public_resource_and_armor_inputs(self):
        g=game(); state=g._state; source=state.entities[state.players[1].hand[0]]
        from hs_sim.engine.player_target_inputs import capture
        proof=capture(g,state,source)
        for mutate in (lambda v:v['players'][0]['resources'].update(corpses=999),
                       lambda v:v['players'][0]['hero'].update(armor=999)):
            value=json.loads(proof.observation_json); mutate(value)
            changed=replace(proof,observation_json=canonical(value))
            with self.assertRaisesRegex(ValueError,'complete payment state projection'):
                validate_full_state(state,g.registry,source,changed)

    def test_observation_wire_cannot_be_noncanonical_or_missing(self):
        g=game(); self.paid(g); proof=g.state.play_history[-1].body_targets.origin.observation
        with self.assertRaises(ValueError): replace(proof,observation_json=proof.observation_json+' ').__post_init__()
        snap=g.snapshot(); receipt=snap['state']['play_history'][-1]['body_targets']; receipt['origin']['observation']=None
        receipt['origin_hash']=canonical_hash(receipt['origin'])
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap,registry())

    def test_builtin_receipts_do_not_acquire_unnecessary_observation(self):
        from test_target_predicates import game as structural_game, action
        g=structural_game(); g.apply(action(g)[0])
        self.assertIsNone(g.state.play_history[-1].body_targets.origin.observation)

    def test_callback_nonbool_or_exception_cannot_accept_or_change_state(self):
        from hs_sim.engine.errors import ResolutionError
        from hs_sim.engine.targeting import target_choices
        for mode in ('bool','raise'):
            g=game(mode,setup=False); before=g.snapshot()
            state=g.state; source=state.entities[state.players[1].hand[-1]]
            with self.assertRaises(ResolutionError):
                target_choices(state,g.registry,source,g.registry.card('unit'),
                    context_factory=context_factory(g,1))
            self.assertEqual(g.snapshot(),before)

    def test_original_public_input_does_not_embed_past_state_or_event_stream(self):
        g=game(); self.paid(g)
        proof=g.state.play_history[-1].body_targets.origin.observation
        text=proof.observation_json
        for internal in ('play_history','death_history','rng_state','resolution_frame','events','source_json'):
            self.assertNotIn('"'+internal+'"',text)
        self.assertIn('"event_cursor"',text)
        self.assertEqual(len(proof.references),len(set(i for i,ref in proof.references)))

    def test_two_actual_retries_capture_new_faces_and_keep_one_original_view(self):
        g=Game.from_scenario(retry_fixture.scenario(),retry_registry())
        g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertTrue(g.for_player(1).submit(retry_fixture.command(g))['accepted'])
        first=g.state.play_history[-1].body_targets
        for attempt,face in ((1,'face1'),(2,'face2')):
            choice=g.state.pending_choice; g.apply(SelectChoice(choice.player_id,choice.id,('retry',)))
            receipt=g.state.play_history[-1].body_targets
            self.assertEqual(receipt.retry_attempt,attempt); self.assertEqual(receipt.retry_root,first)
            value=json.loads(receipt.origin.observation.observation_json)
            self.assertEqual(value['players'][0]['hand'][0]['card_id'],face)
            self.assertEqual(value['players'][0]['mana'],10); self.assertEqual(g.state.players[1].mana,8)
            self.assertNotEqual(receipt.origin.observation,receipt.retry_root.origin.observation)
        self.check(g,retry_mode='normal')

    def test_retry_waiting_inputs_restore_and_resume_after_original_choice(self):
        g=Game.from_scenario(retry_fixture.scenario(),retry_registry('wait'))
        g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertTrue(g.for_player(1).submit(retry_fixture.command(g))['accepted'])
        choice=g.state.pending_choice; g.apply(SelectChoice(choice.player_id,choice.id,('go',)))
        choice=g.state.pending_choice; g.apply(SelectChoice(choice.player_id,choice.id,('retry',)))
        self.assertEqual(g.state.play_history[-1].body_targets.retry_attempt,1)
        self.check(g,retry_mode='wait')

