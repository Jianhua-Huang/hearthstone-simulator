"""Original same-turn offers, source-independent Dragon Rush and named summons."""
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p59_cards import (ABYSSIAN, UPGRADED, MURLOC_MAP,
    FEL_MAP, DECK_MAP, UND_FORM, ELE_FORM, INF_FORM, UND_TOKEN, ELE_TOKEN, INF_TOKEN,
    ROOTS, EVIDENCE, RUSH, MAPPINGS, PREFIX, POOL_ID, load_batch, register_simple_followup_p59_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, SpellSchool
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p59.test.'
YETI = 'CORE_CS2_182'
MURL = tuple(TEST + n for n in ('murl_a', 'murl_b', 'murl_c'))
FELS = tuple(TEST + n for n in ('fel_a', 'fel_b', 'fel_c'))
FOREIGN, UNKNOWN = TEST + 'warrior_murloc', TEST + 'unknown_murloc'
DRAGON, ALL_RACE = TEST + 'dragon', TEST + 'all'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (*MURL, *FELS, FOREIGN)
CONTEXT = GenerationContext('p59-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p59_cards(r)
    elif not all(present): raise AssertionError('P59 requires complete eleven-definition assembly')
    register_candidate_pool_metadata(r); r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    rows = [(cid, CardClass.NEUTRAL if n == 0 else CardClass.MAGE, ('murloc',)) for n, cid in enumerate(MURL)]
    rows += [(FOREIGN, CardClass.WARRIOR, ('murloc',)), (DRAGON, CardClass.NEUTRAL, ('dragon',)),
        (ALL_RACE, CardClass.NEUTRAL, ('all',))]
    for cid, cls, tribes in rows:
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=2, health=6,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=tribes)))
    r.register_behavior(TEST + 'armor', lambda c: (GainArmor(c.player_id, 1),))
    for n, cid in enumerate(FELS):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=0, spell_school=SpellSchool.FEL,
            on_play=TEST + 'armor', metadata=CardMetadata(True,
                (CardClass.NEUTRAL if n == 0 else CardClass.MAGE,), Rarity.COMMON, tribes=())))
    def cycle(c):
        root = c.state.hand_choice_followups[-1]
        target = root.initial_entity_id
        return (MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.DECK, source_id=c.source_id),
            InvokeBehavior(TEST + 'return', c.source_id, 1, target))
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        give=lambda c: (ChangeControl(c.target_id, 2),),
        silence=lambda c: (Silence(c.target_id),),
        cycle=cycle,
        return_hand=lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 1, Zone.HAND, source_id=c.source_id),),
        remove_one=lambda c: (RemovePlayerEffect(1, c.state.players[1].player_effects[0].id),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P59 deliberate continuation failure')))
    for name, body in scripts.items():
        key = TEST + ('return' if name == 'return_hand' else name)
        r.register_behavior(key, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=key,
            targeting=TargetSpec() if name in ('kill', 'give', 'silence') else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 1,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('murloc',)),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p59-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        r.register_trigger_condition(TEST + 'eligible', lambda c: any(
            root.request.cause.source.card_id == ELE_FORM and any(d.outcome == 'delivered' and
            d.entity.entity_id == c.event.target_id for d in root.deliveries)
            for root in c.state.card_summon_history))
        r.register_behavior(TEST + 'watch', lambda c: (RequestChoice(1, (
            ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (
                InvokeBehavior(TEST + 'fail', c.source_id, 1),))), c.source_id),))
        r.register_card(CardDefinition(TEST + 'watch', 'Original summon witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec('minion_summoned',
                TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate(); return r


@lru_cache(maxsize=None)
def shared_registry(mode, members): return registry(mode, members)


class SimpleFollowupP59Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 10, mode=None, members=MEMBERS):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 10, mana=40, max_mana=40, mana_cap=40)),
            seed=5959, generation_context=CONTEXT), shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play_id(self, g, entity_id, target=None):
        e = g.state.entities[entity_id]
        g.apply(PlayCard(1, entity_id, target_id=target,
            position=len(g.state.players[1].board) if e.kind == CardType.MINION else None))

    def play(self, g, cid, target=None):
        source = self.first(g, cid).id; self.play_id(g, source, target); return source

    def choose(self, g, cid=None, key=None):
        q = g.state.pending_choice
        option = next(o for o in q.options if key == o.id) if key is not None else next(o for o in q.options if cid is None or o.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'hand_choice_followups'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_eighteen_full_rows_thirty_six_faces_twenty_real_links_and_internal_mapping_limit(self):
        from tools.card_batch import check_face
        data = load_batch(); rows = {x['record']['id']: x for k in ('cards', 'evidence_only') for x in data[k]}
        self.assertEqual((len(rows), len(data['official_observations']), len(data['exact_parent_child_links'])), (18, 36, 20))
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            check_face(raw, o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(raw['id']))
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        for mapping in data['token_mapping_basis']:
            self.assertFalse(any(x['parent'] == mapping['form'] and x['child'] == mapping['token'] for x in data['exact_parent_child_links']))
        self.assertIn('not a claimed direct official TLC-to-token link', data['token_mapping_limit'])
        self.assertEqual(set(data['numeric_normalizations']), {'TTN_737t1', 'TTN_862t3', 'TTN_960t3'})
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['parent_implemented'])

    def test_eleven_definitions_four_roots_seven_forms_and_all_old_data_preserved(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items(): self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items(): self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools)); self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for cid in EVIDENCE: self.assertEqual(cid in after.cards, cid in before.cards)
        for row in load_batch()['cards']:
            raw = row['record']; card = after.card(raw['id'])
            self.assertEqual((card.cost, card.metadata), (raw['cost'], metadata_from_record(raw)))
            if card.kind == CardType.MINION: self.assertEqual((card.attack, card.health), (raw['attack'], raw['health']))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 4)
        self.assertEqual(after.card(DECK_MAP).spell_school, SpellSchool.SHADOW)
        self.assertEqual(after.card(UND_TOKEN).keywords, (Keyword.TAUNT, Keyword.REBORN))
        self.assertEqual(after.card(ELE_TOKEN).keywords, (Keyword.TAUNT,))
        self.assertFalse(after.card(INF_TOKEN).keywords)

    def test_murloc_map_real_original_offer_armed_play_and_reward_restore_without_reroll(self):
        g = self.game((MURLOC_MAP,))
        self.play(g, MURLOC_MAP)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(MURL))
        self.portable(g); self.choose(g, MURL[0])
        root = g.state.hand_choice_followups[-1]; original = root.initial_entity_id
        self.assertEqual(root.status, 'armed'); self.portable(g)
        self.play_id(g, original)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(MURL[1:]))
        self.portable(g); rng = g.snapshot()['rng_state']; self.choose(g, MURL[1])
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.hand_choice_followups[-1].status, 'completed')
        self.assertEqual(self.first(g, MURL[1]).zone, Zone.HAND)

    def test_fel_map_real_spell_play_uses_fel_and_current_class_pool(self):
        g = self.game((FEL_MAP,))
        self.play(g, FEL_MAP)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(FELS))
        self.choose(g, FELS[0]); original = g.state.hand_choice_followups[-1].initial_entity_id
        self.play_id(g, original)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(FELS[1:]))
        self.choose(g, FELS[1]); self.assertEqual(g.state.hand_choice_followups[-1].status, 'completed')

    def test_deck_map_takes_original_physical_cards_from_retained_offer_without_copy(self):
        g = self.game((DECK_MAP,), deck=(MURL[0], MURL[1], FELS[0]))
        old_deck = tuple(g.state.players[1].deck); next_id = g.state.next_entity_id
        self.play(g, DECK_MAP); self.choose(g, MURL[0])
        root = g.state.hand_choice_followups[-1]; original = root.initial_entity_id
        self.assertIn(original, old_deck); self.assertNotIn(original, g.state.players[1].deck)
        self.assertEqual(root.request.operation, 'take')
        self.play_id(g, original); self.choose(g, FELS[0])
        root = g.state.hand_choice_followups[-1]
        self.assertIn(root.reward_entity_id, old_deck)
        self.assertEqual(g.state.entities[root.reward_entity_id].zone, Zone.HAND)
        self.assertEqual(g.state.next_entity_id, next_id)
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_original_followup_ignores_existing_same_face_and_expires_if_unused(self):
        g = self.game((MURLOC_MAP, MURL[0]))
        existing = self.first(g, MURL[0]).id
        self.play(g, MURLOC_MAP); self.choose(g, MURL[0]); selected = g.state.hand_choice_followups[-1].initial_entity_id
        self.play_id(g, existing)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.hand_choice_followups[-1].status, 'armed')
        self.play_id(g, selected); self.assertIsNotNone(g.state.pending_choice)
        g = self.game((MURLOC_MAP,)); self.play(g, MURLOC_MAP); self.choose(g, MURL[0]); g.apply(EndTurn(1))
        self.assertEqual(g.state.hand_choice_followups[-1].status, 'expired')

    def test_selected_hand_departure_and_reentry_does_not_rearm_original_followup(self):
        g = self.game((MURLOC_MAP, TEST + 'cycle'))
        self.play(g, MURLOC_MAP); self.choose(g, MURL[0]); selected = g.state.hand_choice_followups[-1].initial_entity_id
        self.play(g, TEST + 'cycle'); self.play_id(g, selected)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.hand_choice_followups[-1].status, 'lost')

    def test_unknown_qualified_map_candidate_fails_before_rng_and_payment(self):
        g = self.game((MURLOC_MAP,), members=(*MURL, UNKNOWN))
        saved, calls = g.snapshot(), []; original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args); return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError): self.play(g, MURLOC_MAP)
        self.assertEqual(g.snapshot(), saved); self.assertFalse(calls)

    def test_abyssian_dragon_or_all_commit_upgrades_original_hand_entity_and_installs_rush(self):
        for cid in (DRAGON, ALL_RACE):
            g = self.game((ABYSSIAN, cid)); old = self.first(g, ABYSSIAN).id
            self.play(g, cid)
            self.assertEqual((g.state.entities[old].card_id, g.state.entities[old].attack, g.state.entities[old].max_health), (UPGRADED, 12, 12))
            self.play_id(g, old)
            self.assertIn(Keyword.RUSH, g.state.entities[old].keywords)
            self.assertEqual(len(g.state.players[1].player_effects), 1)
            if cid == DRAGON: self.portable(g)

    def test_persistent_dragon_rush_survives_source_death_duplicate_instances_and_current_control(self):
        g = self.game((ABYSSIAN, UPGRADED, TEST + 'kill', TEST + 'kill', TEST + 'remove_one', TEST + 'give'), board=(DRAGON, ALL_RACE, YETI))
        first = self.play(g, ABYSSIAN); second = self.play(g, UPGRADED)
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        dragon = self.first(g, DRAGON, 'board').id
        self.assertIn(Keyword.RUSH, g.state.entities[dragon].keywords)
        self.assertIn(Keyword.RUSH, self.first(g, ALL_RACE, 'board').keywords)
        self.assertNotIn(Keyword.RUSH, self.first(g, YETI, 'board').keywords)
        self.play(g, TEST + 'kill', first); self.play(g, TEST + 'kill', second); self.play(g, TEST + 'remove_one')
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        self.assertIn(Keyword.RUSH, g.state.entities[dragon].keywords)
        self.play(g, TEST + 'give', dragon)
        self.assertNotIn(Keyword.RUSH, g.state.entities[dragon].keywords)
        self.portable(g)

    def test_persistent_rush_uses_normal_new_minion_attacks_and_survives_beneficiary_silence(self):
        g = self.game((ABYSSIAN, DRAGON, TEST + 'silence'), enemy=(YETI,))
        self.play(g, ABYSSIAN); source = self.play(g, DRAGON)
        hero = g.state.players[2].hero_id; victim = self.first(g, YETI, 'board', 2).id
        self.assertTrue(any(isinstance(a, Attack) and a.attacker_id == source and a.defender_id == victim for a in g.legal_actions()))
        self.assertFalse(any(isinstance(a, Attack) and a.attacker_id == source and a.defender_id == hero for a in g.legal_actions()))
        self.play(g, TEST + 'silence', source)
        self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, source, hero))

    def test_three_fixed_forms_have_exact_named_counts_stats_keywords_and_no_randomness(self):
        for form, token, count in MAPPINGS:
            g = self.game((form,)); rng = g.snapshot()['rng_state']; source = self.play(g, form)
            tokens = [g.state.entities[i] for i in g.state.players[1].board if i != source]
            self.assertEqual([e.card_id for e in tokens], [token] * count)
            self.assertEqual(len({e.id for e in tokens}), count)
            self.assertEqual(g.snapshot()['rng_state'], rng)
            expected = {UND_TOKEN: (3, 3), ELE_TOKEN: (2, 2), INF_TOKEN: (6, 6)}[token]
            self.assertTrue(all((e.attack, e.max_health) == expected for e in tokens))

    def test_fixed_named_capacity_and_actual_reborn_keep_normal_native_lifecycle(self):
        g = self.game((ELE_FORM,), board=(YETI,) * 5); self.play(g, ELE_FORM)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id == ELE_TOKEN for i in g.state.players[1].board), 1)
        g = self.game((UND_FORM, TEST + 'kill')); self.play(g, UND_FORM)
        old = self.first(g, UND_TOKEN, 'board').id; self.play(g, TEST + 'kill', old)
        reborn = next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == UND_TOKEN and g.state.entities[i].id != old and g.state.entities[i].health == 1)
        self.assertIn(Keyword.TAUNT, reborn.keywords); self.assertNotIn(Keyword.REBORN, reborn.keywords)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)

    def test_fixed_summon_original_tail_waits_restores_and_failure_preserves_boundary(self):
        g = self.game((ELE_FORM,), mode='wait'); self.play(g, ELE_FORM)
        self.assertEqual(len(g.state.players[1].board), 2)
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, key='bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, key='ok')
        self.assertEqual(sum(g.state.entities[i].card_id == ELE_TOKEN for i in g.state.players[1].board), 4)


if __name__ == '__main__': unittest.main()
