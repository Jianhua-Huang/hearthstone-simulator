import json
import random
import unittest
from dataclasses import asdict
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_combat_consumer_cards import (
    BEAST, BATCH_HASH, DESCENT, FLAMER, OVERDRIVE, PATROL, ROOTS, VOID, load_batch)
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, RequestChoice, Silence
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.model import CardClass, CardMetadata, DamageKind, Keyword, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest

COIN, YETI, FLY, SI7 = 'GAME_005', 'CORE_CS2_182', 'CORE_UNG_809', 'CORE_EX1_134'
P = 'fixture.native_combat_consumers.'
KILL, HURT, SCRATCH, SILENCE, SUMMON, PLAIN, MECH, SD, SHIELD, WAIT, WATCH = (
    P+s for s in ('kill', 'hurt', 'scratch', 'silence', 'summon', 'plain', 'mech', 'spell_damage', 'shield', 'death_wait', 'watch'))
CTX = GenerationContext('k333-explicit-known-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry()
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    for cid, body, targeting in (
        (KILL, lambda c: (Destroy(c.target_id, c.source_id),), target),
        (HURT, lambda c: (Damage(c.target_id, 10, c.source_id),), TargetSpec()),
        (SCRATCH, lambda c: (Damage(c.target_id, 2, c.source_id),), target),
        (SILENCE, lambda c: (Silence(c.target_id),), target),
        (SUMMON, lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(SI7),), SummonCause.capture(c)),), None)):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, 'Explicit test preparation', CardType.SPELL,
            metadata=META, on_play=cid, targeting=targeting))
    r.register_card(CardDefinition(PLAIN, 'Known one-cost pool entry', CardType.MINION, cost=1,
        attack=2, health=4, metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())))
    r.register_pool_card(PoolCard.from_definition(r.card(PLAIN)))
    r.register_card(CardDefinition(MECH, 'Known friendly Mech', CardType.MINION,
        attack=2, health=8, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))))
    r.register_card(CardDefinition(SD, 'Known Spell Damage source', CardType.MINION, health=8, spell_damage=1, metadata=META))
    r.register_card(CardDefinition(SHIELD, 'Known shielded neighbor', CardType.MINION, attack=1, health=5,
        keywords=(Keyword.DIVINE_SHIELD,), metadata=META))
    r.register_behavior(WAIT, lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('continue', 'Continue'), ChoiceOption('hurt', 'Damage before original healing',
            (Damage(c.state.players[c.player_id].hero_id, 2, c.source_id),))), c.source_id),))
    r.register_card(CardDefinition(WAIT, 'Explicit death boundary observer', CardType.MINION,
        attack=1, health=5, metadata=META, deathrattle=WAIT))
    members = () if mode == 'empty' else (FLY,) if mode == 'firefly' else (FLY, PLAIN)
    entries = tuple(PoolMember(cid) for cid in members)
    if mode == 'unknown':
        unknown = P+'unknown'
        r.register_pool_card(PoolCard(unknown, CardType.MINION, 1,
            CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=()),
            battlecry=False, deathrattle=False, choose_one=False))
        entries += (PoolMember(unknown),)
    r.register_pool(PoolDefinition('constructed.minions', 'explicit-v1', CTX.target_id, CTX.mode, entries, complete=True))
    if mode in ('weapon_wait', 'patrol_wait', 'summon_wait'):
        def observe(c):
            if mode == 'weapon_wait':
                entity = c.state.entities.get(c.event.target_id)
                if entity is None or entity.card_id != OVERDRIVE or entity.controller != c.player_id: return ()
            elif mode == 'patrol_wait':
                if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != PATROL: return ()
            else:
                entity = c.state.entities.get(c.event.target_id)
                if entity is None or entity.card_id not in (FLY, PLAIN) or entity.controller != c.player_id: return ()
                if sum(len(row.deliveries) for row in c.state.card_summon_history) != 1: return ()
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        r.register_behavior(WATCH, observe)
        event = 'card_added_to_hand' if mode == 'weapon_wait' else 'damage_dealt' if mode == 'patrol_wait' else 'minion_summoned'
        r.register_card(CardDefinition(WATCH, 'Explicit boundary observer', CardType.MINION,
            health=20, metadata=META, triggers=(TriggerSpec(event, WATCH),)))
    return r


