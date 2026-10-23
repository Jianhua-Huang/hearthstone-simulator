"""Real shuffle Quest, native hero and original-corpse return boundaries."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards import native_master_dusk_cards as cards
from hs_sim.cards.native_master_dusk_cards import QUEST, DUSK, POWER, NINJA, PROGRAM, PREFIX
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Registry, RewindSpec, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dead_minion_shuffles import ShuffleDeadMinion
from hs_sim.engine.deck_shuffles import ShuffleDeckCards, shuffled
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    DestroyBatch, InvokeBehavior, RequestChoice, ShuffleIntoDeck, Silence, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, DrawMatching
from hs_sim.targets import canonical_digest

P = 'k164.'
HERO, BASE_POWER, OTHER_HERO, VICTIM, WATCH = (P + x for x in ('hero', 'power', 'other_hero', 'victim', 'watch'))
ONE, FIVE, TOP, UNKNOWN, KILL, ALL, DRAW, SILENCE, BUFF, GIVE, TAKE, TRANSFORM, REWIND, WOUND, FOE, FILL = (
    P + x for x in ('one', 'five', 'top', 'unknown', 'kill', 'all', 'draw', 'silence', 'buff',
        'give', 'take', 'transform', 'rewind', 'wound', 'foe', 'fill'))
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes() + cards.BATCH_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def production():
    r = build_registry(); r.freeze(); return r


def corpse(c):
    death = next(d for d in c.state.death_history if d.id == dict(c.event.data)['death_id'])
    return SourceAllocationFact.capture(c.state, c.state.entities[death.entity_id]), death


@lru_cache(maxsize=None)
def registry(mode=None, role='writer', pin=SOURCE_PIN):
    if role not in ('writer', 'reader') or pin != SOURCE_PIN:
        raise AssertionError('Incomplete independent fixture identity')
    actual = production(); r = Registry('k164-isolated-' + str(mode))
    for cid in (NINJA, POWER):
        r.register_card(actual.card(cid)); r.register_pool_card(PoolCard.from_definition(actual.card(cid)))
    progress = actual.card(NINJA).hand_progress
    r.register_trigger_condition(progress.condition_id, actual.trigger_condition(progress.condition_id))
    for name in (progress.on_complete, 'cards.simple_followup_p71.shell',
                 'cards.simple_followup_p71.shell_next', 'cards.simple_followup_p71.shell_draw'):
        r.register_behavior(name, actual.behavior(name))
    cards.register_native_master_dusk_cards(r)
    r.register_behavior(P + 'empty', lambda c: ())
    r.register_card(CardDefinition(BASE_POWER, BASE_POWER, CardType.HERO_POWER, on_use=P + 'empty'))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30, initial_hero_power=BASE_POWER))
    r.register_card(CardDefinition(OTHER_HERO, OTHER_HERO, CardType.HERO, cost=1, health=30,
        hero_card=True, hero_armor=2, initial_hero_power=BASE_POWER))
    r.register_card(CardDefinition(VICTIM, VICTIM, CardType.MINION, cost=1, attack=2, health=5))
    def batch(c, count=1, recipient=None):
        pid = c.player_id if recipient is None else recipient
        return shuffled(c, tuple(AddToDeck(pid, VICTIM, source_id=c.source_id) for _ in range(count)), player_id=pid)
    def draw(c): return (DrawMatching(c.player_id, PoolQuery(), 'skip', card_ids=(NINJA,), source_id=c.source_id),)
    bodies = {ONE: batch, FIVE: lambda c: batch(c, 5), TOP: lambda c: (AddToDeck(c.player_id, VICTIM, position='top', source_id=c.source_id),),
        UNKNOWN: lambda c: (AddToDeck(c.player_id, VICTIM, source_id=c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        ALL: lambda c: (DestroyBatch(tuple(c.state.players[c.player_id].board), c.source_id),),
        DRAW: draw, SILENCE: lambda c: (Silence(c.target_id),), BUFF: lambda c: (Buff(c.target_id, 4, 5, c.source_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3 - c.player_id),),
        TAKE: lambda c: (ChangeControl(c.state.players[3 - c.player_id].board[0], c.player_id),),
        FOE: lambda c: (Destroy(c.state.players[3 - c.player_id].board[0], c.source_id),),
        TRANSFORM: lambda c: (Transform(c.target_id, VICTIM),),
        REWIND: lambda c: (Destroy(c.target_id, c.source_id),),
        WOUND: lambda c: (Damage(c.state.players[c.player_id].hero_id, 5, c.source_id, DamageKind.EFFECT),),
        P + 'theirs': lambda c: batch(c, recipient=3 - c.player_id),
        FILL: lambda c: tuple(AddToHand(c.player_id, VICTIM, c.source_id) for _ in range(10)) + batch(c)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        targeted = cid in (KILL, SILENCE, BUFF, GIVE, TRANSFORM, REWIND)
        extra = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if cid == REWIND else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if targeted else None, **extra))
    def fail(c): raise ResolutionError('K164 deliberate accepted continuation failure')
    r.register_behavior(P + 'fail', fail)
    if mode:
        event = 'minion_died' if mode == 'death' else 'minion_summoned' if mode == 'entry' else 'card_shuffled'
        def eligible(c):
            target = c.state.entities.get(c.event.target_id)
            return target is not None and target.card_id == NINJA if mode in ('death', 'entry') else c.event.player_id == 1
        def watch(c):
            if mode == 'shuffle_fail': return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            if mode == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id, DamageKind.EFFECT),)
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),))]
            if mode == 'entry': options.append(ChoiceOption('kill', 'Kill first original Ninja', (Destroy(c.event.target_id, c.source_id),)))
            if mode == 'death':
                fact, death = corpse(c)
                request = ShuffleDeckCards(1, 1, (ShuffleDeadMinion(fact, death, 1, c.source_id),), c.source_id)
                options.extend((ChoiceOption('early', 'Return original before old listener', (request,)),
                    ChoiceOption('cycle', 'Return, redraw and kill this same physical Ninja', (request,
                        DrawMatching(1, PoolQuery(), 'skip', card_ids=(NINJA,), source_id=c.source_id),
                        Destroy(fact.entity_id, c.source_id)))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(P + 'watch', watch); r.register_trigger_condition(P + 'eligible', eligible)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=50,
            limited_triggers=(LimitedTriggerSpec(event, P + 'watch', condition_id=P + 'eligible', uses=1),)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class NativeMasterDuskTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode=None, active=1, deck=(VICTIM,) * 8):
        self.mode = mode
        if mode: board = (WATCH,) + tuple(board)
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40), PlayerSetup(HERO, hand=enemy_hand, board=enemy,
            deck=(VICTIM,) * 8, mana=40, max_mana=40, mana_cap=40)), active_player=active, seed=164), registry(mode))
    def first(self, g, cid, zone='board', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None, pid=1):
        entity = self.first(g, cid, 'hand', pid); g.apply(PlayCard(pid, entity.id, target_id=target,
            position=len(g.state.players[pid].board) if entity.kind == CardType.MINION else None)); return entity.id
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def value(self, g): return self.first(g, QUEST, 'quests').quest_progress.value
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(self.mode, 'reader')
        self.assertIsNot(g.registry, reader)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved); self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('rng_state', 'resolution_frame', 'source_allocation', 'death_history', 'deck_shuffle_history', 'zone_epoch'):
                self.assertNotIn('"' + key + '"', public)
    def ninja_ids(self, g, pid=1): return [i for i in g.state.players[pid].board if g.state.entities[i].card_id == NINJA]

    def test_a0_complete_source_and_existing_ninja_power_definitions_remain_exact(self):
        from tools.card_batch import check_face
        d = cards.load_batch(); self.assertEqual(len(d['official_observations']), 8)
        rows = {x['record']['id']: x['record'] for x in d['cards'] + d['existing_dependencies']}
        for o in d['official_observations']: check_face(rows[o['card_id']], o['face'], o['locale'])
        r = production(); self.assertEqual((r.card(QUEST).cost, r.card(DUSK).hero_armor), (1, 8))
        self.assertEqual(r.card(DUSK).initial_hero_power, POWER)
        for cid, pin in d['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), pin['sha256'])

    def test_a1_quest_counts_five_operations_not_cards_and_has_no_retroactive_credit(self):
        g = self.game((ONE, QUEST, FIVE, ONE, ONE, ONE, ONE)); self.play(g, ONE); self.play(g, QUEST)
        self.assertEqual(self.value(g), 0); self.play(g, FIVE); self.assertEqual(self.value(g), 1)
        for value in (2, 3, 4): self.play(g, ONE); self.assertEqual(self.value(g), value)
        self.play(g, ONE); self.assertFalse(g.state.players[1].quests)
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id == DUSK]), 1); self.portable(g)

    def test_a2_quest_ignores_other_issuer_and_recipient_and_positional_insertions(self):
        g = self.game((QUEST, P + 'theirs', TOP, ONE), enemy_hand=(P + 'theirs',))
        self.play(g, QUEST); self.play(g, P + 'theirs'); self.play(g, TOP); self.assertEqual(self.value(g), 0)
        g.apply(EndTurn(1)); self.play(g, P + 'theirs', pid=2); self.assertEqual(self.value(g), 0)
        g.apply(EndTurn(2)); self.play(g, ONE); self.assertEqual(self.value(g), 1); self.portable(g)

    def test_a3_unknown_shuffle_issuer_rolls_back_instead_of_silently_losing_progress(self):
        g = self.game((QUEST, UNKNOWN)); self.play(g, QUEST); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, UNKNOWN)
        self.assertEqual(g.snapshot(), saved)

    def test_b0_actual_hero_health_armor_power_and_two_attributed_ninjas(self):
        g = self.game((WOUND, DUSK)); self.play(g, WOUND); dusk = self.play(g, DUSK)
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health, hero.armor), (25, 8)); self.assertEqual(len(self.ninja_ids(g)), 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id, POWER)
        self.assertEqual(g.state.players[1].mana, 36)
        self.assertTrue(all(r.request.cause.source.entity_id == dusk for r in g.state.card_summon_history))
        self.assertEqual([e.spec_id for e in g.state.players[1].player_effects], [PROGRAM]); self.portable(g)

    def test_b1_original_ninja_dies_resets_and_redraws_as_same_physical_minion(self):
        g = self.game((DUSK, BUFF, KILL, DRAW)); self.play(g, DUSK); target = self.ninja_ids(g)[0]
        self.play(g, BUFF, target); allocations = g.state.next_entity_id; self.play(g, KILL, target)
        e = g.state.entities[target]; self.assertEqual((e.zone, e.attack, e.health, e.damage), (Zone.DECK, 3, 3, 0))
        self.assertIn(Keyword.STEALTH, e.keywords); self.assertEqual(g.state.next_entity_id, allocations)
        row, = g.state.deck_shuffle_history; self.assertEqual((row.actor_id, row.player_id, row.first_card.entity_id), (1, 1, target))
        self.play(g, DRAW); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertEqual(len(g.state.draw_history), 2); self.portable(g)

    def test_b2_opponent_kill_preserves_program_issuer_and_own_deck(self):
        g = self.game((DUSK,), enemy_hand=(FOE,)); self.play(g, DUSK); target = self.ninja_ids(g)[0]
        g.apply(EndTurn(1)); self.play(g, FOE, pid=2)
        row, = g.state.deck_shuffle_history; self.assertEqual((row.actor_id, row.player_id), (1, 1))
        self.assertEqual(row.source.entity_id, g.state.players[1].player_effects[0].source_id); self.portable(g)

    def test_b3_silence_does_not_remove_global_rule_and_other_current_faces_do_not_match(self):
        g = self.game((DUSK, SILENCE, TRANSFORM, KILL, KILL)); self.play(g, DUSK); a, b = self.ninja_ids(g)
        self.play(g, SILENCE, a); self.play(g, TRANSFORM, b); self.play(g, KILL, a); self.play(g, KILL, b)
        self.assertEqual((g.state.entities[a].zone, g.state.entities[b].zone), (Zone.DECK, Zone.GRAVEYARD))
        self.assertEqual(len(g.state.deck_shuffle_history), 1); self.portable(g)

    def test_b4_controlled_enemy_owned_ninja_uses_death_controller_without_changing_owner(self):
        g = self.game((DUSK, TAKE, KILL), enemy=(NINJA,)); self.play(g, DUSK)
        target = self.ninja_ids(g, 2)[0]; self.play(g, TAKE); self.play(g, KILL, target)
        e = g.state.entities[target]; self.assertEqual((e.owner, e.controller, e.zone), (2, 1, Zone.DECK)); self.portable(g)

    def test_b5_hero_replacement_keeps_persistent_rule_and_stacked_instances_shuffle_once(self):
        g = self.game((DUSK, DUSK, OTHER_HERO, KILL)); self.play(g, DUSK); self.play(g, DUSK)
        target = self.ninja_ids(g)[0]; self.play(g, OTHER_HERO); self.assertEqual(len(g.state.players[1].player_effects), 2)
        self.play(g, KILL, target); self.assertEqual(len(g.state.deck_shuffle_history), 1)
        self.assertEqual(g.state.entities[target].zone, Zone.DECK); self.portable(g)

    def test_c0_entry_wait_uses_written_summons_then_program_installation(self):
        g = self.game((DUSK,), mode='entry'); self.play(g, DUSK)
        self.assertFalse(g.state.players[1].player_effects); target = self.ninja_ids(g)[0]; self.portable(g)
        self.choose(g, 'kill'); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertFalse(g.state.deck_shuffle_history); self.assertEqual(len(g.state.players[1].player_effects), 1); self.portable(g)

    def test_c1_death_wait_restore_failure_and_original_early_return_do_not_shuffle_twice(self):
        g = self.game((DUSK, KILL), mode='death'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, KILL, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'early')
        self.assertEqual(g.state.entities[target].zone, Zone.DECK); self.assertEqual(len(g.state.deck_shuffle_history), 1)
        self.assertTrue(any(e.kind == 'effect_skipped' and e.target_id == target and
            dict(e.data).get('effect') == 'ShuffleDeadMinion' for e in g.events)); self.portable(g)

    def test_c2_old_queued_death_cannot_borrow_same_entity_after_redraw_and_second_death(self):
        g = self.game((DUSK, KILL), mode='death'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, KILL, target)
        self.portable(g); self.choose(g, 'cycle')
        rows = [d for d in g.state.death_history if d.entity_id == target]; self.assertEqual(len(rows), 2)
        self.assertEqual(len(g.state.deck_shuffle_history), 2); self.assertEqual(g.state.entities[target].zone, Zone.DECK); self.portable(g)

    def test_c3_shuffle_failure_rolls_back_whole_kill_and_terminal_preserves_insert(self):
        g = self.game((DUSK, KILL), mode='shuffle_fail'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, KILL, target)
        self.assertEqual(g.snapshot(), saved)
        g = self.game((DUSK, KILL), mode='terminal'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, KILL, target)
        self.assertEqual(g.state.status, 'finished'); self.assertEqual(g.state.entities[target].zone, Zone.DECK)
        self.assertEqual(len(g.state.deck_shuffle_history), 1); self.portable(g)

    def test_c4_real_rewind_retires_old_shuffle_and_keeps_one_final_payment(self):
        g = self.game((DUSK, REWIND)); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, REWIND, target)
        self.portable(g); self.choose(g, 'retry')
        self.assertEqual((len(g.state.deck_shuffle_history), len(g.state.death_history), g.state.players[1].mana), (1, 1, 36))
        self.assertEqual(g.state.entities[target].zone, Zone.DECK); self.portable(g)

    def test_d0_strict_original_death_codec_and_old_zone_limits_remain(self):
        g = self.game((DUSK, KILL), mode='death'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, KILL, target)
        death = g.state.death_history[-1]; fact = SourceAllocationFact.capture(g.state, g.state.entities[target])
        request = ShuffleDeadMinion(fact, death, 1, g.state.players[1].hero_id)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(request)))), request)
        for edit in (dict(player_id=True), dict(player_id=2), dict(card=replace(fact, zone_epoch=fact.zone_epoch + 1))):
            with self.assertRaises(ValueError): replace(request, **edit)
        with self.assertRaises(ValueError): CardReference.capture(g.state.entities[target])
        self.assertIsInstance(ShuffleIntoDeck(target, 1), ShuffleIntoDeck)
        with self.assertRaises(ValueError): codec.encode(replace(request, death=replace(death, id=999)))
        with self.assertRaises(ValueError): codec.encode(replace(request, card=replace(fact, next_entity_id=g.state.next_entity_id + 1)))
        self.portable(g)

    def test_d1_rehashed_queued_original_death_substitution_is_rejected(self):
        g = self.game((DUSK, KILL), mode='death'); self.play(g, DUSK); target = self.ninja_ids(g)[0]; self.play(g, KILL, target)
        bad = deepcopy(g.snapshot()); changed = 0
        def edit(value):
            nonlocal changed
            if isinstance(value, dict):
                if value.get('type') == 'hs_sim.engine.dead_minion_shuffles.ShuffleDeadMinion':
                    value['fields']['player_id'] = True; changed += 1
                else:
                    for item in value.values(): edit(item)
            elif isinstance(value, list):
                for item in value: edit(item)
        edit(bad); self.assertGreater(changed, 0)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry(self.mode, 'reader'))
        self.portable(g)

    def test_e0_full_board_hero_still_installs_rule_without_ninja_or_summon_rng(self):
        g = self.game((DUSK,), board=(VICTIM,) * 7); before = g._rng.getstate(); self.play(g, DUSK)
        self.assertFalse(self.ninja_ids(g)); self.assertEqual(len(g.state.players[1].player_effects), 1)
        self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertTrue(all(r.selected is None for r in g.state.card_summon_history))
        self.assertEqual(g._rng.getstate(), before); self.portable(g)

    def test_e1_full_hand_reward_waits_then_delivers_once_and_releases_completed_quest(self):
        g = self.game((QUEST, ONE, ONE, ONE, ONE, FILL)); self.play(g, QUEST)
        for _ in range(4): self.play(g, ONE)
        self.play(g, FILL); self.assertFalse(g.state.players[1].quests)
        self.assertEqual(len(g.state.players[1].hand), 10)
        row, = g.state.quest_hand_rewards
        self.assertEqual((row.phase, row.request.instruction.card_id), ('pending', DUSK))
        self.assertFalse(any(e.card_id == DUSK for e in g.state.entities.values()))
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events)); self.portable(g)
        before = g._rng.getstate(); self.play(g, VICTIM)
        row, = g.state.quest_hand_rewards; reward = g.state.entities[row.delivery.entity_id]
        self.assertEqual((row.phase, reward.card_id, reward.zone), ('delivered', DUSK, Zone.HAND))
        self.assertEqual(g._rng.getstate(), before)
        self.play(g, VICTIM)
        self.assertEqual(sum(e.card_id == DUSK for e in g.state.entities.values()), 1); self.portable(g)

    def test_e2_simultaneous_ninjas_keep_independent_deaths_and_semantic_operations(self):
        g = self.game((DUSK, ALL)); self.play(g, DUSK); targets = set(self.ninja_ids(g)); self.play(g, ALL)
        self.assertEqual({r.first_card.entity_id for r in g.state.deck_shuffle_history}, targets)
        self.assertEqual(len(g.state.deck_shuffle_history), 2)
        self.assertTrue(all(g.state.entities[i].zone == Zone.DECK for i in targets)); self.portable(g)

    def test_e3_departed_controller_ninja_does_not_use_old_players_program(self):
        g = self.game((DUSK, GIVE, FOE)); self.play(g, DUSK); target = self.ninja_ids(g)[0]
        self.play(g, GIVE, target); self.play(g, FOE)
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].zone), (2, Zone.GRAVEYARD))
        self.assertFalse(g.state.deck_shuffle_history); self.portable(g)


if __name__ == '__main__': unittest.main()
