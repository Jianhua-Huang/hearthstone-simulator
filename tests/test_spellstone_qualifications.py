"""Three independent held upgrades reuse ordinary healing, resource and attack facts."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, BuffStoredCard, CardClass, CardDefinition, CardType, CostSpec,
    EndTurn, Game, HandProgressSpec, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Resource, Runes, Scenario, SelectChoice, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, DamageBatch, Destroy, Draw, EquipWeapon,
    Freeze, GainResource, Heal, HealBatch, ModifyCost, RequestChoice, SpendResource, Summon)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hero_attack_history import record as attack_record
from hs_sim.engine.model import HealingKind
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry


PEARL = ('LOOT_091', 'LOOT_091t1', 'LOOT_091t2')
SPIRIT = ('LOOT_091t', 'LOOT_091t1t', 'LOOT_091t2t')
OPAL = ('TOY_645', 'TOY_645t', 'TOY_645t1')
SPINEL = ('TOY_825', 'TOY_825t', 'TOY_825t2')
FARSEER, JUSTICE = 'CS2_117', 'CS2_091'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/spellstone-qualifications.json'
PIN = '2cea7cf01559edf78f38f218cd4503a5e5c861fdbb20d15712566b9e740a4391'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete qualification raw evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original qualification card changed')
    return {row['id']: row['data'] for row in raw['records']}


def own_heal(c):
    # The packet retains its source controller independently of its recipient.
    return dict(c.event.data).get('source_controller') == c.player_id


def own_corpse_gain(c):
    return c.event.player_id == c.player_id and dict(c.event.data).get('resource') == Resource.CORPSES.value


def own_hero_declaration(c):
    window = dict(c.event.data).get('window_id')
    value = next((a for a in c.state.hero_attack_history if a.declaration.identity.record_id == window), None)
    if value is None:
        return False  # Ordinary minion declarations have no hero declaration fact.
    fact = attack_record(c.state, window).declaration.identity
    return (fact.player_id, fact.physical_hero_id, fact.declared_target_id) == (
        c.player_id, c.event.source_id, c.event.target_id)


def registry(scripts=(), *, wait=False, bad_condition=False, attack_freeze=False):
    r = opening_registry(); rows = evidence()
    for cid, condition in (('pearl', own_heal), ('spinel', own_corpse_gain), ('opal', own_hero_declaration)):
        r.register_trigger_condition(cid + '.eligible', (lambda c: 'invalid') if bad_condition else condition)
    for family, card_class, goal, event, basis, school, name in (
        (PEARL, CardClass.PALADIN, 3, 'healed', 'event_amount', SpellSchool.HOLY, 'pearl'),
        (SPINEL, CardClass.DEATH_KNIGHT, 5, 'resource_gained', 'event_amount', None, 'spinel'),
        (OPAL, CardClass.DEMON_HUNTER, 2, 'attack_declared', 'one', None, 'opal'),
    ):
        for stage in (2, 1, 0):
            cid = family[stage]; row = rows[cid]
            spec = None if stage == 2 else HandProgressSpec('event', goal, family[stage + 1],
                event=event, condition_id=name + '.eligible', amount_basis=basis,
                upgrade_cost_policy='clear_local')
            if name == 'pearl':
                body = lambda c, token=SPIRIT[stage]: (Summon(c.player_id, token),)
            elif name == 'opal':
                body = lambda c, count=stage + 1: (Draw(c.player_id, count, c.source_id),)
            else:
                def body(c, amount=stage + 1):
                    scope = MinionScope((Zone.HAND,), PoolQuery(tribes_any=('undead',)), tribe_basis='current')
                    return tuple(BuffStoredCard(ref, amount, amount, c.source_id)
                        for ref in minion_references(c.state, r, c.player_id, scope, c.source_id))
            r.register_behavior('body.' + cid, body)
            r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
                on_play='body.' + cid, hand_progress=spec, spell_school=school,
                metadata=metadata(card_class, rarity=Rarity.RARE, collectible=stage == 0,
                    runes=Runes(blood=1) if name == 'spinel' else None)))
    for cid in SPIRIT:
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], keywords=(Keyword.TAUNT,),
            metadata=metadata(CardClass.PALADIN, collectible=False, tribes=('undead',))))
    row = rows[FARSEER]
    r.register_behavior('farseer.heal', lambda c: (Heal(c.target_id, 3, c.source_id),))
    r.register_card(CardDefinition(FARSEER, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], battlecry='farseer.heal', targeting=TargetSpec(),
        metadata=metadata()))
    row = rows[JUSTICE]
    r.register_card(CardDefinition(JUSTICE, row['name'], CardType.WEAPON, cost=row['cost'],
        attack=row['attack'], durability=row['health'],
        metadata=metadata(CardClass.PALADIN, rarity=Rarity.FREE)))
    for name, tribes, corpse in (('unit', (), 1), ('undead', ('undead',), 1),
        ('all', ('all',), 1), ('no_corpse', (), 0)):
        r.register_card(CardDefinition('probe.' + name, name, CardType.MINION, attack=1, health=6,
            corpse_value=corpse, keywords=(Keyword.CHARGE,), metadata=metadata(tribes=tribes)))
    if wait:
        r.register_behavior('probe.wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        r.register_behavior('probe.noop', lambda c: ())
        r.register_card(CardDefinition('probe.progress', 'Waiting resource progress probe', CardType.SPELL,
            on_play='probe.noop', hand_progress=HandProgressSpec('event', 5, on_complete='probe.wait',
                event='resource_gained', condition_id='spinel.eligible', amount_basis='event_amount'),
            metadata=metadata()))
    if attack_freeze:
        r.register_behavior('probe.cancel', lambda c: (Freeze(c.event.source_id),))
        r.register_card(CardDefinition('probe.cancel', 'Attack cancellation probe', CardType.MINION,
            health=6, triggers=(TriggerSpec('attack_declared', 'probe.cancel'),), metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class QualificationCase(unittest.TestCase):
    def setUp(self):
        self.scripts = []; self.options = {}

    def script(self, name, callback): self.scripts.append((name, callback))

    def game(self, hand=(), *, board=(), enemy_board=(), enemy_hand=(), corpses=0, weapon=None,
        deck=('card.1',) * 18, armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10,
                corpses=corpses, weapon_card_id=weapon, armor=armor),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',) * 18,
                mana=10, max_mana=10)), seed=33), registry(self.scripts, **self.options))

    def entity(self, g, cid, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == cid)

    def progress(self, g, cid, player=1): return progress_ability(self.entity(g, cid, player))

    def play(self, g, cid, target=None):
        source = self.entity(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source, target)); return source

    def round(self, g): g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        r = registry(self.scripts, **self.options)
        restored = Game.from_snapshot(snap, r)
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def gain(self, name, amount, player=1):
        self.script(name, lambda c: (GainResource(player, Resource.CORPSES, amount),))

    def hurt_heal(self, name, damage, healing, player=1):
        self.script(name, lambda c: (Damage(c.state.players[player].hero_id, damage, c.source_id),
            Heal(c.state.players[player].hero_id, healing, c.source_id, HealingKind.SPELL)))


class PearlQualificationTests(QualificationCase):
    def test_real_three_bodies_and_actual_farseer_upgrade(self):
        for cid, token, amount in zip(PEARL, SPIRIT, (2, 4, 6)):
            with self.subTest(cid=cid):
                g = self.game((cid,)); self.play(g, cid)
                spirit = self.entity(g, token, zone=Zone.BOARD)
                self.assertEqual((spirit.attack, spirit.health, spirit.keywords), (amount, amount, {Keyword.TAUNT}))
                self.assertEqual(g.state.players[1].mana, 8)
        self.script('hurt', lambda c: (Damage(c.state.players[1].hero_id, 3),))
        g = self.game(('hurt', FARSEER, PEARL[0])); self.play(g, 'hurt')
        self.play(g, FARSEER, g.state.players[1].hero_id)
        self.assertEqual(self.progress(g, PEARL[1]).progress_completions, 1); self.portable(g)

    def test_actual_one_healed_does_not_credit_three_requested(self):
        self.hurt_heal('heal', 1, 3); g = self.game(('heal', PEARL[0])); self.play(g, 'heal')
        self.assertEqual(self.progress(g, PEARL[0]).progress_units, (1,))
        self.assertEqual([e.amount for e in g.events if e.kind == 'healed'], [1])

    def test_full_health_zero_restore_does_not_progress(self):
        self.hurt_heal('heal', 0, 12); g = self.game(('heal', PEARL[0])); self.play(g, 'heal')
        self.assertEqual(self.progress(g, PEARL[0]).progress_value, 0)
        self.assertFalse(any(e.kind == 'healed' for e in g.events))

    def test_separate_actual_heals_accumulate_and_large_heal_only_one_stage(self):
        self.hurt_heal('first', 2, 2); self.hurt_heal('second', 9, 9)
        g = self.game(('first', 'second', PEARL[0])); self.play(g, 'first'); self.play(g, 'second')
        a = self.progress(g, PEARL[1]); self.assertEqual((a.progress_value, a.progress_units), (0, (2, 1)))
        self.portable(g)

    def test_two_sources_in_one_actual_heal_batch_preserve_both_facts(self):
        self.script('two', lambda c: (Damage(c.state.players[1].hero_id, 6),
            HealBatch((Heal(c.state.players[1].hero_id, 3, c.source_id),
                Heal(c.state.players[1].hero_id, 3, c.state.players[1].hero_id)))))
        g = self.game(('two', PEARL[0])); self.play(g, 'two')
        self.assertEqual(self.progress(g, PEARL[2]).progress_units, (3, 3))
        self.assertEqual(len({e.source_id for e in g.events if e.kind == 'healed'}), 2); self.portable(g)

    def test_source_player_qualifies_independently_of_recipient(self):
        self.script('heal_enemy', lambda c: (Damage(c.state.players[2].hero_id, 3),
            Heal(c.state.players[2].hero_id, 3, c.source_id)))
        g = self.game(('heal_enemy', PEARL[0]), enemy_hand=(PEARL[0],)); self.play(g, 'heal_enemy')
        self.assertEqual(self.progress(g, PEARL[1]).progress_completions, 1)
        self.assertEqual(self.progress(g, PEARL[0], 2).progress_value, 0)

    def test_enemy_and_unattributed_healing_do_not_credit_owner(self):
        self.script('other', lambda c: (Damage(c.state.players[1].hero_id, 6),
            Heal(c.state.players[1].hero_id, 3, c.state.players[2].hero_id),
            Heal(c.state.players[1].hero_id, 3)))
        g = self.game(('other', PEARL[0])); self.play(g, 'other')
        self.assertEqual(self.progress(g, PEARL[0]).progress_value, 0)

    def test_actual_minion_healing_uses_same_fact(self):
        self.script('heal', lambda c: (Damage(c.state.players[1].board[0], 4),
            Heal(c.state.players[1].board[0], 3, c.source_id)))
        g = self.game(('heal', PEARL[0]), board=('probe.unit',)); self.play(g, 'heal')
        self.assertEqual(self.progress(g, PEARL[1]).progress_completions, 1)

    def test_acquired_after_healing_has_no_retroactive_credit(self):
        self.script('late', lambda c: (Damage(c.state.players[1].hero_id, 3),
            Heal(c.state.players[1].hero_id, 3, c.source_id), AddToHand(1, PEARL[0])))
        g = self.game(('late',)); self.play(g, 'late')
        self.assertEqual(self.progress(g, PEARL[0]).progress_value, 0); self.portable(g)


class SpinelQualificationTests(QualificationCase):
    def test_initial_corpse_bank_and_spending_do_not_progress(self):
        self.script('spend', lambda c: (SpendResource(1, Resource.CORPSES, 5, required=True),))
        g = self.game(('spend', SPINEL[0]), corpses=8); self.play(g, 'spend')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 3)
        self.assertEqual(self.progress(g, SPINEL[0]).progress_value, 0)

    def test_direct_gain_uses_actual_units_not_number_of_events(self):
        self.gain('three', 3); self.gain('two', 2)
        g = self.game(('three', 'two', SPINEL[0])); self.play(g, 'three')
        self.assertEqual(self.progress(g, SPINEL[0]).progress_units, (3,)); self.play(g, 'two')
        self.assertEqual(self.progress(g, SPINEL[1]).progress_units, (3, 2)); self.portable(g)

    def test_oversized_single_gain_upgrades_once_and_two_gains_twice(self):
        self.gain('large', 12); self.gain('next', 5)
        g = self.game(('large', 'next', SPINEL[0])); self.play(g, 'large')
        self.assertEqual(self.progress(g, SPINEL[1]).progress_units, (5,)); self.play(g, 'next')
        self.assertEqual(self.progress(g, SPINEL[2]).progress_units, (5, 5))

    def test_normal_death_and_direct_gain_share_one_progress_chain(self):
        self.gain('four', 4)
        self.script('death', lambda c: (Destroy(c.state.players[1].board[0]),))
        g = self.game(('four', 'death', SPINEL[0]), board=('probe.unit',)); self.play(g, 'four'); self.play(g, 'death')
        a = self.progress(g, SPINEL[1]); self.assertEqual(a.progress_units, (4, 1))
        event = next(e for e in g.events if e.kind == 'resource_gained' and e.source_id is not None)
        death = next(d for d in g.state.death_history if d.id == dict(event.data)['death_id'])
        self.assertEqual((event.amount, event.source_id), (death.corpse_value, death.entity_id)); self.portable(g)

    def test_death_batch_counts_each_actual_corpse_but_no_corpse_entity_does_not(self):
        self.script('batch', lambda c: (DamageBatch(tuple(Damage(i, 6, c.source_id)
            for i in c.state.players[1].board)),))
        g = self.game(('batch', SPINEL[0]), board=('probe.unit',)*5 + ('probe.no_corpse',))
        self.play(g, 'batch')
        self.assertEqual(self.progress(g, SPINEL[1]).progress_units, (1, 1, 1, 1, 1))
        self.assertEqual(len({d.batch for d in g.state.death_history}), 1)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 5); self.portable(g)

    def test_enemy_gain_and_zero_gain_do_not_count(self):
        self.script('other', lambda c: (GainResource(2, Resource.CORPSES, 7), GainResource(1, Resource.CORPSES, 0)))
        g = self.game(('other', SPINEL[0]), enemy_hand=(SPINEL[0],)); self.play(g, 'other')
        self.assertEqual(self.progress(g, SPINEL[0]).progress_value, 0)
        self.assertEqual(self.progress(g, SPINEL[1], 2).progress_completions, 1)

    def test_acquired_after_gain_starts_without_bank_credit(self):
        self.script('late', lambda c: (GainResource(1, Resource.CORPSES, 8), AddToHand(1, SPINEL[0])))
        g = self.game(('late',)); self.play(g, 'late')
        self.assertEqual(self.progress(g, SPINEL[0]).progress_value, 0)

    def test_real_three_bodies_buff_only_own_current_hand_undead(self):
        for cid, amount in zip(SPINEL, (1, 2, 3)):
            with self.subTest(cid=cid):
                g = self.game((cid, 'probe.undead', 'probe.all', 'probe.unit'),
                    enemy_hand=('probe.undead',), board=('probe.undead',), deck=('probe.undead',))
                self.play(g, cid)
                for target in ('probe.undead', 'probe.all'):
                    e = self.entity(g, target); self.assertEqual((e.attack, e.health), (1+amount, 6+amount))
                for target, p, z in (('probe.unit', 1, Zone.HAND), ('probe.undead', 2, Zone.HAND),
                    ('probe.undead', 1, Zone.BOARD), ('probe.undead', 1, Zone.DECK)):
                    e = self.entity(g, target, p, z); self.assertEqual((e.attack, e.health), (1, 6))
                self.assertEqual(g.state.players[1].mana, 9)
                self.assertFalse(any(e.kind == 'resource_spent' for e in g.events))
                self.portable(g)

    def test_finished_stage_no_longer_listens(self):
        self.script('all', lambda c: (GainResource(1, Resource.CORPSES, 5),)*3)
        g = self.game(('all', SPINEL[0])); self.play(g, 'all')
        self.assertEqual(self.progress(g, SPINEL[2]).progress_units, (5, 5))
        self.assertEqual(sum(e.kind == 'hand_card_upgraded' for e in g.events), 2)


class OpalQualificationTests(QualificationCase):
    def attack(self, g, target=None):
        g.apply(Attack(1, g.state.players[1].hero_id, target or g.state.players[2].hero_id))

    def test_four_ordinary_hero_attacks_complete_two_stages(self):
        g = self.game((OPAL[0],), weapon=JUSTICE)
        for n in range(4):
            if n: self.round(g)
            self.attack(g)
        a = self.progress(g, OPAL[2]); self.assertEqual((a.progress_completions, a.progress_units), (2, (1,)*4))
        self.assertEqual(len(g.state.hero_attack_history), 4); self.portable(g)

    def test_minion_attack_does_not_credit_hero_condition(self):
        g = self.game((OPAL[0],), board=('probe.unit',))
        g.apply(Attack(1, g.state.players[1].board[0], g.state.players[2].hero_id))
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 0)
        self.assertEqual(g.state.hero_attack_history, [])

    def test_enemy_hero_attack_is_separate(self):
        self.script('enemy_weapon', lambda c: (EquipWeapon(2, JUSTICE),))
        g = self.game(('enemy_weapon', OPAL[0]), enemy_hand=(OPAL[0],)); self.play(g, 'enemy_weapon')
        g.apply(EndTurn(1)); g.apply(Attack(2, g.state.players[2].hero_id, g.state.players[1].hero_id))
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 0)
        self.assertEqual(self.progress(g, OPAL[0], 2).progress_value, 1)

    def test_equipping_weapon_and_direct_damage_are_not_attacks(self):
        self.script('setup', lambda c: (EquipWeapon(1, JUSTICE), Damage(c.state.players[2].hero_id, 1, c.source_id)))
        g = self.game(('setup', OPAL[0])); self.play(g, 'setup')
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 0)

    def test_preexisting_attacks_are_not_credited_to_new_hand_card(self):
        self.script('later', lambda c: (AddToHand(1, OPAL[0]),))
        g = self.game(('later',), weapon=JUSTICE); self.attack(g); self.play(g, 'later')
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 0); self.portable(g)

    def test_shielded_target_still_counts_one_actual_declaration(self):
        # Zero damage is irrelevant to an attack-count condition.
        from hs_sim.engine.effects import GrantKeyword
        self.script('shield', lambda c: (GrantKeyword(c.state.players[2].board[0], Keyword.DIVINE_SHIELD),))
        g = self.game(('shield', OPAL[0]), enemy_board=('probe.unit',), weapon=JUSTICE)
        self.play(g, 'shield'); self.attack(g, g.state.players[2].board[0])
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 1)
        self.assertTrue(any(e.kind == 'damage_prevented' for e in g.events)); self.portable(g)

    def test_cancelled_declared_attack_counts_under_explicit_internal_policy(self):
        self.options['attack_freeze'] = True
        g = self.game((OPAL[0],), enemy_board=('probe.cancel',), weapon=JUSTICE); self.attack(g)
        self.assertEqual(self.progress(g, OPAL[0]).progress_value, 1)
        self.assertEqual(g.state.hero_attack_history[0].terminal.outcome, 'cancelled'); self.portable(g)

    def test_illegal_attack_has_no_fact_progress_or_resource_effect(self):
        g = self.game((OPAL[0],)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(), before)

    def test_real_three_draw_bodies_do_not_invent_upgrade_events(self):
        for cid, count in zip(OPAL, (1, 2, 3)):
            with self.subTest(cid=cid):
                g = self.game((cid,)); original = len(g.state.players[1].deck); self.play(g, cid)
                self.assertEqual(len(g.state.players[1].deck), original-count)
                self.assertEqual(len(g.state.players[1].hand), count)
                self.assertEqual(g.state.players[1].mana, 8); self.portable(g)


class QualificationLifecycleTests(QualificationCase):
    def test_full_raw_thresholds_and_distinct_family_declarations(self):
        rows = evidence(); r = registry()
        self.assertEqual(len(rows), 14)
        for family, tag, goal in ((PEARL, 'TAG_SCRIPT_DATA_NUM_2', 3),
            (OPAL, 'TAG_SCRIPT_DATA_NUM_1', 2), (SPINEL, 'TAG_SCRIPT_DATA_NUM_1', 5)):
            for cid in family[:2]:
                self.assertEqual(rows[cid]['tags'][tag], goal)
                self.assertEqual(r.card(cid).hand_progress.goal, goal)
            self.assertIsNone(r.card(family[2]).hand_progress)

    def test_current_and_base_copy_preserve_or_clear_partial_progress(self):
        self.gain('gain', 3)
        def copies(c):
            ref = CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand
                if c.state.entities[i].card_id == SPINEL[0]))
            return (CopyCard(ref, 1, mode='current'), CopyCard(ref, 1, mode='base'))
        self.script('copies', copies)
        g = self.game(('gain', 'copies', SPINEL[0])); self.play(g, 'gain'); self.play(g, 'copies')
        values = [progress_ability(g.state.entities[i]).progress_value for i in g.state.players[1].hand]
        self.assertEqual(values, [3, 3, 0]); self.portable(g)

    def test_deck_pauses_progress_and_return_retains_original_partial(self):
        self.gain('three', 3); self.gain('five', 5); self.gain('two', 2)
        def moving(c, src, dst):
            e = next(c.state.entities[i] for i in getattr(c.state.players[1], src.value)
                if c.state.entities[i].card_id == SPINEL[0])
            return (MoveCard(CardReference.capture(e), 1, dst),)
        self.script('away', lambda c: moving(c, Zone.HAND, Zone.DECK))
        self.script('back', lambda c: moving(c, Zone.DECK, Zone.HAND))
        g = self.game(('three', 'away', 'five', 'back', 'two', SPINEL[0])); self.play(g, 'three'); self.play(g, 'away')
        self.play(g, 'five'); self.play(g, 'back'); self.play(g, 'two')
        self.assertEqual(self.progress(g, SPINEL[1]).progress_units, (3, 2)); self.portable(g)

    def test_two_physical_held_cards_have_independent_progress_identities(self):
        self.gain('gain', 3); g = self.game(('gain', SPINEL[0], SPINEL[0])); self.play(g, 'gain')
        rows = [progress_ability(g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertEqual([a.progress_value for a in rows], [3, 3])
        self.assertEqual(len({a.id for a in rows}), 2); self.portable(g)

    def test_actual_upgrade_clears_local_cost_and_preserves_physical_card(self):
        def cost(c):
            e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == SPINEL[0])
            return (ModifyCost(e.id, CostSpec(delta=-1)),)
        self.script('discount', cost); self.gain('upgrade', 5)
        g = self.game(('discount', 'upgrade', SPINEL[0])); original = self.entity(g, SPINEL[0]).id
        self.play(g, 'discount'); self.assertEqual(g.quote_cost(original).amount, 0); self.play(g, 'upgrade')
        self.assertEqual(self.entity(g, SPINEL[1]).id, original)
        self.assertEqual(g.quote_cost(original).amount, 1); self.portable(g)

    def test_waiting_generic_progress_restores_clone_replays_without_double_gain(self):
        self.options['wait'] = True; self.gain('gain', 5)
        g = self.game(('gain', 'probe.progress')); self.play(g, 'gain')
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        for game in (g, restored):
            pending = game.state.pending_choice
            game.apply(SelectChoice(pending.player_id, pending.id, ('ok',)))
            self.assertEqual(game.state.players[1].resources[Resource.CORPSES], 5)
            self.assertEqual(self.progress(game, 'probe.progress').progress_units, (5,))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_bad_qualification_rolls_back_payment_resource_and_random_state(self):
        from hs_sim.engine.effects import RandomDamage
        self.options['bad_condition'] = True
        self.script('gain', lambda c: (RandomDamage(tuple(c.state.players[2].board), 1, c.source_id),
            SpendResource(1, Resource.CORPSES, 2, required=True), GainResource(1, Resource.CORPSES, 5)))
        g = self.game(('gain', SPINEL[0]), enemy_board=('probe.unit', 'probe.unit'), corpses=3)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'condition must return bool'): self.play(g, 'gain')
        self.assertEqual(g.snapshot(), before)

    def test_private_progress_and_unit_receipts_never_leak_to_opponent(self):
        self.gain('gain', 3); g = self.game(('gain', SPINEL[0])); self.play(g, 'gain')
        mine = g.observe(1); enemy = g.observe(2)
        self.assertIn('hand_progress', json.dumps(mine))
        hidden = enemy['players'][0]['hand']
        self.assertTrue(hidden)
        for card in hidden:
            self.assertNotIn('hand_progress', card); self.assertIsNone(card['card_id'])
        self.assertEqual(mine['players'][0]['hand'][0]['hand_progress']['value'], 3)
        for view in (mine, enemy):
            text = json.dumps(view)
            self.assertNotIn('progress_keys', text); self.assertNotIn('progress_units', text)
            self.assertNotIn('ability_id', text)

