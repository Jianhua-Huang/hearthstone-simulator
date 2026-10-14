"""B2-03 accepted physical Deathrattle faces and complete source proofs.

All tribal/condition fixtures are synthetic local contracts, not CN evidence.
This module owns its methods; it does not inherit another TestCase's tests.
"""
import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, EndTurnSpec, Game, Keyword, LaunchStarship, PlayCard, PlayerEffectSpec,
    LimitedTriggerSpec, PlayerSetup, Registry, ResolutionError, Ruleset, RewindSpec, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.model import (AbilityInstance, BattlecryRepeatSpec,
    DeathrattleRecipient, DeathrattleRecipientMetadataFilter,
    ComboRepeatSpec, DeathrattleRepeatMatchSpec, DeathrattleRepeatSpec, EndTurnRepeatSpec,
    EndTurnRequest, EndTurnSelector, RepeatSourceEligibility)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, EquipWeapon, GainArmor, GrantDeathrattle,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Summon,
    Transform, TriggerDeathrattles)
from hs_sim.engine.deathrattle_matching import (capture_recipient_from_state,
    deathrattle_match_from_dict, deathrattle_match_to_dict,
    deathrattle_repeat_recipient_matches, recipient_from_capture)
from hs_sim.engine.deathrattle_repeats import (GrantDeathrattleRepeatAura,
    capture_plan, validate_plan)
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.deathrattles import FinishDeathrattleBatch
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.repeat_source_conditions import (
    qualifying_deathrattle_self_witnesses, qualifying_repeat_witnesses)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def spec(count=2, *, tribes=None, condition=None, scope='friendly',
         origins=('printed', 'granted'), kinds=(CardType.MINION,)):
    recipient = None if tribes is None else DeathrattleRecipientMetadataFilter(
        'accepted_carrier_face_printed', tribes)
    matching = (DeathrattleRepeatMatchSpec(recipient, condition)
        if recipient is not None or condition is not None else None)
    return DeathrattleRepeatSpec(count, kinds, scope, origins, matching)


def condition(*, another=True, tribes=('beast',), profile='repeat.witness.controlled'):
    return RepeatSourceEligibility(profile, tribes, another)


def find(state, name, player=1):
    return next(i for i in state.players[player].board if state.entities[i].card_id == name)


def ask(c, *effects):
    return RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Resolve', tuple(effects)),), source_id=c.source_id)


def fixture_registry():
    r = Registry('deathrattle-matching-public-fixtures-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30,
        metadata=metadata()))
    r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('ten', lambda c: [GainArmor(c.player_id, 10)])
    r.register_behavior('wait', lambda c: [ask(c, GainArmor(c.player_id, 1))])
    r.register_behavior('noop', lambda c: [])
    for name, tribes in (('plain', ()), ('dragon', ('dragon',)), ('beast', ('beast',)),
            ('all', ('all',)), ('multi', ('beast', 'dragon')), ('unknown.tribes', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            metadata=metadata(tribes)))
    r.register_card(CardDefinition('unknown.metadata', 'Unknown', CardType.MINION, health=6))
    r.register_card(CardDefinition('retainer', 'Retainer', CardType.MINION, health=6,
        metadata=metadata(), retain_rewind_outcomes=True))
    for name, tribes, behavior in (('dragon.rattle', ('dragon',), 'armor'),
            ('beast.rattle', ('beast',), 'armor'), ('plain.rattle', (), 'armor'),
            ('dragon.wait', ('dragon',), 'wait'), ('beast.wait', ('beast',), 'wait'),
            ('unknown.rattle', None, 'armor')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            deathrattle=behavior, metadata=metadata(tribes)))
    for name, declaration in (('tribal.source', spec(tribes=('dragon',))),
            ('false.source', spec(5, tribes=('beast',))),
            ('conditional.source', spec(tribes=('dragon',), condition=condition())),
            ('strong.source', spec(3, tribes=('dragon',)))):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            metadata=metadata(), deathrattle_repeats=(declaration,)))
    r.register_card(CardDefinition('weapon', 'Weapon', CardType.WEAPON,
        attack=1, durability=2, metadata=metadata()))
    r.register_card(CardDefinition('weapon.rattle', 'Rattle weapon', CardType.WEAPON,
        attack=1, durability=2, deathrattle='armor'))
    r.register_card(CardDefinition('location.rattle', 'Rattle location', CardType.LOCATION,
        durability=2, on_use='noop', deathrattle='armor'))
    return r


class DeathrattleMatchingTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()
        self.entries = []
        self.script('kill', lambda c: [Destroy(c.target_id, c.source_id)], target=True)
        self.script('trigger', lambda c: [TriggerDeathrattles(c.target_id, c.source_id)], target=True)
        self.script('grant', lambda c: [GrantDeathrattle(c.target_id, 'ten', c.source_id)], target=True)

    def install(self, kind, *values):
        getattr(self.r, 'register_' + kind)(*values)
        self.entries.append((kind, values))

    def fresh(self):
        r = fixture_registry()
        for kind, values in self.entries:
            getattr(r, 'register_' + kind)(*values)
        self.assertEqual(r.fingerprint(), self.r.fingerprint())
        return r

    def behavior(self, name, body):
        self.install('behavior', name, body)

    def minion(self, name, body=None, *, tribes=(), **fields):
        fields.setdefault('health', 6)
        fields.setdefault('metadata', metadata(tribes))
        if body is not None:
            fields['deathrattle'] = body
        self.install('card', CardDefinition(name, name, CardType.MINION, **fields))

    def source(self, name, declaration, **fields):
        self.minion(name, deathrattle_repeats=(declaration,), **fields)

    def script(self, name, body, target=False, **fields):
        self.behavior(name, body)
        fields.setdefault('cost', 1)
        self.install('card', CardDefinition(name, name, CardType.SPELL,
            on_play=name, requires_target=target, metadata=metadata(), **fields))

    def policy(self, name, declarations, *, duration=None, end_repeats=()):
        fields = {} if duration is None else dict(kind='objective', duration=duration, tick_event='turn_ended')
        self.script(name, lambda c: [AddPlayerEffect(c.player_id, name, c.source_id)])
        self.install('player_effect', PlayerEffectSpec(name, name,
            deathrattle_repeats=declarations, end_turn_repeats=end_repeats, **fields))

    def game(self, *, hand=(), board=('dragon.rattle',), enemy=(), enemy_hand=(),
             weapon=None, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',)*14,
                mana=10, max_mana=10, weapon_card_id=weapon),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, deck=('plain',)*14,
                mana=10, max_mana=10)), seed=154), self.r, ruleset=rules)

    def play(self, g, name, target=None, *, position=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(p, eid, target, position=position))
        return eid

    def choose(self, g, option='ok'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def finish(self, g):
        while g.state.pending_choice is not None:
            self.portable(g)
            self.choose(g)
        self.portable(g)

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s, self.fresh()).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), self.fresh()).snapshot(), s)

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def batch(self, g, index=-1):
        return g.state.deathrattle_batches[index]

    def counts(self, g, index=-1):
        return [p.plan.repetitions for p in self.batch(g, index).payloads]

    def nodes(self, value, tail):
        result = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + tail):
                result.append(value)
            for child in value.values():
                result.extend(self.nodes(child, tail))
        elif isinstance(value, list):
            for child in value:
                result.extend(self.nodes(child, tail))
        return result

    def proofs(self, g):
        return [w for w in (*g._frame.prefix, *g._frame.continuation)
            if type(w) is FinishDeathrattleBatch]

    def queue(self, snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    def reject(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, self.fresh())

    def restore_modified(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return Game.from_snapshot(s, self.fresh())

    def edit_ability(self, value, identity, edit):
        """Edit both durable state JSON and typed Frame payloads, counting edits."""
        count = 0
        if isinstance(value, dict):
            fields = value.get('fields') if str(value.get('type', '')).endswith('.AbilityInstance') else value
            if (isinstance(fields, dict) and fields.get('id') == identity
                    and fields.get('kind') == 'deathrattle_repeat'
                    and isinstance(fields.get('deathrattle_repeat'), dict)):
                edit(fields, fields is not value)
                count += 1
            children = fields.values() if isinstance(fields, dict) and fields is not value else value.values()
            for child in children:
                count += self.edit_ability(child, identity, edit)
        elif isinstance(value, list):
            for child in value:
                count += self.edit_ability(child, identity, edit)
        return count

    def waiting(self, *, natural=False, board=('dragon.wait', 'tribal.source', 'false.source')):
        name = 'kill' if natural else 'trigger'
        g = self.game(hand=(name,), board=board)
        self.play(g, name, find(g.state, board[0]))
        return g

    def self_fixture(self, *, another=True, origins=('printed','granted'), body='wait'):
        declaration = spec(3, tribes=('dragon',), scope='self', origins=origins,
            condition=condition(another=another))
        self.minion('self', body, tribes=('dragon',), deathrattle_repeats=(declaration,))
        return declaration

    def test_model_validation_preserves_physical_kinds_and_payload_origins(self):
        self.assertEqual(spec(scope='self', kinds=(CardType.WEAPON,)).kinds, (CardType.WEAPON,))
        for args in ((True, 'dragon', CardType.MINION), (0, 'dragon', CardType.MINION),
                (1, '', CardType.MINION), (1, 'dragon', CardType.SPELL)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeathrattleRecipient(*args)
        for fields in ({'tribes_any':['dragon']}, {'tribes_any':('dragon','dragon')},
                {'basis':'current_face'}, {'tribes_any':(True,)}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                DeathrattleRecipientMetadataFilter(**fields)
        with self.assertRaises(ValueError):
            DeathrattleRepeatSpec(match=BattlecryRepeatSpec())

    def test_match_codec_exact_fields_types_and_detached_values(self):
        matching = spec(tribes=('dragon',), condition=condition()).match
        encoded = deathrattle_match_to_dict(matching)
        self.assertEqual(deathrattle_match_from_dict(encoded), matching)
        encoded['recipient_metadata']['tribes_any'].append('beast')
        self.assertEqual(matching.recipient_metadata.tribes_any, ('dragon',))
        original = deathrattle_match_to_dict(matching)
        for mutation in ('missing', 'extra', 'unknown_basis', 'bool_another', 'duplicate'):
            value = copy.deepcopy(original)
            if mutation == 'missing': value.pop('source_eligibility')
            elif mutation == 'extra': value['unknown'] = None
            elif mutation == 'unknown_basis': value['recipient_metadata']['basis'] = 'current'
            elif mutation == 'bool_another': value['source_eligibility']['exclude_carrier'] = 1
            else: value['recipient_metadata']['tribes_any'] *= 2
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                deathrattle_match_from_dict(value)

    def test_registry_fingerprint_includes_complete_match_and_profile(self):
        before = self.r.fingerprint()
        self.source('new', spec(tribes=('dragon',), condition=condition()))
        self.assertNotEqual(self.r.fingerprint(), before)
        self.assertEqual(self.fresh().fingerprint(), self.r.fingerprint())

    def test_pure_static_intersection_uses_actual_receiver_not_donor(self):
        g = self.game(board=('dragon.rattle','dragon.rattle','beast'))
        carrier, other = g.state.players[1].board[:2]
        ability = active_abilities(g.state.entities[carrier], 'deathrattle')[0]
        recipient = capture_recipient_from_state(g.state, self.r, carrier)
        declaration = spec(3, tribes=('beast','dragon'), scope='self')
        self.assertTrue(deathrattle_repeat_recipient_matches(declaration, recipient=recipient,
            recipient_definition=self.r.card('dragon.rattle'), payload_ability=ability, source_carrier_id=carrier))
        self.assertFalse(deathrattle_repeat_recipient_matches(declaration, recipient=recipient,
            recipient_definition=self.r.card('dragon.rattle'), payload_ability=ability, source_carrier_id=other))
        self.assertFalse(deathrattle_repeat_recipient_matches(spec(origins=('granted',)), recipient=recipient,
            recipient_definition=self.r.card('dragon.rattle'), payload_ability=ability, source_carrier_id=carrier))

    def test_empty_tribe_filter_allows_unknown_metadata_and_query_is_pure(self):
        self.source('unfiltered', spec())
        self.minion('unknown.wait', 'wait', metadata=None)
        g = self.game(board=('unknown.wait','unfiltered'))
        before = g.snapshot(); carrier = g.state.players[1].board[0]
        ability = active_abilities(g.state.entities[carrier], 'deathrattle')[0]
        recipient = capture_recipient_from_state(g.state, self.r, carrier)
        plan = capture_plan(g.state, self.r, 1, recipient, ability)
        self.assertEqual(plan.repetitions, 2)
        self.assertIsNone(validate_plan(g.state, self.r, plan, 1, g.state.turn, recipient, ability))
        self.assertEqual(g.snapshot(), before)

    def test_recipient_tribes_OR_multi_and_all_match_actual_faces(self):
        for card, expected in (('dragon.rattle',2), ('beast.rattle',2), ('plain.rattle',1), ('all',2), ('multi',2)):
            with self.subTest(card=card):
                self.setUp()
                if card in ('all','multi'): self.minion(card+'.rattle','armor',tribes=self.r.card(card).metadata.tribes);card += '.rattle'
                self.source('either', spec(tribes=('beast','dragon')))
                g = self.game(hand=('kill',), board=(card,'either'))
                self.play(g,'kill',find(g.state,card));self.assertEqual(self.armor(g),expected)
                self.portable(g)

    def test_natural_recipient_uses_frozen_death_face_when_current_entity_differs(self):
        self.minion('dead.dragon','wait',tribes=('dragon',))
        g = self.waiting(natural=True,board=('dead.dragon','tribal.source'))
        carrier = g.state.death_history[0].entity_id
        self.assertEqual(g.state.entities[carrier].zone, Zone.GRAVEYARD)
        self.assertEqual(self.counts(g),[2])
        # This is a pure compact provenance query. Ordinary Transform only
        # targets BOARD, so no paid graveyard transformation route is claimed.
        later = copy.deepcopy(g.state)
        later.entities[carrier].card_id = 'plain'
        self.assertEqual(recipient_from_capture(later,self.r,g.state.deathrattle_history[0].capture).card_id,'dead.dragon')
        self.finish(g);self.assertEqual(self.armor(g),2)

    def test_effect_accepts_current_face_after_prior_transform(self):
        self.script('change.trigger',lambda c:[Transform(c.target_id,'dragon.rattle'),TriggerDeathrattles(c.target_id,c.source_id)],target=True)
        g=self.game(hand=('change.trigger',),board=('beast.rattle','tribal.source'))
        self.play(g,'change.trigger',find(g.state,'beast.rattle'))
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.deathrattle_history[0].capture.card_id,'dragon.rattle');self.portable(g)

    def test_printed_granted_payloads_accept_independent_max_and_order(self):
        self.source('self',spec(3,scope='self',origins=('granted',),tribes=('dragon',)),body='armor',tribes=('dragon',))
        g=self.game(hand=('grant','trigger'),board=('self','tribal.source'));receiver=find(g.state,'self')
        self.play(g,'grant',receiver);self.play(g,'trigger',receiver)
        self.assertEqual(self.counts(g),[2,3]);self.assertEqual(self.armor(g),32)
        self.assertEqual([(r.capture.ability.origin,r.capture.repeat_index)for r in g.state.deathrattle_history],
            [('printed',1),('printed',2),('granted',1),('granted',2),('granted',3)])
        self.portable(g)

    def test_same_named_neighbor_cannot_supply_self_scope(self):
        self.source('self',spec(3,scope='self',tribes=('dragon',)),tribes=('dragon',))
        self.script('grant.armor',lambda c:[GrantDeathrattle(c.target_id,'armor',c.source_id)],target=True)
        g=self.game(hand=('grant.armor','trigger'),board=('dragon.rattle','self','self'))
        self.play(g,'grant.armor',find(g.state,'dragon.rattle'));self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.assertEqual(self.armor(g),2);self.assertEqual(self.counts(g),[1,1]);self.portable(g)

    def test_max_keeps_weaker_equal_sources_and_distinct_attachment_ids(self):
        g=self.game(hand=('trigger',),board=('dragon.rattle','tribal.source','tribal.source','strong.source'))
        self.play(g,'trigger',find(g.state,'dragon.rattle'));plan=self.batch(g).payloads[0].plan
        self.assertEqual(plan.repetitions,3);self.assertEqual(len(plan.contributors),3)
        self.assertEqual(len({c.ability.id for c in plan.contributors}),3);self.assertEqual(self.armor(g),3);self.portable(g)

    def test_explicit_trigger_rounds_preserve_each_nonuniform_payload_plan(self):
        self.source('self',spec(3,scope='self',origins=('granted',),tribes=('dragon',)),body='armor',tribes=('dragon',))
        self.script('twice',lambda c:[TriggerDeathrattles(c.target_id,c.source_id,times=2)],target=True)
        g=self.game(hand=('grant','twice'),board=('self',));i=find(g.state,'self');self.play(g,'grant',i);self.play(g,'twice',i)
        self.assertEqual(self.counts(g),[1,3]);self.assertEqual(self.armor(g),62)
        self.assertEqual([(r.capture.trigger_index,r.capture.ability.origin,r.capture.repeat_index)for r in g.state.deathrattle_history],
            [(t,o,k)for t in (1,2)for o,rs in [('printed',(1,)),('granted',(1,2,3))]for k in rs]);self.portable(g)

    def test_simultaneous_removal_excludes_external_and_same_batch_witness(self):
        self.self_fixture();self.script('kill.all',lambda c:[DamageBatch(tuple(Damage(i,20)for i in c.state.players[1].board))])
        g=self.game(hand=('kill.all',),board=('self','beast','tribal.source'))
        self.play(g,'kill.all');self.assertEqual(self.counts(g),[1]);self.assertEqual(len(g.state.death_history),3)
        self.finish(g);self.assertEqual(self.armor(g),1)

    def test_natural_frozen_self_queries_surviving_post_removal_witness(self):
        self.self_fixture();g=self.waiting(natural=True,board=('self','beast'))
        work=self.proofs(g)[0];death=work.context.death
        source=next(a for a in death.abilities if a.kind=='deathrattle_repeat')
        self.assertEqual(qualifying_deathrattle_self_witnesses(work.context.state,self.r,
            player_id=death.controller,carrier_id=death.entity_id,
            death=death,source_ability=source,eligibility=source.deathrattle_repeat.match.source_eligibility),
            (find(g.state,'beast'),))
        self.assertEqual(self.counts(g),[3]);self.finish(g);self.assertEqual(self.armor(g),3)

    def test_natural_self_is_not_its_own_ordinary_presence_witness(self):
        self.source('self.dragon',spec(3,scope='self',tribes=('dragon',),condition=condition(another=False,tribes=('dragon',))),body='armor',tribes=('dragon',))
        g=self.game(hand=('kill',),board=('self.dragon',));self.play(g,'kill',find(g.state,'self.dragon'))
        self.assertEqual(self.armor(g),1);self.assertEqual(self.counts(g),[1]);self.portable(g)

    def test_effect_live_self_can_witness_presence_but_not_another(self):
        for another,count in ((False,3),(True,1)):
            with self.subTest(another=another):
                self.setUp();self.source('self.dragon',spec(3,scope='self',tribes=('dragon',),condition=condition(another=another,tribes=('dragon',))),body='armor',tribes=('dragon',))
                g=self.game(hand=('trigger',),board=('self.dragon',));self.play(g,'trigger',find(g.state,'self.dragon'))
                self.assertEqual(self.armor(g),count);self.portable(g)

    def test_same_card_name_different_physical_witness_satisfies_another(self):
        self.source('same',spec(tribes=('dragon',),condition=condition(tribes=('dragon',))),body='armor',tribes=('dragon',))
        g=self.game(hand=('trigger',),board=('same','same'));self.play(g,'trigger',g.state.players[1].board[0])
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.batch(g).payloads[0].plan.contributors),2);self.portable(g)

    def test_another_excludes_source_carrier_not_grant_provenance(self):
        self.script('grant.source',lambda c:[GrantDeathrattleRepeatAura(c.target_id,
            spec(condition=condition(tribes=('dragon',))),c.source_id)],target=True)
        g=self.game(hand=('grant.source','trigger'),board=('dragon.rattle','plain'))
        receiver=find(g.state,'dragon.rattle');carrier=find(g.state,'plain')
        self.play(g,'grant.source',carrier);self.play(g,'trigger',receiver)
        self.assertEqual(self.armor(g),2)
        self.assertEqual(self.batch(g).payloads[0].plan.contributors[0].carrier_id,carrier);self.portable(g)

    def unknown_query(self, *, origins=('printed','granted'), kinds=(CardType.MINION,), receiver='beast.rattle'):
        self.source('needs',spec(tribes=('dragon',),condition=condition(),origins=origins,kinds=kinds))
        g=self.game(hand=('trigger',),board=(receiver,'needs','beast','unknown.tribes'))
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'trigger',find(g.state,receiver))
        self.assertEqual(g.snapshot(),before)

    def test_recipient_false_cannot_hide_unknown_witness_metadata(self):
        self.unknown_query()

    def test_payload_origin_false_cannot_hide_unknown_witness_metadata(self):
        self.unknown_query(origins=('granted',),receiver='dragon.rattle')

    def test_recipient_kind_false_cannot_hide_unknown_witness_metadata(self):
        self.unknown_query(kinds=(CardType.WEAPON,),receiver='dragon.rattle')

    def test_complete_witness_query_checks_after_known_first_match(self):
        self.unknown_query(receiver='dragon.rattle')

    def test_false_kind_origin_and_self_cannot_hide_unknown_recipient_metadata(self):
        for fields in (dict(kinds=(CardType.WEAPON,)),dict(origins=('granted',)),dict(scope='self')):
            with self.subTest(fields=fields):
                self.setUp();self.source('unknown.recipient.source',spec(tribes=('dragon',),**fields))
                g=self.game(hand=('trigger',),board=('unknown.rattle','unknown.recipient.source'));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,'trigger',find(g.state,'unknown.rattle'))
                self.assertEqual(g.snapshot(),before)

    def test_presence_profiles_distinguish_dormant_witness(self):
        self.script('sleep',lambda c:[MakeDormant(c.target_id,2)],target=True)
        self.source('controlled',spec(condition=condition()))
        self.source('active',spec(3,condition=condition(profile='repeat.witness.active_live')))
        g=self.game(hand=('sleep','trigger'),board=('dragon.rattle','controlled','active','beast'))
        self.play(g,'sleep',find(g.state,'beast'));self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.assertEqual(self.armor(g),2);self.assertEqual([c.card_id for c in self.batch(g).payloads[0].plan.contributors],['controlled']);self.portable(g)

    def test_source_itself_must_stay_active_even_when_profile_includes_dormant(self):
        self.script('sleep',lambda c:[MakeDormant(c.target_id,2)],target=True)
        g=self.game(hand=('sleep','trigger'),board=('dragon.rattle','conditional.source','beast'))
        self.play(g,'sleep',find(g.state,'conditional.source'));self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.assertEqual(self.armor(g),1);self.assertEqual(self.counts(g),[1]);self.portable(g)

    def test_frozen_self_wrapper_rejects_mismatched_death_and_ability(self):
        self.self_fixture();g=self.waiting(natural=True,board=('self','beast'))
        work=self.proofs(g)[0];death=work.context.death;source=next(a for a in death.abilities if a.kind=='deathrattle_repeat')
        other=g.state.players[1].hero_id
        for broken in (replace(death,entity_id=other,cause=replace(death.cause,target_id=other)),
                replace(death,abilities=tuple(a for a in death.abilities if a.id!=source.id))):
            with self.subTest(broken=broken.id),self.assertRaises(ValueError):
                qualifying_deathrattle_self_witnesses(work.context.state,self.r,death=broken,
                    player_id=death.controller,carrier_id=death.entity_id,
                    source_ability=source,eligibility=source.deathrattle_repeat.match.source_eligibility)

    def test_unknown_profile_registration_and_stale_grant_reject_before_false(self):
        unknown=spec(tribes=('beast',),condition=condition(profile='missing.profile'))
        with self.assertRaises(ValueError):self.source('bad',unknown)
        self.script('stale',lambda c:[GrantDeathrattleRepeatAura(c.state.players[1].hero_id,unknown,c.source_id)])
        g=self.game(hand=('stale',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'stale')
        self.assertEqual(g.snapshot(),before)

    def test_false_nonminion_frozen_death_repeat_source_is_rejected(self):
        self.script('replace',lambda c:[EquipWeapon(1,'weapon')])
        g=self.game(hand=('replace',),board=('false.source',),weapon='weapon.rattle');self.play(g,'replace')
        s=g.snapshot();source=copy.deepcopy(next(a for a in s['state']['entities'][str(find(g.state,'false.source'))]['abilities']if a['kind']=='deathrattle_repeat'))
        source.update(id=s['state']['next_attachment_id'],origin='granted',base_index=None)
        s['state']['next_attachment_id']+=1;s['state']['death_history'][0]['abilities'].append(source)
        self.reject(s)

    def test_false_consumed_allzone_declaration_cannot_hide_unknown_profile(self):
        self.script('bounce',lambda c:[ReturnToHand(c.target_id)],target=True)
        g=self.game(hand=('bounce',),board=('false.source',));source=find(g.state,'false.source');self.play(g,'bounce',source)
        s=g.snapshot();a=next(a for a in s['state']['entities'][str(source)]['abilities']if a['kind']=='deathrattle_repeat')
        a['consumed']=True;a['deathrattle_repeat']['match']['source_eligibility']={'profile_id':'missing.profile','tribes_any':['beast'],'exclude_carrier':True}
        self.reject(s)

    def test_player_policy_allows_tribes_but_rejects_physical_self_condition(self):
        for declaration in (spec(scope='self'),spec(condition=condition())):
            with self.subTest(declaration=declaration),self.assertRaises(ValueError):
                PlayerEffectSpec('bad','plain',deathrattle_repeats=(declaration,))
        self.policy('policy',(spec(tribes=('dragon',)),));g=self.game(hand=('policy','trigger'))
        self.play(g,'policy');self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.assertEqual(self.armor(g),2);self.portable(g)

    def test_multispec_player_instance_keeps_indexes_and_max_without_consumption(self):
        self.policy('multi.policy',(spec(tribes=('dragon',)),spec(3,tribes=('dragon',)),spec(5,tribes=('beast',))))
        g=self.game(hand=('multi.policy','trigger'));self.play(g,'multi.policy');before=copy.deepcopy(g.state.players[1].player_effects)
        self.play(g,'trigger',find(g.state,'dragon.rattle'));contributors=self.batch(g).payloads[0].plan.contributors
        self.assertEqual([c.spec_index for c in contributors],[0,1]);self.assertEqual(len({c.instance.id for c in contributors}),1)
        self.assertEqual(self.armor(g),3);self.assertEqual(g.state.players[1].player_effects,before);self.portable(g)

    def test_duplicate_policy_instances_are_distinct_and_enemy_policy_excluded(self):
        self.policy('policy',(spec(tribes=('dragon',)),))
        g=self.game(hand=('policy','policy','trigger'),enemy_hand=('policy',))
        self.play(g,'policy');self.play(g,'policy');g.apply(EndTurn(1));self.play(g,'policy');g.apply(EndTurn(2))
        self.play(g,'trigger',find(g.state,'dragon.rattle'));sources=self.batch(g).payloads[0].plan.contributors
        self.assertEqual(len(sources),2);self.assertEqual(len({c.instance.id for c in sources}),2)
        self.assertEqual({c.player_id for c in sources},{1});self.assertEqual(self.armor(g),2);self.portable(g)

    def test_player_policy_removed_after_acceptance_keeps_plan_then_requeries(self):
        self.policy('policy',(spec(3,tribes=('dragon',)),))
        self.behavior('remove.wait',lambda c:[RemovePlayerEffect(c.player_id,c.state.players[c.player_id].player_effects[0].id),ask(c,GainArmor(c.player_id,1))] if c.state.players[c.player_id].player_effects else [ask(c,GainArmor(c.player_id,1))])
        self.minion('remover','remove.wait',tribes=('dragon',))
        g=self.game(hand=('policy','trigger','trigger'),board=('remover',));self.play(g,'policy');i=find(g.state,'remover');self.play(g,'trigger',i)
        self.assertFalse(g.state.players[1].player_effects);self.assertEqual(self.counts(g),[3]);self.finish(g)
        self.play(g,'trigger',i);self.assertEqual(self.counts(g),[1]);self.finish(g);self.assertEqual(self.armor(g),4)

    def test_owner_clock_ticks_once_per_boundary_not_per_payload_repeat(self):
        self.policy('clock',(spec(3,tribes=('dragon',)),),duration=2)
        g=self.game(hand=('clock','grant','trigger'));self.play(g,'clock');i=find(g.state,'dragon.rattle');self.play(g,'grant',i);self.play(g,'trigger',i)
        self.assertEqual(self.armor(g),33);self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1)
        g.apply(EndTurn(2));self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1);self.portable(g)

    def test_waiting_end_boundary_clock_applies_after_all_accepted_repeats(self):
        self.policy('clock',(spec(tribes=('dragon',)),),duration=1)
        self.behavior('end.dr',lambda c:[TriggerDeathrattles(find(c.state,'dragon.wait'),c.source_id)]if c.event.player_id==1 else [])
        self.minion('listener',triggers=(TriggerSpec('turn_ended','end.dr'),))
        g=self.game(hand=('clock',),board=('dragon.wait','listener'));self.play(g,'clock');g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1);self.assertEqual(self.counts(g),[2]);self.portable(g)
        self.choose(g);self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1);self.portable(g)
        self.choose(g);self.assertFalse(g.state.players[1].player_effects);self.assertEqual(g.state.active_player,2);self.assertEqual(self.armor(g),2);self.portable(g)

    def test_same_player_effect_legally_contributes_DR_and_EndTurn_under_parent_proof(self):
        self.policy('shared',(spec(tribes=('dragon',)),),duration=2,end_repeats=(EndTurnRepeatSpec(),))
        self.minion('end',triggers=(TriggerSpec('turn_ended','armor',EndTurnSpec()),))
        def nested(c):
            request=EndTurnRequest(EndTurnSelector('selected',(c.player_id,),('minion',),(find(c.state,'end'),)))
            return [ask(c,TriggerEndTurnEffects(c.player_id,request,c.source_id))]
        self.behavior('shared.body',nested);self.minion('shared.rattle','shared.body',tribes=('dragon',))
        g=self.game(hand=('shared','trigger'),board=('shared.rattle','end'));self.play(g,'shared');identity=g.state.players[1].player_effects[0].id
        self.play(g,'trigger',find(g.state,'shared.rattle'));self.finish(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.end_turn_batches),2)
        self.assertTrue(all(any(c.player_effect is not None and c.player_effect.id==identity for c in p.contributors)for b in g.state.end_turn_batches for p in b.plans))
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2);self.portable(g)

    def change_fixture(self):
        def body(c):
            effects=[GainArmor(c.player_id,1)]
            if c.deathrattle.repeat_index==1:
                effects += [Transform(c.source_id,'plain'),Transform(find(c.state,'beast'),'plain'),Silence(find(c.state,'conditional.source'))]
            return [ask(c,*effects)]
        self.behavior('change.wait',body);self.minion('changer','change.wait',tribes=('dragon',))
        return self.game(hand=('trigger','trigger'),board=('changer','conditional.source','beast','dragon.rattle'))

    def test_accepted_face_and_witness_survive_transform_then_next_group_requeries(self):
        g=self.change_fixture();self.play(g,'trigger',find(g.state,'changer'));self.assertEqual(self.counts(g),[2])
        self.choose(g);self.assertEqual(self.counts(g),[2]);self.assertEqual(g.state.entities[g.state.deathrattle_history[self.batch(g).id-1].capture.carrier_id].card_id,'plain');self.portable(g)
        self.choose(g);self.play(g,'trigger',find(g.state,'dragon.rattle'));self.assertEqual(self.counts(g),[1])
        self.assertEqual(self.armor(g),3);self.portable(g)

    def test_later_legal_control_transfer_keeps_original_source_identity(self):
        self.behavior('transfer',lambda c:[ask(c,ChangeControl(find(c.state,'tribal.source',1),2),GainArmor(c.player_id,1))]if c.deathrattle.repeat_index==1 else [ask(c,GainArmor(c.player_id,1))])
        self.minion('transfer.rattle','transfer',tribes=('dragon',))
        g=self.game(hand=('trigger',),board=('transfer.rattle','tribal.source'),enemy=('dragon.rattle',),enemy_hand=('trigger',))
        self.play(g,'trigger',find(g.state,'transfer.rattle'));identity=self.batch(g).payloads[0].plan.contributors[0].ability.id;self.finish(g)
        g.apply(EndTurn(1));self.play(g,'trigger',find(g.state,'dragon.rattle',2))
        self.assertEqual((self.armor(g),self.armor(g,2)),(2,2));self.assertEqual(self.batch(g).payloads[0].plan.contributors[0].ability.id,identity);self.portable(g)

    def test_nested_death_uses_new_world_but_parent_keeps_accepted_plan(self):
        self.behavior('nested',lambda c:[ask(c,Silence(find(c.state,'tribal.source')),Destroy(find(c.state,'beast.wait')),GainArmor(c.player_id,1))]if c.deathrattle.repeat_index==1 else [ask(c,GainArmor(c.player_id,1))])
        self.minion('parent','nested',tribes=('dragon',));g=self.game(hand=('trigger',),board=('parent','tribal.source','beast.wait'))
        self.play(g,'trigger',find(g.state,'parent'));self.choose(g);self.assertEqual([self.counts(g,i)for i in range(2)],[[2],[1]])
        self.finish(g);self.assertEqual(self.armor(g),3);self.assertEqual([r.execution_order for r in g.state.deathrattle_history],[1,3,2]);self.portable(g)

    def test_all_false_source_static_spec_cannot_change_while_waiting(self):
        g=self.waiting();s=g.snapshot();a=next(a for a in s['state']['entities'][str(find(g.state,'false.source'))]['abilities']if a['kind']=='deathrattle_repeat')
        a['deathrattle_repeat']['repetitions']=4;self.reject(s)

    def test_false_source_erased_only_from_original_proof_is_rejected(self):
        g=self.waiting();s=g.snapshot();identity=active_abilities(g.state.entities[find(g.state,'false.source')],'deathrattle_repeat')[0].id
        marker=self.nodes(s['resolution_frame'],'FinishDeathrattleBatch')[0]
        removed = []
        def erase(v):
            if isinstance(v,dict):
                if isinstance(v.get('abilities'),list):
                    before=len(v['abilities'])
                    v['abilities'][:]=[a for a in v['abilities']if a.get('id')!=identity]
                    removed.append(before-len(v['abilities']))
                for x in v.values():erase(x)
            elif isinstance(v,list):
                for x in v:erase(x)
        erase(marker['fields']['context']);self.assertGreater(sum(removed),0);self.reject(s)

    def test_queued_invoke_false_declaration_is_bound_to_full_original_group(self):
        g=self.waiting();s=g.snapshot()
        identity=active_abilities(g.state.entities[find(g.state,'false.source')],'deathrattle_repeat')[0].id
        queued=self.nodes(s['resolution_frame'],'InvokeDeathrattle')
        self.assertTrue(queued)
        def change(fields,typed):
            declaration=fields['deathrattle_repeat']
            if typed:declaration=declaration['fields']
            declaration['repetitions']=4
        edits=self.edit_ability(queued[0]['fields']['context'],identity,change)
        self.assertGreater(edits,0);self.reject(s)
        self.finish(g);self.assertEqual(self.armor(g),2)

    def test_new_death_record_false_source_remains_bound_when_live_attachment_is_absent(self):
        def body(c):
            effects=[GainArmor(c.player_id,1)]
            if c.deathrattle.repeat_index==1:effects.insert(0,Destroy(find(c.state,'false.source')))
            return [ask(c,*effects)]
        self.behavior('later.death',body);self.minion('later.death','later.death',tribes=('dragon',))
        g=self.waiting(board=('later.death','tribal.source','false.source'));old=find(g.state,'false.source')
        identity=active_abilities(g.state.entities[old],'deathrattle_repeat')[0].id
        self.choose(g);self.assertEqual(len(g.state.death_history),1);self.portable(g)
        s=g.snapshot()
        # Absence is an allowed compact boundary; no graveyard cleanup effect
        # is claimed. The frozen natural declaration must still be protected.
        s['state']['entities'][str(old)]['abilities']=[]
        restored=self.restore_modified(copy.deepcopy(s))
        self.assertEqual(restored.state.death_history[0].entity_id,old)
        frozen=next(a for a in s['state']['death_history'][0]['abilities']if a['id']==identity)
        frozen['deathrattle_repeat']['repetitions']=4
        self.reject(s);self.finish(g);self.assertEqual(self.armor(g),2)

    def test_original_consumed_false_source_cannot_be_revived_during_waiting(self):
        g=self.game(hand=('trigger',),board=('dragon.wait','false.source'))
        carrier=find(g.state,'false.source');old=next(a for a in g.state.entities[carrier].abilities if a.kind=='deathrattle_repeat')
        # A valid synthetic starting attachment, rather than a new ability
        # consumption effect. Its paid root creates the actual original proof.
        g._state.entities[carrier].abilities=[replace(a,consumed=True)if a.id==old.id else a for a in g._state.entities[carrier].abilities]
        g=Game.from_snapshot(g.snapshot(),self.fresh())
        self.play(g,'trigger',find(g.state,'dragon.wait'))
        self.assertEqual(self.counts(g),[1]);Game.from_snapshot(g.snapshot(),self.fresh())
        s=g.snapshot();source=next(a for a in s['state']['entities'][str(carrier)]['abilities']if a['id']==old.id)
        source['consumed']=False;self.reject(s)

    def test_old_global_id_cannot_switch_family_on_a_false_live_carrier(self):
        g=self.waiting();s=g.snapshot();a=next(a for a in s['state']['entities'][str(find(g.state,'false.source'))]['abilities']if a['kind']=='deathrattle_repeat')
        a['kind']='battlecry_repeat';a['battlecry_repeat']={'repetitions':2,'kinds':['minion'],'scope':'friendly','match':None};a['deathrattle_repeat']=None
        self.reject(s)

    def test_completed_history_contributor_id_cannot_belong_to_other_family(self):
        self.minion('foreign',battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),))
        g=self.game(hand=('trigger',),board=('dragon.rattle','tribal.source','foreign'));self.play(g,'trigger',find(g.state,'dragon.rattle'))
        foreign=active_abilities(g.state.entities[find(g.state,'foreign')],'battlecry_repeat')[0]
        s=g.snapshot();source=s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0]
        source['ability']['id']=foreign.id
        self.reject(s)

    def removed_source_nested(self):
        self.behavior('child',lambda c:[Silence(find(c.state,'conditional.source')),*[ask(c,GainArmor(c.player_id,1))]])
        self.minion('child','child',tribes=('dragon',))
        self.behavior('parent',lambda c:[ask(c,TriggerDeathrattles(find(c.state,'child'),c.source_id))])
        self.minion('parent','parent',tribes=('beast',))
        g=self.game(hand=('trigger',),board=('parent','conditional.source','beast','child'));self.play(g,'trigger',find(g.state,'parent'));self.choose(g)
        return g

    def test_later_removed_source_full_declaration_still_bound_to_false_parent(self):
        g=self.removed_source_nested();self.assertFalse(active_abilities(g.state.entities[find(g.state,'conditional.source')],'deathrattle_repeat'))
        s=g.snapshot();child=self.batch(g);identity=child.payloads[0].plan.contributors[0].ability.id
        def change(fields,typed):
            declaration=fields['deathrattle_repeat']
            if typed:
                declaration['fields']['match']['fields']['recipient_metadata']['fields']['tribes_any']['tuple']=['dragon','mech']
            else:
                declaration['match']['recipient_metadata']['tribes_any']=['dragon','mech']
        edits=[self.edit_ability(s['state']['deathrattle_batches'][-1],identity,change),
            self.edit_ability(s['state']['deathrattle_history'][child.id-1:],identity,change)]
        for marker in self.nodes(s['resolution_frame'],'FinishDeathrattleBatch'):
            if marker['fields']['batch']['fields']['id']==child.id:edits.append(self.edit_ability(marker,identity,change))
        for context_node in self.nodes(s['resolution_frame'],'RuleContext'):
            cap=context_node['fields'].get('deathrattle')
            if isinstance(cap,dict)and cap.get('fields',{}).get('group_id')==child.id:edits.append(self.edit_ability(context_node,identity,change))
        self.assertGreater(sum(edits),0)
        self.reject(s);self.finish(g);self.assertEqual(self.armor(g),2)

    def test_false_player_effect_owner_and_static_identity_are_bound(self):
        self.policy('false.policy',(spec(tribes=('beast',)),));g=self.game(hand=('false.policy','trigger'),board=('dragon.wait',));self.play(g,'false.policy');self.play(g,'trigger',find(g.state,'dragon.wait'))
        for field,value in (('source_id',g.state.players[2].hero_id),('created_turn',2),('entered_order',999)):
            s=g.snapshot();s['state']['players']['1']['player_effects'][0][field]=value
            with self.subTest(field=field):self.reject(s)

    def foreign_child(self):
        self.minion('dual',deathrattle_repeats=(spec(5,tribes=('beast',)),),battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),))
        self.behavior('child.cry',lambda c:[ask(c,Silence(find(c.state,'dual')),GainArmor(c.player_id,1))]if c.battlecry.repeat_index==1 else [ask(c,GainArmor(c.player_id,1))])
        self.minion('child.cry',cost=1,battlecry='child.cry')
        def parent(c):
            child=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='child.cry')
            return [ask(c,PlayFromHand(PlayCard(c.player_id,child)),GainArmor(c.player_id,1))]
        self.behavior('parent.paid',parent);self.minion('parent.paid','parent.paid',tribes=('dragon',))
        g=self.game(hand=('trigger','child.cry'),board=('parent.paid','dual'))
        old=active_abilities(g.state.entities[find(g.state,'dual')],'deathrattle_repeat')[0].id
        bc=active_abilities(g.state.entities[find(g.state,'dual')],'battlecry_repeat')[0].id
        self.play(g,'trigger',find(g.state,'parent.paid'));self.choose(g);self.choose(g)
        return g,old,bc

    def test_false_DR_old_id_cannot_become_later_BC_source_after_both_are_removed(self):
        g,old,bc=self.foreign_child();self.assertFalse(g.state.entities[find(g.state,'dual')].abilities)
        s=g.snapshot();child=g.state.play_history[-1]
        def rewrite(v):
            if isinstance(v,dict):
                if 'contributors' in v and isinstance(v['contributors'],list):v['contributors'][:]=[old if x==bc else x for x in v['contributors']]
                if v.get('type','').endswith('.BattlecryRepeatPlan'):
                    values=v['fields']['contributors']['tuple'];values[:]=[old if x==bc else x for x in values]
                for x in v.values():rewrite(x)
            elif isinstance(v,list):
                for x in v:rewrite(x)
        rewrite(s['state'])
        for context_node in self.nodes(s['resolution_frame'],'RuleContext'):
            play=context_node['fields'].get('play')
            if isinstance(play,dict)and play.get('fields',{}).get('id')==child.id:rewrite(context_node)
        self.reject(s);self.finish(g);self.assertEqual(self.armor(g),3)

    def test_later_BC_complete_original_window_binds_removed_false_DR_declaration(self):
        g,old,bc=self.foreign_child();s=g.snapshot()
        markers=self.nodes(s['resolution_frame'],'FinishBattlecryAcceptance')
        self.assertTrue(markers)
        def change(fields,typed):
            declaration=fields['deathrattle_repeat']
            if typed:declaration=declaration['fields']
            declaration['repetitions']=4
        edits=sum(self.edit_ability(marker['fields']['context'],old,change)for marker in markers)
        self.assertGreater(edits,0);self.reject(s)
        self.finish(g);self.assertEqual(self.armor(g),3)

    def end_guard_fixture(self, *, skip=False):
        def first(c):
            after=[Silence(find(c.state,'false.source'))]
            if skip:after.append(Destroy(find(c.state,'end.last')))
            after.append(ask(c,GainArmor(c.player_id,1)))
            return [ask(c,*after)]
        self.behavior('end.first',first)
        self.minion('end.first',triggers=(TriggerSpec('turn_ended','end.first',EndTurnSpec()),))
        self.minion('end.last',limited_triggers=(LimitedTriggerSpec('turn_ended','armor',uses=2,end_turn=EndTurnSpec()),))
        def parent(c):
            if c.deathrattle.repeat_index>1:return [ask(c,GainArmor(c.player_id,1))]
            selected=(find(c.state,'end.first'),find(c.state,'end.last'))
            request=EndTurnRequest(EndTurnSelector('selected',(1,),('minion',),selected))
            return [ask(c,TriggerEndTurnEffects(1,request,c.source_id))]
        self.behavior('guard.parent',parent);self.minion('guard.parent','guard.parent',tribes=('dragon',))
        g=self.waiting(board=('guard.parent','tribal.source','false.source','end.first','end.last'))
        source=find(g.state,'false.source');identity=active_abilities(g.state.entities[source],'deathrattle_repeat')[0].id
        self.choose(g);self.choose(g)
        self.assertFalse(g.state.entities[source].abilities);self.portable(g)
        return g,identity

    def test_later_pending_EndTurn_guard_false_source_window_is_bound(self):
        g,identity=self.end_guard_fixture();s=g.snapshot()
        guards=self.nodes(s['resolution_frame'],'CheckActiveEndTurn');self.assertTrue(guards)
        def change(fields,typed):
            declaration=fields['deathrattle_repeat']
            if typed:declaration=declaration['fields']
            declaration['repetitions']=4
        self.assertGreater(self.edit_ability(guards[-1],identity,change),0)
        self.reject(s);self.finish(g)

    def test_later_EndTurn_guard_validates_original_sources_before_legal_skip(self):
        g,identity=self.end_guard_fixture(skip=True);before=g.snapshot()
        from hs_sim.engine.deathrattle_acceptance import validate_control_work
        from hs_sim.engine.end_turns import CheckActiveEndTurn
        called=[]
        def corrupt(r,work):
            if type(work)is CheckActiveEndTurn and work.acceptance.source.card_id=='end.last':
                saved=copy.deepcopy(work.acceptance.state)
                for entity in saved.entities.values():
                    entity.abilities=[replace(a,deathrattle_repeat=replace(a.deathrattle_repeat,repetitions=4))
                        if a.id==identity else a for a in entity.abilities]
                context=replace(work.acceptance,state=saved)
                work=replace(work,context=context,acceptance=context);called.append(True)
            return validate_control_work(r,work)
        with patch('hs_sim.engine.deathrattle_acceptance.validate_control_work',side_effect=corrupt),self.assertRaises(ResolutionError):self.choose(g)
        self.assertTrue(called);self.assertEqual(g.snapshot(),before);self.portable(g)
        self.finish(g);self.assertTrue(any(row.skipped for row in g.state.end_turn_history))

    def test_later_two_closed_paid_combo_roots_keep_exact_finite_use_chain_when_source_is_gone(self):
        self.script('combo.policy',lambda c:[AddComboRepeatModifier(c.player_id,ComboRepeatSpec(),
            source_id=c.source_id,uses=2,trigger='activation')])
        self.minion('combo.child',cost=1,keywords=(Keyword.COMBO,),combo='armor')
        def parent(c):
            children=[i for i in c.state.players[1].hand if c.state.entities[i].card_id=='combo.child']
            tail=ask(c,GainArmor(1,1))
            second=ask(c,PlayFromHand(PlayCard(1,children[1])),tail)
            return [ask(c,PlayFromHand(PlayCard(1,children[0])),second)]
        self.behavior('combo.parent',parent);self.minion('combo.parent','combo.parent',tribes=('dragon',))
        g=self.game(hand=('combo.policy','trigger','combo.child','combo.child'),board=('combo.parent',))
        self.play(g,'combo.policy');identity=g.state.players[1].combo_modifiers[0].id
        self.play(g,'trigger',find(g.state,'combo.parent'));self.choose(g);self.portable(g);self.choose(g);self.portable(g)
        self.assertFalse(g.state.players[1].combo_modifiers)
        self.assertTrue(all(p.completed for p in g.state.play_history if p.kind==CardType.MINION))
        self.assertFalse(any(type(w).__name__=='FinishComboAcceptance'for w in (*g._frame.prefix,*g._frame.continuation)))
        receipts=[r for r in g.state.combo_policy_receipts if r.modifiers]
        self.assertEqual([r.modifiers[0].uses_remaining for r in receipts],[2,1])
        s=g.snapshot();later=next(r for r in s['state']['combo_policy_receipts']if r['id']==receipts[-1].id)
        self.assertEqual(later['modifiers'][0]['id'],identity);later['modifiers'][0]['uses_remaining']=2
        self.reject(s);self.finish(g);self.assertEqual(self.armor(g),5);self.assertEqual(g.state.players[1].mana,6)

    def hp_root_fixture(self, *, pending_start, fatal):
        from hs_sim.engine.hero_powers import TriggerHeroPower
        self.minion('hp.false.source')
        self.behavior('hp.parent.body',lambda c:[TriggerHeroPower(c.player_id,c.source_id,
            choices='player',targeting='explicit'),GainArmor(c.player_id,10)])
        self.minion('hp.parent','hp.parent.body',tribes=('dragon',))
        def choice(c):
            effect=Damage(c.state.players[2].hero_id,40)if fatal else GainArmor(c.player_id,1)
            return [ask(c,effect)]
        if pending_start:
            self.behavior('hp.start.wait',choice)
            self.minion('hp.start.wait',triggers=(TriggerSpec('hero_power_trigger_started','hp.start.wait'),))
        else:
            self.behavior('hp.last.wait',choice)
        self.install('card',CardDefinition('hp.skill','Synthetic skill',CardType.HERO_POWER,
            cost=2,on_use='noop' if pending_start else 'hp.last.wait',metadata=metadata()))
        # A real public grant is accepted before DR capture in the same paid
        # Spell. No printed-source mismatch or fake manual paid HP is involved.
        self.script('hp.parent.trigger',lambda c:[GrantDeathrattleRepeatAura(
            find(c.state,'hp.false.source'),spec(5,tribes=('beast',)),c.source_id),
            TriggerDeathrattles(find(c.state,'hp.parent'),c.source_id)])
        board=('hp.parent','hp.false.source')+(('hp.start.wait',)if pending_start else ())
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('hp.parent.trigger',),
            board=board,deck=('plain',)*14,hero_power_card_id='hp.skill',mana=10,max_mana=10),
            PlayerSetup('hero',deck=('plain',)*14,mana=10,max_mana=10)),seed=154),self.r)
        self.play(g,'hp.parent.trigger')
        source=active_abilities(g.state.entities[find(g.state,'hp.false.source')],'deathrattle_repeat')[0]
        self.assertEqual(source.origin,'granted');self.assertEqual(source.deathrattle_repeat.repetitions,5)
        return g,source.id

    def hp_root_window_assertions(self, g, identity, *, pending_start, fatal):
        from hs_sim.engine.hero_powers import FinishHeroPower,validate_acceptance
        from hs_sim.engine.model import validate_invariants
        work=(*g._frame.prefix,*g._frame.continuation)
        roots=[item for item in work if type(item)is FinishHeroPower]
        self.assertEqual(len(roots),1);self.assertEqual(len(self.proofs(g)),1)
        root=roots[0];power=g.state.hero_power_history[-1]
        self.assertEqual((root.record_id,root.context.power.id),(power.id,power.id))
        self.assertIsNone(root.context.power_payload)
        self.assertEqual((power.origin,power.failure,power.repeat_plan.repetitions),('effect',None,1))
        self.assertFalse(power.completed);self.assertFalse(self.batch(g).payloads[0].plan.contributors)
        if pending_start:
            # A valid active noop has one real payload. The ordinary start
            # reaction pauses before its Invoke, while root Finish is separate.
            self.assertEqual(len(power.payloads),1);self.assertEqual(len(g.state.hero_power_payload_history),1)
            self.assertEqual(len(g.state.hero_power_payload_batches),1)
            self.assertIsNone(g.state.hero_power_payload_history[0].execution_order)
            self.assertFalse(g.state.hero_power_payload_history[0].completed)
            invokes=[item for item in work if type(item).__name__=='InvokeHeroPowerPayload']
            self.assertEqual(len(invokes),1)
            self.assertEqual(invokes[0].context.power_payload.power_id,power.id)
        else:
            self.assertFalse(any(type(item).__name__=='InvokeHeroPowerPayload'for item in work))
            self.assertEqual(len(power.payloads),1);self.assertEqual(len(g.state.hero_power_payload_history),1)
            self.assertEqual(g.state.hero_power_payload_history[0].execution_order,1)
            self.assertFalse(g.state.hero_power_payload_history[0].completed)
            self.assertTrue(any(type(item).__name__=='FinishHeroPowerPayload'for item in work))
        before=g.snapshot();self.portable(g)
        altered_state=copy.deepcopy(root.context.state)
        for entity in altered_state.entities.values():
            entity.abilities=[replace(a,deathrattle_repeat=replace(a.deathrattle_repeat,repetitions=4))
                if a.id==identity else a for a in entity.abilities]
        altered_root=replace(root,context=replace(root.context,state=altered_state))
        # The mutation is a legal granted declaration and irrelevant to the
        # skill's own payload/plan; only the enclosing DR proof should refuse it.
        self.assertIsNone(validate_invariants(altered_state,self.r))
        self.assertIsNone(validate_acceptance(altered_root,self.r))
        damaged=copy.deepcopy(before)
        marker=self.nodes(damaged['resolution_frame'],'FinishHeroPower')[0]
        def change(fields,typed):
            declaration=fields['deathrattle_repeat']
            if typed:declaration=declaration['fields']
            declaration['repetitions']=4
        self.assertEqual(self.edit_ability(marker['fields']['context'],identity,change),1)
        self.assertEqual(damaged['state'],before['state'])
        self.assertEqual(self.nodes(damaged['resolution_frame'],'FinishDeathrattleBatch'),
            self.nodes(before['resolution_frame'],'FinishDeathrattleBatch'))
        self.assertEqual(marker['fields']['context']['fields']['power'],
            self.nodes(before['resolution_frame'],'FinishHeroPower')[0]['fields']['context']['fields']['power'])
        self.assertEqual(self.nodes(damaged['resolution_frame'],'InvokeHeroPowerPayload'),
            self.nodes(before['resolution_frame'],'InvokeHeroPowerPayload'))
        branches=(g,g.clone(),Game.from_snapshot(before,self.fresh()),replay(build_replay(g),self.fresh()))
        for branch in branches:self.choose(branch)
        final=g.snapshot();self.assertTrue(all(branch.snapshot()==final for branch in branches));self.portable(g)
        self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0)
        if fatal:
            self.assertEqual(g.state.status,'finished');self.assertTrue(g.state.hero_power_history[0].interrupted)
            self.assertTrue(all(row.interrupted for row in g.state.deathrattle_history))
            self.assertTrue(all(row.interrupted for row in g.state.hero_power_payload_history))
        else:
            self.assertTrue(g.state.hero_power_history[0].completed)
            self.assertTrue(all(row.completed for row in g.state.deathrattle_history))
            self.assertTrue(all(row.completed for row in g.state.hero_power_payload_history))
            self.assertEqual(self.armor(g),11)
        self.reject(damaged)

    def hp_earlier_root_assertions(self, *, pending_start):
        from hs_sim.engine.hero_powers import FinishHeroPower,TriggerHeroPower
        self.minion('hp.early.false')
        self.behavior('hp.early.parent',lambda c:[ask(c,GainArmor(c.player_id,1))])
        self.minion('hp.early.parent','hp.early.parent',tribes=('dragon',))
        self.behavior('hp.early.start',lambda c:[TriggerDeathrattles(find(c.state,'hp.early.parent'),c.source_id)])
        self.minion('hp.early.start',triggers=(TriggerSpec('hero_power_trigger_started','hp.early.start'),))
        self.install('card',CardDefinition('hp.early.skill','Earlier skill',CardType.HERO_POWER,
            cost=2,on_use='noop' if pending_start else 'armor',metadata=metadata()))
        self.script('hp.early.trigger',lambda c:[GrantDeathrattleRepeatAura(find(c.state,'hp.early.false'),
            spec(5,tribes=('beast',)),c.source_id),TriggerHeroPower(c.player_id,c.source_id,
                choices='player',targeting='explicit')])
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('hp.early.trigger',),
            board=('hp.early.parent','hp.early.false','hp.early.start'),deck=('plain',)*14,
            hero_power_card_id='hp.early.skill',mana=10,max_mana=10),
            PlayerSetup('hero',deck=('plain',)*14,mana=10,max_mana=10)),seed=154),self.r)
        self.play(g,'hp.early.trigger')
        roots=[item for item in (*g._frame.prefix,*g._frame.continuation)if type(item)is FinishHeroPower]
        self.assertEqual(len(roots),1);self.assertEqual(len(self.proofs(g)),1)
        self.assertFalse(roots[0].context.state.deathrattle_batches)
        self.assertEqual(self.proofs(g)[0].context.state.hero_power_history[0].id,roots[0].record_id)
        self.portable(g);before=g.snapshot()
        branches=(g,g.clone(),Game.from_snapshot(before,self.fresh()),replay(build_replay(g),self.fresh()))
        for branch in branches:self.choose(branch)
        self.assertTrue(all(branch.snapshot()==g.snapshot()for branch in branches));self.portable(g)
        self.assertTrue(g.state.hero_power_history[0].completed)
        self.assertTrue(all(row.completed for row in g.state.deathrattle_history))
        self.assertEqual(self.armor(g),1 if pending_start else 2)

    def test_pending_start_HeroPower_root_original_window_binds_parent_false_DR_source(self):
        for fatal in (False,True):
            self.setUp()
            with self.subTest(fatal=fatal):
                g,identity=self.hp_root_fixture(pending_start=True,fatal=fatal)
                self.hp_root_window_assertions(g,identity,pending_start=True,fatal=fatal)
        self.setUp();self.hp_earlier_root_assertions(pending_start=True)

    def test_last_HeroPower_payload_root_original_window_binds_parent_false_DR_source(self):
        for fatal in (False,True):
            self.setUp()
            with self.subTest(fatal=fatal):
                g,identity=self.hp_root_fixture(pending_start=False,fatal=fatal)
                self.hp_root_window_assertions(g,identity,pending_start=False,fatal=fatal)
        self.setUp();self.hp_earlier_root_assertions(pending_start=False)

    def test_waiting_all_positions_restore_clone_and_fresh_registry_replay(self):
        self.source('self',spec(3,scope='self',origins=('granted',),tribes=('dragon',)),body='wait',tribes=('dragon',))
        self.script('grant.wait',lambda c:[GrantDeathrattle(c.target_id,'wait',c.source_id)],target=True)
        g=self.game(hand=('grant.wait','trigger'),board=('self','tribal.source'));i=find(g.state,'self');self.play(g,'grant.wait',i);self.play(g,'trigger',i)
        seen=[]
        while g.state.pending_choice:
            self.portable(g);running=next(r for r in g.state.deathrattle_history if r.execution_order is not None and not r.completed)
            seen.append((running.capture.ability.origin,running.capture.repeat_index));self.choose(g)
        self.assertEqual(seen,[('printed',1),('printed',2),('granted',1),('granted',2),('granted',3)])
        self.assertEqual(self.armor(g),5);self.portable(g)

    def test_entire_finish_marker_and_all_unstarted_span_cannot_be_deleted(self):
        g=self.waiting();s=g.snapshot();q=self.queue(s)
        q[:]=[w for w in q if not(w.get('type','').endswith('.FinishDeathrattleBatch')or w.get('type','').endswith('.InvokeDeathrattle'))]
        self.reject(s)

    def test_repeat_span_count_order_and_prefix_cannot_be_shortened(self):
        g=self.waiting()
        for change in ('count','duplicate','order','counter'):
            s=g.snapshot()
            if change=='count':s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['repetitions']=1
            elif change=='counter':s['state']['next_deathrattle_id']-=1
            elif change=='duplicate':s['state']['deathrattle_history'][1]['capture']['id']=1
            else:self.queue(s).reverse()
            with self.subTest(change=change):self.reject(s)

    def test_already_completed_capture_prefix_is_bound_during_next_group(self):
        g=self.game(hand=('trigger','trigger'),board=('dragon.rattle','dragon.wait','tribal.source'));self.play(g,'trigger',find(g.state,'dragon.rattle'));self.play(g,'trigger',find(g.state,'dragon.wait'))
        s=g.snapshot();s['state']['deathrattle_history'][0]['capture']['trigger_source_card_id']='plain';self.reject(s)

    def test_completed_compact_history_does_not_rejudge_current_witness(self):
        g=self.game(hand=('trigger','kill'),board=('dragon.rattle','conditional.source','beast'));self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.play(g,'kill',find(g.state,'beast'));self.assertEqual(self.counts(g,0),[2]);self.assertEqual(self.armor(g),2);self.portable(g)

    def test_no_body_stays_no_batch_but_false_sources_keep_real_body_proof(self):
        g=self.game(hand=('trigger','trigger'),board=('plain','dragon.wait','false.source'));self.play(g,'trigger',find(g.state,'plain'))
        self.assertFalse(g.state.deathrattle_batches)
        self.play(g,'trigger',find(g.state,'dragon.wait'));self.assertEqual(self.counts(g),[1]);self.assertFalse(self.batch(g).payloads[0].plan.contributors)
        self.assertEqual(len(self.proofs(g)),1);self.finish(g);self.assertEqual(self.armor(g),1)

    def test_terminal_during_repeat_preserves_completed_and_interrupted_positions(self):
        self.behavior('fatal',lambda c:[GainArmor(c.player_id,1),Damage(c.state.players[2].hero_id,40)])
        self.minion('fatal','fatal',tribes=('dragon',));g=self.game(hand=('trigger',),board=('fatal','strong.source'))
        self.play(g,'trigger',find(g.state,'fatal'));rows=g.state.deathrattle_history
        self.assertEqual([r.execution_order for r in rows],[1,None,None]);self.assertTrue(all(r.interrupted for r in rows))
        self.assertEqual(self.armor(g),1);self.portable(g)

    def test_terminal_before_any_body_keeps_all_queued_interrupted(self):
        self.behavior('on.death.fatal',lambda c:[Damage(c.state.players[2].hero_id,40)])
        self.minion('listener',triggers=(TriggerSpec('minion_died','on.death.fatal'),))
        g=self.game(hand=('kill',),board=('dragon.rattle','strong.source','listener'));self.play(g,'kill',find(g.state,'dragon.rattle'))
        self.assertEqual([r.execution_order for r in g.state.deathrattle_history],[None,None,None]);self.assertTrue(all(r.interrupted for r in g.state.deathrattle_history));self.portable(g)

    def test_terminal_cut_proof_is_rejected_before_cleanup_and_rolls_back_choice(self):
        self.behavior('fatal.wait',lambda c:[ask(c,Damage(c.state.players[2].hero_id,40))]);self.minion('fatal.wait','fatal.wait',tribes=('dragon',))
        g=self.waiting(board=('fatal.wait','tribal.source'));before=g.snapshot()
        from hs_sim.engine.deathrattle_acceptance import validate_terminal_queue
        def cut(r,queue):
            trimmed=tuple(w for w in queue if type(w)is not FinishDeathrattleBatch)
            return validate_terminal_queue(r,trimmed)
        with patch('hs_sim.engine.deathrattle_acceptance.validate_terminal_queue',side_effect=cut),self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_closing_one_group_checks_complete_remaining_sibling_queue(self):
        self.script('kill.pair',lambda c:[DamageBatch(tuple(Damage(find(c.state,name),20)for name in ('dragon.wait','beast.wait')))])
        g=self.game(hand=('kill.pair',),board=('dragon.wait','beast.wait'))
        self.play(g,'kill.pair');self.assertEqual(len(g.state.deathrattle_batches),2);self.portable(g);before=g.snapshot()
        from hs_sim.engine.deathrattle_acceptance import validate_queue
        from hs_sim.engine.deathrattles import InvokeDeathrattle
        calls=[]
        def cut(state,registry,queue,limit,**kwargs):
            if kwargs.get('closing') is not None:
                queue=tuple(item for item in queue if type(item)is not InvokeDeathrattle);calls.append(True)
            return validate_queue(state,registry,queue,limit,**kwargs)
        with patch('hs_sim.engine.deathrattle_acceptance.validate_queue',side_effect=cut),self.assertRaises(ResolutionError):self.choose(g)
        self.assertTrue(calls);self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(self.armor(g),2)

    def test_terminal_catalogue_checks_dormancy_global_id_before_abandoning_queue(self):
        self.script('sleep',lambda c:[MakeDormant(c.target_id,2)],target=True)
        self.behavior('fatal.wait',lambda c:[ask(c,Damage(c.state.players[2].hero_id,40))]);self.minion('fatal.wait','fatal.wait',tribes=('dragon',))
        g=self.game(hand=('sleep','trigger'),board=('fatal.wait','tribal.source','false.source','beast'))
        self.play(g,'sleep',find(g.state,'beast'));self.play(g,'trigger',find(g.state,'fatal.wait'));before=g.snapshot()
        from hs_sim.engine.deathrattle_acceptance import validate_terminal_queue
        called=[]
        def collide(r,queue):
            carrier=find(r.state,'false.source');identity=r.state.entities[find(r.state,'beast')].dormancy.id
            r.state.entities[carrier].abilities=[replace(a,id=identity)if a.kind=='deathrattle_repeat'else a for a in r.state.entities[carrier].abilities]
            called.append(True);return validate_terminal_queue(r,queue)
        with patch('hs_sim.engine.deathrattle_acceptance.validate_terminal_queue',side_effect=collide),self.assertRaises(ResolutionError):self.choose(g)
        self.assertTrue(called);self.assertEqual(g.snapshot(),before);self.finish(g)

    def test_match_budget_rejects_before_allocation_but_false_huge_source_does_not(self):
        self.source('huge',spec(100001,tribes=('dragon',)))
        g=self.game(hand=('trigger',),board=('dragon.rattle','huge'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'trigger',find(g.state,'dragon.rattle'))
        self.assertEqual(g.snapshot(),before)
        other=self.game(hand=('trigger',),board=('beast.rattle','huge'));self.play(other,'trigger',find(other.state,'beast.rattle'))
        self.assertEqual(self.armor(other),1);self.assertEqual(len(other.state.deathrattle_history),1);self.portable(other)

    def test_choice_rng_then_registered_failure_rolls_back_only_current_action(self):
        def fail(c):raise ValueError('registered failure after RNG')
        self.behavior('fail',fail);self.behavior('bad.choice',lambda c:[ask(c,
            RandomDamage((c.state.players[1].hero_id,c.state.players[2].hero_id),1,c.source_id),
            InvokeBehavior('fail',c.source_id,c.player_id))])
        self.minion('bad.choice','bad.choice',tribes=('dragon',));g=self.waiting(board=('bad.choice','tribal.source'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def rewind_fixture(self,retained):
        self.behavior('erase.source',lambda c:[GainArmor(c.player_id,1),Silence(find(c.state,'conditional.source'))])
        self.minion('rewind.body','erase.source',tribes=('dragon',))
        self.script('rewinder',lambda c:[TriggerDeathrattles(find(c.state,'rewind.body'),c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rewind.body','conditional.source','beast')+ (('retainer',)if retained else ()))
        self.play(g,'rewinder')
        if not retained:self.choose(g,'retry')
        return g

    def test_normal_rewind_restores_condition_and_replaces_abandoned_group(self):
        g=self.rewind_fixture(False);self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.deathrattle_batches),1);self.assertEqual(self.counts(g),[2]);self.portable(g)

    def test_retained_rewind_keeps_old_group_and_recaptures_changed_condition(self):
        g=self.rewind_fixture(True);self.assertEqual(self.armor(g),3);self.assertEqual([self.counts(g,i)for i in range(2)],[[2],[1]]);self.portable(g)

    def test_weapon_recipient_kind_can_match_without_irrelevant_tribe_metadata(self):
        self.source('all.kind',spec(kinds=(CardType.WEAPON,),tribes=None));self.source('tribal.kind',spec(3,kinds=(CardType.WEAPON,),tribes=('dragon',)))
        self.script('replace',lambda c:[EquipWeapon(1,'weapon')]);g=self.game(hand=('replace',),board=('all.kind','tribal.kind'),weapon='weapon.rattle');self.play(g,'replace')
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.deathrattle_history[0].capture.kind,CardType.WEAPON);self.portable(g)

    def test_location_recipient_has_no_minion_tribes_even_with_unknown_metadata(self):
        self.source('location.kind',spec(kinds=(CardType.LOCATION,)));self.source('location.tribe',spec(3,kinds=(CardType.LOCATION,),tribes=('dragon',)))
        self.script('destroy.loc',lambda c:[DestroyLocation(find(c.state,'location.rattle'))]);g=self.game(hand=('destroy.loc',),board=('location.rattle','location.kind','location.tribe'));self.play(g,'destroy.loc')
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.deathrattle_history[0].capture.kind,CardType.LOCATION);self.portable(g)

    def magnetic_fixture(self,tribe):
        self.minion('host','armor',tribes=('mech',));self.minion('part','armor',tribes=('dragon',),keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))
        self.source('filter',spec(3,tribes=(tribe,),origins=('granted',)))
        g=self.game(hand=('part','kill'),board=('host','filter'));self.play(g,'part',position=0);self.play(g,'kill',find(g.state,'host'));return g

    def test_magnetic_donor_tribe_does_not_replace_receiver_tribe(self):
        g=self.magnetic_fixture('dragon');self.assertEqual(self.counts(g),[1,1]);self.assertEqual(self.armor(g),2)
        self.assertEqual(self.batch(g).payloads[1].ability.deathrattle_card_id,'part');self.portable(g)

    def test_magnetic_granted_origin_matches_host_printed_tribe(self):
        g=self.magnetic_fixture('mech');self.assertEqual(self.counts(g),[1,3]);self.assertEqual(self.armor(g),4);self.portable(g)

    def test_starship_component_face_and_granted_origin_remain_separate(self):
        self.minion('ship',health=0,tribes=('mech',),starship_for=(CardClass.NEUTRAL,))
        self.minion('piece','armor',tribes=('dragon',),keywords=(Keyword.STARSHIP_PIECE,))
        self.script('ship.grant',lambda c:[GrantDeathrattleRepeatAura(c.target_id,spec(3,scope='self',origins=('granted',),tribes=('mech',)),c.source_id),GrantDeathrattle(c.target_id,'armor',c.source_id)],target=True)
        g=self.game(hand=('kill','ship.grant','kill'),board=('piece',));self.play(g,'kill',find(g.state,'piece'));ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id))
        self.play(g,'ship.grant',ship.id);self.play(g,'kill',ship.id)
        self.assertEqual(self.counts(g),[1,3]);self.assertEqual(self.batch(g).payloads[0].ability.deathrattle_card_id,'piece')
        self.assertEqual(self.armor(g),5);self.portable(g)

    def test_private_match_fields_are_strict_in_current_history_and_Frame(self):
        g=self.waiting()
        for route in ('state','frame'):
            s=g.snapshot()
            if route=='state':
                declaration=s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0]['ability']['deathrattle_repeat'];declaration.pop('match')
            else:
                declaration=self.nodes(s['resolution_frame'],'DeathrattleRepeatSpec')[0];declaration['fields']['unknown']=None
            with self.subTest(route=route):self.reject(s)

    def test_both_players_observation_commands_events_are_detached_and_private(self):
        self.policy('policy',(spec(tribes=('dragon',)),),duration=2)
        g=self.game(hand=('policy','trigger'),board=('dragon.wait','conditional.source','beast'),enemy_hand=('unknown.tribes',));self.play(g,'policy');self.play(g,'trigger',find(g.state,'dragon.wait'))
        before=g.snapshot();forbidden=('deathrattle_batches','deathrattle_history','contributors','spec_index','DeathrattleRecipient','FinishDeathrattleBatch','source_eligibility','profile_id','resolution_frame','rng_state')
        for player in (1,2):
            port=g.for_player(player);view=port.observe();actions=port.legal_actions();events=port.events();encoded=json.dumps((view,actions,events),sort_keys=True)
            for name in forbidden:self.assertNotIn('"'+name+'"',encoded)
            view['observation']['players'][0]['hero']['armor']=999
            self.assertEqual(g.snapshot(),before)
            if player==1:self.assertNotIn('unknown.tribes',encoded)
        self.finish(g);self.assertEqual(self.armor(g),2)

    def test_native_independent_registry_composition_has_natural_and_effect_waits(self):
        from examples.deathrattle_matching import run
        game,waiting,summary=run()
        self.assertEqual(len(waiting),8)
        self.assertTrue(summary['restored_cloned_replayed_every_wait'])
        self.assertEqual(summary['group_origins'],['death','effect','death'])
        self.assertFalse(summary['official_cn_calibrated']);self.assertEqual(summary['representative_cards_added'],0)
        self.assertTrue(all(r.completed for r in game.state.deathrattle_history))


if __name__ == '__main__':
    unittest.main()