class NativeCombatConsumerTests(unittest.TestCase):
    readers = {}

    def game(self, hand=(), board=(), enemy=(), mode='normal', weapon=None, other_weapon=None):
        if mode in ('weapon_wait', 'patrol_wait', 'summon_wait'): board = (WATCH,)+board
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand, board=board,
                deck=(COIN,)*10, mana=10, max_mana=10, weapon_card_id=weapon),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=(COIN,), board=enemy,
                deck=(COIN,)*10, mana=10, max_mana=10, weapon_card_id=other_weapon)),
            seed=0, generation_context=CTX), fixture(mode))

    def play(self, g, cid, target=None, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid, target_id=target)); return eid

    def proceed(self, g, option='continue'):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def portable(self, g, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        r = self.readers[mode]; saved = g.snapshot()
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), r).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for hidden in ('"rng_state"', '"pool_basis"', '"card_summon_history"', '"cast_history"'):
                self.assertNotIn(hidden, visible)

    def test_complete_five_roots_and_original_named_dependency_keep_full_metadata(self):
        data = load_batch(); self.assertEqual(canonical_digest(data), BATCH_HASH)
        self.assertEqual(len(data['official_observations']), 12)
        r = fixture()
        for item in data['cards']:
            raw = item['record']; card = r.card(raw['id'])
            self.assertEqual(asdict(card.metadata), asdict(metadata_from_record(raw)))
            self.assertEqual((card.kind.value.upper(), card.cost), (raw['type'], raw['cost']))
            self.assertEqual(canonical_digest(raw), item['record_sha256'])
        dep = data['existing_dependencies'][0]
        self.assertEqual(canonical_digest(asdict(r.card(OVERDRIVE))), dep['definition_sha256'])
        self.assertEqual((r.card(FLAMER).kind, r.card(FLAMER).attack, r.card(FLAMER).durability), (CardType.WEAPON, 2, 2))
        self.assertEqual(set(ROOTS), {item['record']['id'] for item in data['cards']})

    def test_void_hits_original_target_and_only_two_immediate_neighbors_on_either_board(self):
        for friendly in (False, True):
            with self.subTest(friendly=friendly):
                g = self.game((VOID,), (YETI,)*4 if friendly else (), () if friendly else (YETI,)*4)
                board = tuple(g.state.players[1 if friendly else 2].board)
                source = self.play(g, VOID, board[1])
                self.assertEqual([g.state.entities[i].health for i in board], [3, 1, 3, 5])
                hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
                self.assertEqual(sorted(e.amount for e in hits), [2, 2, 4])

    def test_void_edge_and_spell_damage_use_single_native_batch(self):
        g = self.game((VOID,), (SD,), (YETI,)*3); board = tuple(g.state.players[2].board)
        self.play(g, VOID, board[0])
        self.assertEqual(g.state.entities[board[0]].zone, Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[i].health for i in board[1:]], [2, 5]); self.portable(g)

    def test_void_divine_shield_does_not_cancel_neighbor_damage(self):
        g = self.game((VOID,), enemy=(YETI, SHIELD, YETI)); ids = tuple(g.state.players[2].board)
        self.play(g, VOID, ids[1]); self.assertEqual([g.state.entities[i].health for i in ids], [3, 5, 3])
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[ids[1]].keywords)

    def test_both_targeted_spells_reject_hero_before_payment(self):
        for card in (VOID, DESCENT):
            g = self.game((card,)); saved = g.snapshot()
            with self.assertRaises(IllegalAction): self.play(g, card, g.state.players[2].hero_id)
            self.assertEqual(g.snapshot(), saved)

    def test_descent_restores_current_health_to_target_controller_after_destruction(self):
        for friendly in (False, True):
            with self.subTest(friendly=friendly):
                owner = 1 if friendly else 2
                g = self.game((HURT, SCRATCH, DESCENT), (YETI,) if friendly else (), () if friendly else (YETI,))
                hero = g.state.players[owner].hero_id; target = g.state.players[owner].board[0]
                self.play(g, HURT, hero); self.play(g, SCRATCH, target); self.play(g, DESCENT, target)
                self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[hero].health, 23)

    def test_descent_waiting_deathrattle_keeps_original_amount_and_heals_after_reactions(self):
        g = self.game((HURT, DESCENT), enemy=(WAIT,)); hero = g.state.players[2].hero_id
        self.play(g, HURT, hero); target = g.state.players[2].board[0]; self.play(g, DESCENT, target)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.entities[hero].health, 20)
        self.portable(g); self.proceed(g, 'hurt'); self.assertEqual(g.state.entities[hero].health, 23)
        self.portable(g)

    def test_flamer_natural_hero_attacks_reward_both_durability_charges(self):
        g = self.game((FLAMER,)); self.play(g, FLAMER); hero = g.state.players[1].hero_id
        for count in (1, 2):
            g.apply(Attack(1, hero, g.state.players[2].hero_id))
            self.assertEqual(sum(g.state.entities[i].card_id == OVERDRIVE for i in g.state.players[1].hand), count)
            if count == 1: g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertIsNone(g.state.players[1].weapon_id); self.portable(g)

    def test_flamer_ignores_minion_attacks_and_foreign_hero_attacks(self):
        g = self.game(board=(YETI,), weapon=FLAMER, other_weapon=FLAMER)
        g.apply(Attack(1, g.state.players[1].board[0], g.state.players[2].hero_id))
        self.assertFalse(g.state.players[1].hand); g.apply(EndTurn(1))
        g.apply(Attack(2, g.state.players[2].hero_id, g.state.players[1].hero_id))
        self.assertEqual(sum(g.state.entities[i].card_id == OVERDRIVE for i in g.state.players[1].hand), 0)
        self.assertEqual(sum(g.state.entities[i].card_id == OVERDRIVE for i in g.state.players[2].hand), 1)

    def test_flamer_full_hand_burns_actual_named_reward(self):
        g = self.game((COIN,)*10, weapon=FLAMER)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(any(e.kind == 'card_burned' for e in g.events))
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id == OVERDRIVE]), 1)

    def test_flamer_original_reward_wait_restore_then_actual_overdrive_execution(self):
        g = self.game(board=(MECH,), mode='weapon_wait', weapon=FLAMER)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertIsNotNone(g.state.pending_choice); self.portable(g, 'weapon_wait'); self.proceed(g)
        mech = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == MECH)
        self.play(g, OVERDRIVE, mech); self.assertEqual(g.state.entities[mech].attack, 4)
        self.assertIn(Keyword.RUSH, g.state.entities[mech].keywords)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[mech].zone, Zone.GRAVEYARD)

    def test_patrol_counts_first_combo_card_even_when_combo_body_does_not_activate(self):
        g = self.game((SI7,), (PATROL,)); enemy = g.state.players[2].hero_id
        self.play(g, SI7); self.assertEqual(g.state.entities[enemy].health, 27)
        self.assertEqual(g.state.play_history[-1].prior_turn_plays, 0)

    def test_patrol_counts_activated_combo_and_separates_its_native_damage(self):
        g = self.game((COIN, SI7), (PATROL,)); hero = g.state.players[2].hero_id
        self.play(g, COIN); self.play(g, SI7, hero)
        self.assertEqual(g.state.entities[hero].health, 24); self.assertEqual(g.state.play_history[-1].prior_turn_plays, 1)

    def test_patrol_normal_play_and_only_summoned_combo_card_do_not_roll_rng(self):
        g = self.game((COIN, SUMMON), (PATROL,)); rng = g._rng.getstate()
        self.play(g, COIN); self.play(g, SUMMON)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_patrol_random_enemy_includes_hero_and_is_not_spell_damage(self):
        g = self.game((SI7,), (PATROL, SD), (YETI,)); before = sum(g.state.entities[i].health for i in (*g.state.players[2].board, g.state.players[2].hero_id))
        rng = g._rng.getstate(); self.play(g, SI7)
        after = sum(g.state.entities[i].health for i in (*g.state.players[2].board, g.state.players[2].hero_id))
        self.assertEqual(before-after, 3); self.assertNotEqual(g._rng.getstate(), rng)

    def test_patrol_actual_damage_wait_restores_without_repeating_random_selection(self):
        g = self.game((SI7,), (PATROL,), mode='patrol_wait'); self.play(g, SI7)
        self.assertIsNotNone(g.state.pending_choice); rng = g._rng.getstate(); saved = g.snapshot(); self.portable(g, 'patrol_wait')
        c = g.state.pending_choice
        with self.assertRaises(IllegalAction): g.apply(SelectChoice(c.player_id, c.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved); self.proceed(g); self.assertEqual(g._rng.getstate(), rng)

    def test_beast_two_physical_summons_skip_battlecries_then_buff_new_and_old_minions(self):
        g = self.game((KILL,), (BEAST, YETI), mode='firefly'); self.play(g, KILL, g.state.players[1].board[0])
        bodies = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.card_id, e.attack, e.health) for e in bodies], [(YETI, 7, 5), (FLY, 4, 2), (FLY, 4, 2)])
        self.assertFalse(g.state.players[1].hand); self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertTrue(all(len(row.deliveries) == 1 for row in g.state.card_summon_history)); self.portable(g, 'firefly')

    def test_beast_one_space_samples_once_and_buffs_all_actual_survivors(self):
        g = self.game((KILL,), (BEAST,)+(YETI,)*6)
        expected = random.Random(); expected.setstate(g._rng.getstate()); expected.randrange(2)
        self.play(g, KILL, g.state.players[1].board[0]); self.assertEqual(g._rng.getstate(), expected.getstate())
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual([len(row.deliveries) for row in g.state.card_summon_history], [1, 0])
        self.assertTrue(all(g.state.entities[i].attack == 7 for i in g.state.players[1].board if g.state.entities[i].card_id == YETI))

    def test_beast_empty_pool_still_buffs_existing_minions_without_rng(self):
        g = self.game((KILL,), (BEAST, YETI), mode='empty'); rng = g._rng.getstate()
        self.play(g, KILL, g.state.players[1].board[0]); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual([(g.state.entities[i].card_id, g.state.entities[i].attack) for i in g.state.players[1].board], [(YETI, 7)])

    def test_beast_unknown_eligible_pool_rolls_back_original_destruction_and_payment(self):
        g = self.game((KILL,), (BEAST, YETI), mode='unknown'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, KILL, g.state.players[1].board[0])
        self.assertEqual(g.snapshot(), saved)

    def test_beast_silence_removes_native_deathrattle(self):
        g = self.game((SILENCE, KILL), (BEAST, YETI)); source = g.state.players[1].board[0]; rng = g._rng.getstate()
        self.play(g, SILENCE, source); self.play(g, KILL, source)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.card_summon_history)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack, 4)

    def test_beast_first_summon_wait_restores_second_summon_then_one_current_buff(self):
        g = self.game((KILL,), (BEAST, YETI), mode='summon_wait')
        self.play(g, KILL, g.state.players[1].board[1]); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].board), 3)
        self.assertEqual(next(g.state.entities[i].attack for i in g.state.players[1].board if g.state.entities[i].card_id == YETI), 4)
        self.portable(g, 'summon_wait'); self.proceed(g)
        self.assertEqual(len(g.state.players[1].board), 4)
        self.assertEqual(next(g.state.entities[i].attack for i in g.state.players[1].board if g.state.entities[i].card_id == YETI), 7)
        self.assertEqual(sum(len(row.deliveries) for row in g.state.card_summon_history), 2)
        self.portable(g, 'summon_wait')


if __name__ == '__main__': unittest.main()
