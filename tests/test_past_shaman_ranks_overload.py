"""Real Shaman entries and existing range/rank/held-progress boundaries."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import past_shaman_ranks_overload as native
from hs_sim.engine import EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (Buff, ChangeManaCrystals, ChoiceOption, Damage, Draw,
    InvokeBehavior, Overload, RandomDamage, RequestChoice, Summon)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Keyword, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest
from tools import card_batch as cb

ELEMENTAL, CHAIN, SCHEME, FORK, CRACKLE, STONE = native.ROOTS
P = 'k675.'
A, B, DORMANT, POWER, SHIELD, IMMUNE, SPAWNER, TOKEN, WATCH, FAIL = (
    P+x for x in ('a', 'b', 'dormant', 'power', 'shield', 'immune', 'spawner', 'token', 'watch', 'fail'))
OVER1, OVER2, OVER4, GAIN, SHRINK, DRAW, GROW, HURT, DISCOUNT, AUTO_FORK, AUTO_SCHEME = (
    P+x for x in ('over1', 'over2', 'over4', 'gain', 'shrink', 'draw', 'grow', 'hurt', 'discount', 'auto_fork', 'auto_scheme'))
CTX = GenerationContext('k675-original-native-consumers', 'experimental')


@lru_cache(None)
def host(role='writer'):
    return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r = opening_registry()
    native.register_past_shaman_ranks_overload(r)
    for cid, hp, keywords, power, dormant in (
            (A, 30, (), 0, 0), (B, 30, (), 0, 0), (DORMANT, 30, (), 0, 2),
            (POWER, 30, (), 2, 0), (SHIELD, 30, (Keyword.DIVINE_SHIELD,), 0, 0),
            (IMMUNE, 30, (Keyword.IMMUNE,), 0, 0), (SPAWNER, 2, (), 0, 0), (TOKEN, 2, (), 0, 0)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=2, health=hp,
            keywords=keywords, spell_damage=power, dormant_turns=dormant,
            deathrattle=SPAWNER if cid == SPAWNER else None, metadata=metadata(tribes=())))
    r.register_behavior(SPAWNER, lambda c: (Summon(c.player_id, TOKEN),))
    bodies = {
        OVER1: lambda c: (Overload(c.player_id, 1),), OVER2: lambda c: (Overload(c.player_id, 2),),
        OVER4: lambda c: (Overload(c.player_id, 4),),
        GAIN: lambda c: (ChangeManaCrystals(c.player_id, 1, True),),
        SHRINK: lambda c: (ChangeManaCrystals(c.player_id, -7),),
        DRAW: lambda c: (Draw(c.player_id, 1, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, 3, 2, c.source_id),),
        HURT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        DISCOUNT: lambda c: tuple(ModifyStoredCost(CardReference.capture(c.state.entities[eid]), CostSpec(delta=-2), c.source_id)
            for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id in native.STONES),
        AUTO_FORK: lambda c: (CastSpell(c.player_id, FORK, c.source_id),),
        AUTO_SCHEME: lambda c: (CastSpell(c.player_id, SCHEME, c.source_id),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        fields = dict(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))) if cid in (GROW, HURT) else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(collectible=False), **fields))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K675 deliberate rollback')))

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in (ELEMENTAL, FORK, *native.RANKS):
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue'), ChoiceOption('fault', 'Fail', (
                RandomDamage((c.state.players[3-c.player_id].hero_id,), 1, c.source_id),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=(TriggerSpec('damage_dealt', WATCH),), metadata=metadata(collectible=False, tribes=())))
    r.validate()
    return r


class ShamanRanksOverloadTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand=(), *, board=(), enemy=(), deck=('card.1',)*12, maximum=10,
            enemy_hand=(), seed=675):
        self.mode = 'small'
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck, mana=maximum, max_mana=maximum),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy, deck=('card.2',)*12, mana=10, max_mana=10)),
            seed=seed, generation_context=CTX), fixture('writer'))

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def ids(self, g, p=1, zone='hand'):
        return [g.state.entities[e].card_id for e in getattr(g.state.players[p], zone)]

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            self.choose(g); count += 1
            self.assertLess(count, 20)

    def health_events(self, g, source):
        return [dict(dict(e.data)['result']) for e in g.events
            if e.kind == 'health_resolved' and e.source_id == source]

    def test_ten_complete_native_faces_twenty_two_primary_faces_and_real_rank_family(self):
        d = native.load_batch(); r = fixture('writer')
        self.assertEqual((len(d['cards']), len(d['dependencies']), len(d['official_observations'])), (6, 4, 22))
        for row in d['cards']+d['dependencies']:
            cid = row['record']['id']
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(PoolCard.from_definition(r.card(cid)))), row['pool_card_sha256'])
        self.assertEqual(r.mana_rank_families[native.RANK_FAMILY.id], native.RANK_FAMILY)
        self.assertFalse(d['complete_shaman_source_bound']); self.assertEqual(len(d['original_shaman_member_ids']), 71)
        self.assertEqual(r.use_visibility(native.PREFIX+'enemy_minion'), 'player')

    def test_all_six_real_root_entries_pay_once_and_keep_original_overload_amounts(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g = self.game((cid,), board=(A,), enemy=(B,))
                actual = native.RANKS[2] if cid == CHAIN else cid
                target = g.state.players[1].board[0] if cid == STONE else g.state.players[2].board[0] if cid == CHAIN else self.hero(g, 2).id if cid == CRACKLE else None
                self.play(g, actual, target); self.finish(g)
                self.assertEqual(g.state.players[1].mana, 10-g.registry.card(actual).cost)
                self.assertEqual([c.card_id for c in g.state.cast_history], [actual])
                self.assertEqual(g.state.players[1].overload_owed, {ELEMENTAL:2, FORK:2, CRACKLE:1}.get(cid, 0))

    def test_crackle_uses_complete_uniform_integer_range_and_spell_damage_on_actual_paid_source(self):
        for seed in (0, 1, 5, 9):
            g = self.game((CRACKLE,), board=(POWER,), seed=seed)
            rng = random.Random(); rng.setstate(g._rng.getstate()); rolled = rng.choice((3,4,5,6))
            source = self.play(g, CRACKLE, self.hero(g, 2).id)
            self.assertEqual(self.hero(g, 2).health, 30-rolled-2)
            self.assertEqual([dict(e.data)['selected'] for e in g.events if e.kind == 'random_choice' and e.source_id == source], [str(rolled)])
            self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_crackle_ordinary_shield_immunity_and_friendly_targeting_do_not_bypass_health_rules(self):
        for cid in (SHIELD, IMMUNE, A):
            g = self.game((CRACKLE,), board=(cid,)); target = g.state.players[1].board[0]
            self.play(g, CRACKLE, target)
            self.assertEqual(g.state.entities[target].health, 30) if cid != A else self.assertIn(g.state.entities[target].health, (24,25,26,27))
            if cid == SHIELD: self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_elemental_independent_original_entry_order_rolls_and_ordinary_overload_two(self):
        g = self.game((ELEMENTAL,), board=(A,A), enemy=(B,B))
        targets = tuple(sorted((*g.state.players[1].board,*g.state.players[2].board), key=lambda i:g.state.entities[i].entered_order))
        rng = random.Random(); rng.setstate(g._rng.getstate()); amounts = tuple(rng.choice((4,5)) for _ in targets)
        source = self.play(g, ELEMENTAL)
        self.assertEqual(tuple(30-g.state.entities[i].health for i in targets), amounts)
        self.assertEqual(tuple(x['target_id'] for x in self.health_events(g, source)), targets)
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.assertEqual(g.state.players[1].overload_owed, 2)
        self.portable(g)

    def test_elemental_empty_board_has_no_rng_but_still_pays_and_overloads(self):
        g = self.game((ELEMENTAL,)); rng = g._rng.getstate()
        self.play(g, ELEMENTAL)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(g.state.players[1].mana, 7)
        self.assertEqual(g.state.players[1].overload_owed, 2)

    def test_elemental_original_recipient_set_does_not_damage_new_deathrattle_token(self):
        g = self.game((ELEMENTAL,), board=(SPAWNER,), enemy=(B,))
        original = g.state.players[1].board[0]; self.play(g, ELEMENTAL)
        self.assertNotIn(original, g.state.players[1].board)
        self.assertEqual(self.ids(g, zone='board'), [TOKEN])
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health, 2)
        self.portable(g)

    def test_elemental_excludes_dormant_but_retains_shield_and_immune_recipients(self):
        g = self.game((ELEMENTAL,), enemy=(DORMANT, SHIELD, IMMUNE, B))
        dormant, shield, immune, ordinary = g.state.players[2].board
        source = self.play(g, ELEMENTAL)
        self.assertEqual(g.state.entities[dormant].health, 30)
        self.assertEqual(g.state.entities[shield].health, 30); self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[shield].keywords)
        self.assertEqual(g.state.entities[immune].health, 30); self.assertIn(g.state.entities[ordinary].health, (25,26))
        self.assertEqual(len([e for e in g.events if e.kind == 'random_choice' and e.source_id == source]), 3)

    def test_elemental_wait_keeps_later_original_recipient_unhit_and_resume_failure_rolls_rng_back(self):
        g = self.game((ELEMENTAL,), board=(A,WATCH), enemy=(B,))
        last = g.state.players[2].board[0]; self.play(g, ELEMENTAL)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.entities[last].health, 30)
        g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.finish(g); self.assertIn(g.state.entities[last].health, (25,26))
        self.assertEqual(g.state.players[1].overload_owed, 2); self.portable(g)

    def test_fork_manual_zero_and_only_dormant_enemy_are_illegal_with_no_payment_or_rng(self):
        for enemy in ((), (DORMANT,)):
            g = self.game((FORK,), enemy=enemy); before = g.snapshot()
            with self.assertRaises(IllegalAction): self.play(g, FORK)
            self.assertEqual(g.snapshot(), before)

    def test_fork_one_enemy_is_legal_and_three_enemies_select_two_distinct_originals(self):
        for enemy in ((B,), (B,B,B)):
            g = self.game((FORK,), enemy=enemy); before = tuple(g.state.players[2].board)
            self.play(g, FORK)
            self.assertEqual(sum(g.state.entities[i].health == 28 for i in before), min(2,len(before)))
            self.assertEqual(g.state.players[1].overload_owed, 2)
        self.portable(g)

    def test_fork_both_damage_packets_settle_before_first_waiting_reaction(self):
        g = self.game((FORK,), board=(WATCH,), enemy=(B,B))
        self.play(g, FORK); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [28,28])
        g = self.portable(g); self.finish(g); self.assertEqual(g.state.players[1].overload_owed, 2)

    def test_automatic_fork_empty_board_does_not_inherit_manual_minion_prerequisite(self):
        g = self.game((AUTO_FORK,)); self.play(g, AUTO_FORK)
        self.assertEqual([c.card_id for c in g.state.cast_history], [AUTO_FORK,FORK])
        self.assertEqual(g.state.players[1].overload_owed, 2); self.portable(g)

    def test_all_three_chain_faces_use_maximum_crystals_in_hand_and_deck(self):
        for maximum, expected in ((4, native.RANKS[0]), (5,native.RANKS[1]), (10,native.RANKS[2])):
            g = self.game((CHAIN,), deck=(CHAIN,CHAIN), maximum=maximum, enemy=(B,))
            self.assertEqual(self.ids(g), [expected]); self.assertEqual(self.ids(g, zone='deck'), [expected,expected])
            target = g.state.players[2].board[0]; self.play(g, expected, target)
            self.assertEqual(g.state.entities[target].health, 30-(native.RANKS.index(expected)+2))
        self.portable(g)

    def test_chain_actual_crystal_gain_upgrades_original_identity_but_lower_maximum_never_downgrades(self):
        g = self.game((CHAIN,GAIN), deck=(CHAIN,), maximum=4)
        original = self.entity(g, CHAIN).id; self.play(g, GAIN)
        self.assertEqual(g.state.entities[original].card_id, native.RANKS[1])
        self.assertEqual(self.ids(g, zone='deck'), [native.RANKS[1]])
        g = self.game((CHAIN,SHRINK), maximum=10); original = self.entity(g,native.RANKS[2]).id
        self.play(g, SHRINK); self.assertEqual(g.state.players[1].max_mana, 3)
        self.assertEqual(g.state.entities[original].card_id, native.RANKS[2]); self.portable(g)

    def test_chain_middle_target_and_one_random_adjacent_share_one_original_damage_batch(self):
        g = self.game((CHAIN,), board=(WATCH,), enemy=(B,A,B))
        left, middle, right = g.state.players[2].board
        self.play(g, native.RANKS[2], middle); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[middle].health, 26)
        self.assertEqual(sorted(g.state.entities[i].health for i in (left,right)), [26,30])
        g = self.portable(g); self.finish(g); self.portable(g)

    def test_chain_single_neighbor_has_no_rng_and_dormant_slots_do_not_bridge(self):
        for enemy, index in (((B,A),1), ((B,DORMANT,A),2)):
            g = self.game((CHAIN,), enemy=enemy); target = g.state.players[2].board[index]; rng = g._rng.getstate()
            self.play(g, native.RANKS[2], target)
            self.assertEqual(g._rng.getstate(), rng)
            self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 26 if len(enemy)==2 else 30)

    def test_scheme_initial_one_only_actual_own_start_grows_and_current_copy_survives_restore(self):
        g = self.game((SCHEME,), enemy=(B,)); original = self.entity(g,SCHEME).id
        self.assertEqual(progress_ability(g.state.entities[original]).progress_completions, 0)
        g.apply(EndTurn(1)); self.assertEqual(progress_ability(g.state.entities[original]).progress_completions, 0)
        g.apply(EndTurn(2)); self.assertEqual(progress_ability(g.state.entities[original]).progress_completions, 1)
        g = self.portable(g); target = g.state.players[2].board[0]; self.play(g,SCHEME)
        self.assertEqual(g.state.entities[target].health, 28); self.portable(g)

    def test_scheme_deck_does_not_grow_and_normal_turn_draw_is_not_a_held_start_witness(self):
        g = self.game((SCHEME,), deck=(SCHEME,))
        original = self.entity(g,SCHEME).id; self.cycle(g)
        cards = [g.state.entities[eid] for eid in g.state.players[1].hand if g.state.entities[eid].card_id==SCHEME]
        self.assertEqual(len(cards),2)
        self.assertEqual({e.id:progress_ability(e).progress_completions for e in cards},
            {original:1,next(e.id for e in cards if e.id!=original):0})
        self.portable(g)

    def test_scheme_automatic_new_source_uses_initial_one_and_ordinary_spell_damage(self):
        g = self.game((AUTO_SCHEME,), board=(POWER,), enemy=(B,)); target=g.state.players[2].board[0]
        self.play(g,AUTO_SCHEME); self.assertEqual(g.state.entities[target].health,27)
        self.assertEqual([c.card_id for c in g.state.cast_history],[AUTO_SCHEME,SCHEME]); self.portable(g)

    def test_sapphire_actual_native_overloads_upgrade_by_crystals_not_number_of_cards(self):
        g = self.game((STONE,ELEMENTAL,CRACKLE), enemy=(B,)); original=self.entity(g,STONE).id
        self.play(g,ELEMENTAL); self.assertEqual(progress_ability(g.state.entities[original]).progress_value,2)
        self.play(g,CRACKLE,self.hero(g,2).id)
        self.assertEqual(g.state.entities[original].card_id,native.STONES[1])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_value,0)
        self.assertEqual([v.amount for v in g.state.overload_history],[2,1]); self.portable(g)

    def test_sapphire_one_increment_finishes_only_one_stage_and_enemy_overload_does_not_count(self):
        g=self.game((STONE,OVER4,OVER2,OVER1),enemy_hand=(OVER4,)); original=self.entity(g,STONE).id
        self.play(g,OVER4); self.assertEqual(g.state.entities[original].card_id,native.STONES[1])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_value,0)
        g.apply(EndTurn(1)); self.play(g,OVER4,player=2)
        self.assertEqual(progress_ability(g.state.entities[original]).progress_value,0)
        g.apply(EndTurn(2)); self.play(g,OVER2); self.play(g,OVER1)
        self.assertEqual(g.state.entities[original].card_id,native.STONES[2]); self.portable(g)

    def test_sapphire_only_hand_tracks_overload_and_upgrade_clears_ordinary_local_cost(self):
        g=self.game((STONE,DISCOUNT,OVER4),deck=(STONE,)); original=self.entity(g,STONE).id
        self.play(g,DISCOUNT); self.assertEqual(g.quote_cost(original).amount,5)
        self.play(g,OVER4); self.assertEqual(g.state.entities[original].card_id,native.STONES[1])
        self.assertEqual(g.quote_cost(original).amount,7); self.assertEqual(self.ids(g,zone='deck'),[STONE])
        self.portable(g)

    def test_all_sapphire_faces_copy_current_original_buffs_damage_and_never_hand_play_minions(self):
        for count,cid in enumerate(native.STONES,1):
            g=self.game((GROW,HURT,cid),board=(A,)); target=g.state.players[1].board[0]
            self.play(g,GROW,target); self.play(g,HURT,target)
            before=g.state.entities[target]; expected=(before.attack,before.health,before.max_health)
            self.play(g,cid,target); self.assertEqual(len(g.state.players[1].board),count+1)
            self.assertEqual([(g.state.entities[e].attack,g.state.entities[e].health,g.state.entities[e].max_health)
                for e in g.state.players[1].board[1:]],[expected]*count)
            self.assertEqual([v.card_id for v in g.state.play_history],[GROW,HURT,cid])
        self.portable(g)

    def test_greater_sapphire_respects_actual_capacity_without_allocating_overflow_copies(self):
        g=self.game((native.STONES[2],),board=(A,)*6); target=g.state.players[1].board[0]
        allocator=g.state.next_entity_id; self.play(g,native.STONES[2],target)
        self.assertEqual(len(g.state.players[1].board),7); self.assertEqual(g.state.next_entity_id,allocator+1)
        self.portable(g)

    def test_sapphire_primary_separator_normalization_is_exact_pinned_and_never_omits_rule_words(self):
        d=native.load_batch()
        for cid in native.STONES[:2]:
            row=next(x['record'] for x in d['cards']+d['dependencies'] if x['record']['id']==cid)
            for observation in (o for o in d['official_observations'] if o['card_id']==cid):
                cb.check_face(row,observation['face'],observation['locale'],{'@':''})
                changed=deepcopy(row); changed['text']+=' extra rule'
                with self.assertRaises(ValueError):cb.check_face(changed,observation['face'],observation['locale'],{'@':''})
                face=deepcopy(observation['face']); face['text']=''
                with self.assertRaises(ValueError):cb.check_face(row,face,observation['locale'],{'@':''})

    def test_real_standard_host_plays_actual_upgraded_copy_face_and_actual_ranged_spell(self):
        self.mode='host';h=host('writer');deck=('CORE_EX1_169',)*12
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(native.STONES[2],CRACKLE),board=('LOOT_077t',),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=675,generation_context=h.context),h.registry)
        self.play(g,native.STONES[2],g.state.players[1].board[0]); self.assertEqual(len(g.state.players[1].board),4)
        self.play(g,CRACKLE,g.state.players[2].hero_id); self.assertEqual(g.state.players[1].overload_owed,1)
        self.assertEqual(g._generation_context,h.context); self.portable(g)
