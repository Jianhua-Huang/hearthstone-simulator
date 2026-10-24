"""Actual Test Subject casts, residence, copied memory and ordinary deck delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_targeted_spell_memory_cards import (
    SUBJECT, load_batch, register_past_targeted_spell_memory_cards)
from hs_sim.engine import (CardDefinition, CardType, CounterSpell, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SecretSpec, SetSecret, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.deathrattle_memory import ShuffleRememberedTargetSpell
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    Damage, DestroyBatch, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import TargetSpec, RewindSpec, DeathrattleRepeatSpec, SpellRepeatSpec, DamageKind
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard
from tools import card_batch as batch

P = 'k496.'
HERO, POWER, A, WATCH, DOUBLE = (P+x for x in ('hero', 'power', 'plain', 'watch', 'double'))


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry(version='fixture-k496-'+mode)
    r.register_behavior(P+'empty', lambda c: ())
    r.register_card(CardDefinition(POWER, 'Power', CardType.HERO_POWER, on_use=P+'empty'))
    r.register_card(CardDefinition(HERO, 'Hero', CardType.HERO, health=30, initial_hero_power=POWER))
    r.register_card(CardDefinition(A, 'Plain', CardType.MINION, attack=1, health=12))
    register_past_targeted_spell_memory_cards(r)
    from hs_sim.cards.torch_card import register_torch_card
    register_torch_card(r)
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    scripts = {
        'buff': lambda c: (Buff(c.target_id, 0, 2, c.source_id),),
        'noop': lambda c: (),
        'scratch': lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'base': lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, A),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'sweep': lambda c: (DestroyBatch(tuple(i for p in c.state.players.values() for i in p.board), c.source_id),),
        'arm': lambda c: (SetSecret(2, P+'secret'),),
        'auto': lambda c: (CastSpell(c.player_id, P+'buff', c.source_id,
            next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == SUBJECT),
            targeting='explicit'),),
        'wait': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'explode', c.source_id, c.player_id),)),
            ), source_id=c.source_id),),
    }
    def fail(c):
        raise ResolutionError('k496 deliberate payload failure')
    r.register_behavior(P+'explode', fail)
    scripts['fail'] = lambda c: (InvokeBehavior(P+'explode', c.source_id, c.player_id),)
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name,
            targeting=None if name in ('auto', 'sweep', 'arm') else target))
    from hs_sim.engine.spell_target_groups import SpellTargetGroupProfile
    r.register_card(CardDefinition(P+'dual', 'Two actual arrows', CardType.SPELL, on_play=P+'buff', targeting=target))
    r.register_spell_target_group_profile(SpellTargetGroupProfile(P+'dual', 'k496-two-original-arrows'))
    r.register_secret_condition(P+'counter_condition', lambda c: c.window is not None and
        c.window.kind == 'spell' and c.window.player_id != c.player_id and not c.window.countered)
    r.register_behavior(P+'counter', lambda c: (CounterSpell(c.window.id),))
    r.register_card(CardDefinition(P+'secret', 'Counter probe', CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(P+'secret', ('card_committed',), P+'counter_condition', P+'counter')))
    def observe(c):
        if c.event.kind == 'spell_cast_accepted' and c.event.target_id is not None:
            entity = c.state.entities[c.event.target_id]
            if entity.card_id != SUBJECT:
                return ()
            if mode == 'accept_copy':
                return (CopyMinion(entity.id, c.player_id),)
            if mode != 'accept_wait':
                return ()
        elif c.event.kind == 'card_added_to_deck':
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != SUBJECT:
                return ()
            if mode == 'deck_fail':
                return (InvokeBehavior(P+'explode', c.source_id, c.player_id),)
            if mode != 'deck_wait':
                return ()
        else:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'explode', c.source_id, c.player_id),)),
            ), source_id=c.source_id),)
    r.register_behavior(P+'observe', observe)
    r.register_card(CardDefinition(WATCH, 'Observer', CardType.MINION, health=8,
        triggers=(TriggerSpec('spell_cast_accepted', P+'observe'), TriggerSpec('card_added_to_deck', P+'observe'))))
    r.register_card(CardDefinition(DOUBLE, 'Repeat source', CardType.MINION, health=8,
        deathrattle_repeats=(DeathrattleRepeatSpec(),)))
    r.register_card(CardDefinition(P+'cast_double', 'Cast repeat source', CardType.MINION, health=8,
        spell_repeats=(SpellRepeatSpec(2, class_mode='any'),)))
    if mode == 'retry':
        r.register_card(CardDefinition(P+'retry', 'Retry probe', CardType.SPELL,
            targeting=target, on_play=P+'buff', keywords=(Keyword.REWIND,), rewind=RewindSpec()))
    r.validate()
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class PastTargetedSpellMemoryTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, board=(SUBJECT,), enemy=(), enemy_hand=(), mode='normal'):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=tuple(hand), board=tuple(board),
            deck=(A,)*8, mana=10, max_mana=10), PlayerSetup(HERO, hand=tuple(enemy_hand),
            board=tuple(enemy), deck=(A,)*8, mana=10, max_mana=10)), seed=496), fixture(mode))

    def subject(self, g, player=1):
        return self.entity(g, SUBJECT, player, zone='board')

    def memory(self, g, source):
        return next(a.deathrattle_memory for a in g.state.entities[source].abilities if a.deathrattle_memory is not None)

    def remembered(self, g, source):
        return tuple(x.spell.origin.card_id for x in self.memory(g, source).targeted_spells)

    def copies(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].deck if g.state.entities[i].card_id != A]

    def test_complete_source_zero_attack_and_two_full_primary_faces(self):
        d = load_batch(); raw = d['dependencies'][0]['record']
        self.assertIsNone(raw['attack']); self.assertEqual(fixture().card(SUBJECT).attack, 0)
        self.assertEqual(d['numeric_normalizations'], {SUBJECT: {'attack': 0}})
        self.assertEqual(len(d['official_observations']), 2)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']), o['response_sha256'])
            batch.check_face(raw, o['face'], o['locale'], numeric_normalizations={'attack': 0})

    def test_actual_constructed_boundary_adds_one_complete_definition(self):
        from hs_sim.cards import build_registry
        r = batch.registration_prefix(build_registry,
            'hs_sim.cards.past_targeted_spell_memory_cards.register_past_targeted_spell_memory_cards',
            register_past_targeted_spell_memory_cards, after=True)
        self.assertEqual(len(r.cards), 2697); self.assertEqual(r.card(SUBJECT), fixture().card(SUBJECT))

    def test_paid_subject_starts_empty_without_battlecry_or_spell_history(self):
        g = self.game((SUBJECT,), board=()); source = self.play(g, SUBJECT)
        self.assertEqual(self.remembered(g, source), ()); self.assertFalse(g.state.cast_history)
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.amount, 1)

    def test_own_buff_and_killing_spell_both_shuffle_once_before_lethal(self):
        g = self.game((P+'buff', P+'kill')); source = self.subject(g).id
        self.play(g, P+'buff', source); killer = self.play(g, P+'kill', source)
        copies = self.copies(g)
        self.assertCountEqual([e.card_id for e in copies], [P+'buff', P+'kill'])
        self.assertEqual(len(g.state.cast_history), 2); self.assertEqual(len(g.state.death_history), 1)
        self.assertTrue(all(e.id != e.origin_entity_id for e in copies))
        self.assertIn(killer, [e.origin_entity_id for e in copies]); self.portable(g)

    def test_same_face_two_physical_casts_keep_two_weights(self):
        g = self.game((P+'buff', P+'buff', P+'sweep')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'buff', source)
        self.assertEqual(self.remembered(g, source), (P+'buff', P+'buff'))
        self.play(g, P+'sweep'); self.assertEqual([e.card_id for e in self.copies(g)], [P+'buff']*2)

    def test_other_minion_and_targetless_aoe_do_not_become_memories(self):
        g = self.game((P+'buff', P+'sweep'), board=(SUBJECT, A)); source = self.subject(g).id
        self.play(g, P+'buff', self.entity(g, A, zone='board').id)
        self.assertFalse(self.remembered(g, source)); self.play(g, P+'sweep')
        self.assertFalse(self.copies(g))

    def test_opponent_cast_on_subject_is_excluded(self):
        g = self.game(enemy_hand=(P+'buff', P+'kill')); source = self.subject(g).id
        g.apply(EndTurn(1)); self.play(g, P+'buff', source, player=2); self.play(g, P+'kill', source, player=2)
        self.assertFalse(self.copies(g)); self.assertFalse(self.copies(g, 2)); self.portable(g)

    def test_automatic_targeted_cast_is_a_distinct_actual_spell(self):
        g = self.game((P+'auto', P+'sweep')); source = self.subject(g).id
        self.play(g, P+'auto'); self.assertEqual(self.remembered(g, source), (P+'buff',))
        self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'effect'])
        self.play(g, P+'sweep'); self.assertEqual([e.card_id for e in self.copies(g)], [P+'buff'])

    def test_copy_inherits_full_memory_and_each_recipient_grows_independently(self):
        g = self.game((P+'buff', P+'copy', P+'noop', P+'sweep')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'copy', source)
        clone = next(i for i in g.state.players[1].board if i != source)
        self.assertEqual(self.remembered(g, clone), (P+'buff', P+'copy'))
        self.play(g, P+'noop', clone)
        self.assertEqual(self.remembered(g, source), (P+'buff', P+'copy'))
        self.assertEqual(self.remembered(g, clone), (P+'buff', P+'copy', P+'noop'))
        self.play(g, P+'sweep'); self.assertEqual(len(self.copies(g)), 5); self.portable(g)

    def test_base_copy_has_fresh_empty_native_memory(self):
        g = self.game((P+'buff', P+'base')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'base', source)
        clone = next(i for i in g.state.players[1].board if i != source)
        self.assertEqual(self.remembered(g, clone), ())

    def test_silence_removes_recording_and_frozen_death_body(self):
        g = self.game((P+'buff', P+'silence', P+'sweep')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'silence', source); self.play(g, P+'sweep')
        self.assertFalse(self.copies(g))

    def test_transformation_does_not_keep_subject_memory(self):
        g = self.game((P+'buff', P+'transform', P+'sweep')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'transform', source); self.play(g, P+'sweep')
        self.assertFalse(self.copies(g))

    def test_bounce_and_actual_replay_reset_old_residence_memory(self):
        g = self.game((P+'buff', P+'bounce', P+'noop')); source = self.subject(g).id
        self.play(g, P+'buff', source); old = self.memory(g, source).targeted_spells[0].residence
        self.play(g, P+'bounce', source); self.play(g, SUBJECT); self.play(g, P+'noop', source)
        self.assertEqual(self.remembered(g, source), (P+'noop',))
        self.assertNotEqual(self.memory(g, source).targeted_spells[0].residence, old); self.portable(g)

    def test_changed_controller_receives_carried_memory_in_its_own_deck(self):
        g = self.game((P+'buff', P+'control', P+'kill')); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'control', source); self.play(g, P+'kill', source)
        self.assertFalse(self.copies(g))
        self.assertCountEqual([e.card_id for e in self.copies(g, 2)], [P+'buff', P+'control']); self.portable(g)

    def test_accepted_cast_observer_sees_memory_before_payload(self):
        g = self.game((P+'buff',), board=(SUBJECT, WATCH), mode='accept_copy'); source = self.subject(g).id
        self.play(g, P+'buff', source)
        clone = next(i for i in g.state.players[1].board if i not in (source, self.entity(g, WATCH, zone='board').id))
        self.assertEqual(self.remembered(g, clone), (P+'buff',))
        self.assertEqual(g.state.entities[clone].max_health, 2)

    def test_acceptance_wait_restores_clones_and_replays_with_original_memory(self):
        g = self.game((P+'buff',), board=(SUBJECT, WATCH), mode='accept_wait'); source = self.subject(g).id
        self.play(g, P+'buff', source); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.remembered(g, source), (P+'buff',)); restored = self.portable(g)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())

    def test_failed_payload_rolls_back_memory_and_actual_cast_together(self):
        g = self.game((P+'fail',)); source = self.subject(g).id; before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, P+'fail', source)
        self.assertEqual(g.snapshot(), before)

    def test_failed_choice_rolls_back_to_same_memory_and_resumes(self):
        g = self.game((P+'wait',)); source = self.subject(g).id
        self.play(g, P+'wait', source); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.portable(g)

    def test_deck_delivery_wait_preserves_remaining_original_shuffles(self):
        g = self.game((P+'buff', P+'noop', P+'kill'), board=(SUBJECT, WATCH), mode='deck_wait')
        source = self.subject(g).id; self.play(g, P+'buff', source); self.play(g, P+'noop', source)
        self.play(g, P+'kill', source); self.assertEqual(len(self.copies(g)), 1); self.portable(g)
        while g.state.pending_choice is not None:
            self.choose(g)
        self.assertEqual(len(self.copies(g)), 3); self.portable(g)

    def test_failed_shuffle_reaction_rolls_back_death_and_all_insertions(self):
        g = self.game((P+'buff', P+'kill'), board=(SUBJECT, WATCH), mode='deck_fail'); source = self.subject(g).id
        self.play(g, P+'buff', source); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, P+'kill', source)
        self.assertEqual(g.snapshot(), before)

    def test_same_death_repeated_body_shuffles_full_original_memory_each_time(self):
        g = self.game((P+'buff', P+'kill'), board=(SUBJECT, DOUBLE)); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'kill', source)
        self.assertCountEqual([e.card_id for e in self.copies(g)], [P+'buff', P+'kill']*2)

    def test_memory_is_not_in_either_player_dto_or_event_stream(self):
        g = self.game((P+'buff',)); source = self.subject(g).id; self.play(g, P+'buff', source)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            self.assertNotIn('targeted_spells', view); self.assertNotIn('remembered_cast', view)
            self.assertNotIn('next_attachment_id', view)

    def test_foreign_actual_target_or_future_cast_link_is_rejected(self):
        g = self.game((P+'buff',), board=(SUBJECT, A)); source = self.subject(g).id
        self.play(g, P+'buff', source); link = self.memory(g, source).targeted_spells[0]
        from hs_sim.engine.deathrattle_memory import validate_targeted_spell
        with self.assertRaises(ValueError):
            validate_targeted_spell(g.state, g.registry, replace(link, cast_id=link.cast_id+1))
        from hs_sim.engine.allocation_facts import SourceAllocationFact
        from hs_sim.engine.model import BoardPresenceReference
        other = self.entity(g, A, zone='board')
        forged = replace(link, target=SourceAllocationFact.capture(g.state, other),
            residence=BoardPresenceReference.capture(g.state, other.id))
        with self.assertRaises(ValueError): validate_targeted_spell(g.state, g.registry, forged)

    def test_rehashed_snapshot_cannot_borrow_another_actual_cast(self):
        g = self.game((P+'buff', P+'noop'), board=(SUBJECT, A)); source = self.subject(g).id
        self.play(g, P+'buff', source); self.play(g, P+'noop', self.entity(g, A, zone='board').id)
        saved = deepcopy(g.snapshot())
        rows = saved['state']['entities'] if 'state' in saved else saved['entities']
        rows = rows.values() if isinstance(rows, dict) else rows
        entry = next(x for x in rows if x['id'] == source)
        memory = next(a['deathrattle_memory'] for a in entry['abilities'] if a['deathrattle_memory'] is not None)
        memory['targeted_spells'][0]['cast_id'] = 2
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), fixture())

    def test_countered_targeted_spell_is_not_a_memory(self):
        g = self.game((P+'arm', P+'buff')); source = self.subject(g).id
        self.play(g, P+'arm'); self.play(g, P+'buff', source)
        self.assertEqual(g.state.cast_history[-1].failure, 'countered')
        self.assertFalse(self.remembered(g, source)); self.portable(g)

    def test_secondary_actual_spell_arrow_is_recorded(self):
        g = self.game((P+'dual',), board=(SUBJECT, A)); source = self.subject(g).id
        other = self.entity(g, A, zone='board').id; spell = self.entity(g, P+'dual').id
        g.apply(PlayCard(1, spell, other, target_ids=(other, source)))
        self.assertEqual(g.state.cast_history[-1].target_id, other)
        self.assertEqual(self.remembered(g, source), (P+'dual',)); self.portable(g)

    def test_two_targeted_subjects_each_remember_one_cast_not_two(self):
        g = self.game((P+'dual',), board=(SUBJECT, SUBJECT))
        targets = tuple(g.state.players[1].board); spell = self.entity(g, P+'dual').id
        g.apply(PlayCard(1, spell, targets[0], target_ids=targets))
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertEqual([self.remembered(g, i) for i in targets], [(P+'dual',)]*2)

    def test_paid_repeat_is_two_actual_casts_and_one_play(self):
        g = self.game((P+'buff',), board=(SUBJECT, P+'cast_double')); source = self.subject(g).id
        self.play(g, P+'buff', source)
        self.assertEqual(self.remembered(g, source), (P+'buff',)*2)
        self.assertEqual((len(g.state.cast_history), len(g.state.play_history)), (2, 1)); self.portable(g)

    def test_real_retry_discards_old_attempt_memory_and_keeps_one_new_cast(self):
        g = self.game((P+'retry',), mode='retry'); source = self.subject(g).id
        self.play(g, P+'retry', source); self.choose(g, 'retry')
        self.assertEqual(self.remembered(g, source), (P+'retry',))
        self.assertEqual((len(g.state.cast_history), g.state.entities[source].max_health), (1, 4))
        self.portable(g)

    def test_real_returning_spell_recipe_uses_original_seven_not_later_six_or_printed_eight(self):
        from hs_sim.engine.native_spell_values import bound_value
        g = self.game((P+'scratch', P+'scratch', 'CATA_585'), board=(SUBJECT, SUBJECT))
        first, second = g.state.players[1].board
        self.play(g, P+'scratch', first); original = self.play(g, 'CATA_585', first)
        self.assertEqual(bound_value(g.state.entities[original]).amount, 7)
        self.play(g, P+'scratch', second); self.play(g, 'CATA_585', second)
        self.assertEqual(bound_value(g.state.entities[original]).amount, 6)
        torches = [e for e in self.copies(g) if e.card_id == 'CATA_585']
        self.assertEqual(len(torches), 2)
        self.assertCountEqual([None if bound_value(e) is None else bound_value(e).amount for e in torches], [None, 7])
        self.assertTrue(all(e.base_cost == 1 for e in torches)); self.portable(g)

    def test_queued_shuffle_cannot_borrow_future_memory_index(self):
        g = self.game((P+'buff', P+'kill'), board=(SUBJECT, WATCH), mode='deck_wait')
        source = self.subject(g).id; self.play(g, P+'buff', source); self.play(g, P+'kill', source)
        saved = deepcopy(g.snapshot())
        def find(value):
            if isinstance(value, dict):
                if str(value.get('type', '')).endswith('.ShuffleRememberedTargetSpell'):
                    return value
                for child in value.values():
                    found = find(child)
                    if found is not None: return found
            elif isinstance(value, list):
                for child in value:
                    found = find(child)
                    if found is not None: return found
        queued = find(saved['resolution_frame']); self.assertIsNotNone(queued)
        queued['fields']['index'] = 999
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), fixture('deck_wait'))


if __name__ == '__main__':
    unittest.main()
