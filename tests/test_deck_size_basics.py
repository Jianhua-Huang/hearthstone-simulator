"""One real original deck-size source with the existing initial-health body."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckSizeRule,
    DeckValidationError, EndTurn, Game, OpeningHook, PlayCard, PlayerSetup,
    Rarity, ResolutionError, Runes, Scenario, SelectChoice, SnapshotError, Zone,
    validate_deck)
from hs_sim.engine.deck_size_rules import active_rule, expected_size
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy,
    Heal, InvokeBehavior, RequestChoice, SetStats)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

RENATHAL = 'REV_018'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/deck-size-basics.json'
PIN = '4c4909364876da5a57a967d650158857a2da8bf797519d43df00b04d11801a6c'
RULE = DeckSizeRule(RENATHAL, 40)


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete original deck-size source changed')
    row = raw['records'][0]
    if row['id'] != RENATHAL or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Original Renathal row changed')
    return row['data']


def registry(*, wait=False, fault=False, scripts=(), rule=RULE):
    r = opening_registry(); row = evidence()
    # Initial health already has an ordinary, suspendable opening expression.
    # No on-play/battlecry body: later playing a generated Renathal is a 3/4.
    def renathal_start(c):
        if r.deck_size_rules.get(RENATHAL) != RULE:
            raise ResolutionError('The pinned Renathal adapter requires its reviewed40 deck-size rule')
        return (SetStats(c.state.players[c.player_id].hero_id, health=40, source_id=c.source_id),)
    r.register_behavior('renathal.start', renathal_start)
    r.register_card(CardDefinition(RENATHAL, row['name'], CardType.MINION,
        cost=row['cost'], attack=row['attack'], health=row['health'],
        opening_hooks=(OpeningHook('before_deal', 'renathal.start'),),
        metadata=metadata(rarity=Rarity.LEGENDARY)))
    if rule is not None:
        r.register_deck_size_rule(rule)
    r.register_behavior('fixture.noop', lambda c: ())
    for cid, callback in scripts:
        r.register_behavior(cid, callback)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    if wait:
        r.register_behavior('opening.fault', lambda c: (AddToHand(c.player_id, 'missing.after.initial.health'),))
        r.register_behavior('opening.wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue'),), c.source_id),) +
            ((InvokeBehavior('opening.fault', c.source_id, c.player_id),) if fault else ()))
        r.register_card(CardDefinition('opening.wait', 'Original opening work fixture', CardType.SPELL,
            on_play='fixture.noop', opening_hooks=(OpeningHook('before_deal', 'opening.wait'),), metadata=metadata()))
    return r


def forty(*extras):
    return (RENATHAL, *extras, *(f'card.{n}' for n in range(1, 40-len(extras))))


class DeckSizeConstructionTests(unittest.TestCase):
    def report(self, cards=None, *, cls=CardClass.MAGE, runes=None, r=None, p=None):
        r = r or registry()
        return validate_deck(deck(cls, forty() if cards is None else cards, runes), r, p or policy(r))

    def codes(self, report):
        return [i.code for i in report.issues]

    def test_full_real_source_and_printed_stats_are_pinned(self):
        row = evidence()
        original = next(r for r in json.loads((FIXTURE.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8')) if r['id'] == RENATHAL)
        self.assertEqual(row, original)
        self.assertEqual((row['cost'], row['attack'], row['health']), (3, 3, 4))
        self.assertEqual(row['tags']['DECK_RULE_MOD_DECK_SIZE'], 40)
        self.assertIn('starting Health are 40', row['text_en'])
        self.assertIsNone(registry().card(RENATHAL).battlecry)

    def test_source_changes_only_its_own_expected_main_size(self):
        r = registry(); p = policy(r)
        self.assertEqual(expected_size(deck(cards=forty()), r, p), 40)
        self.assertEqual(expected_size(deck(), r, p), 30)
        self.assertTrue(self.report().valid)
        self.assertTrue(self.report(deck().cards).valid)

    def test_source_requires_exact_forty_no_automatic_filling_or_truncation(self):
        for cards in (forty()[:-1], forty() + ('card.40',), (RENATHAL,) + deck().cards[:29]):
            self.assertIn('deck_size', self.codes(self.report(cards)))
        self.assertIn('deck_size', self.codes(self.report(tuple(f'card.{i}' for i in range(1,41)))))

    def test_banned_rotated_or_foreign_source_cannot_grant_size(self):
        r = registry(); p = policy(r)
        for invalid in (replace(p, banned_card_ids=(RENATHAL,)),
                replace(p, allowed_card_ids=tuple(cid for cid in p.allowed_card_ids if cid != RENATHAL))):
            self.assertIsNone(active_rule(deck(cards=forty()), r, invalid))
            report = self.report(r=r, p=invalid)
            self.assertIn('format_legality', self.codes(report)); self.assertIn('deck_size', self.codes(report))
        # Qualification cannot hide a class violation in the source declaration.
        r = registry(); r._cards[RENATHAL] = replace(r.card(RENATHAL), metadata=metadata(CardClass.WARRIOR, rarity=Rarity.LEGENDARY))
        self.assertIsNone(active_rule(deck(cards=forty()), r, policy(r)))
        self.assertIn('class', self.codes(self.report(r=r)))

    def test_unknown_member_copy_limits_and_collectibility_stay_strict(self):
        self.assertIn('unsupported_definition', self.codes(self.report(forty('missing'))))
        self.assertIn('uncollectible', self.codes(self.report(forty('coin'))))
        self.assertIn('copy_limit', self.codes(self.report(forty('card.1', 'card.1'))))
        relaxed = policy(registry(), legendary_copies=2)
        report = self.report(forty(RENATHAL), p=relaxed)
        self.assertIn('deck_rule_sources', self.codes(report))

    def test_original_dk_loadout_and_format_complete_guard_remain(self):
        self.assertTrue(self.report(cls=CardClass.DEATH_KNIGHT, runes=Runes(3)).valid)
        self.assertIn('rune_loadout', self.codes(self.report(cls=CardClass.DEATH_KNIGHT)))
        r = registry()
        with self.assertRaisesRegex(ValueError, 'complete'):
            replace(policy(r), mode='wild')

    def test_unregistered_declaration_does_not_implicitly_change_construction(self):
        r = registry(rule=None)
        self.assertEqual(expected_size(deck(cards=forty()), r, policy(r)), 30)
        self.assertIn('deck_size', self.codes(self.report(r=r)))

    def test_incomplete_real_adapter_explicitly_refuses_an_ordinary_thirty_deck(self):
        r=registry(rule=None)
        config=setup(r,decks=(deck(cards=(RENATHAL,)+deck().cards[:29]),deck(CardClass.WARRIOR)))
        with self.assertRaisesRegex(ResolutionError,'reviewed40'):
            Game.from_decks(config,r)

    def test_strict_rule_immutable_registry_and_identity(self):
        for factory in (lambda: DeckSizeRule('',40), lambda: DeckSizeRule(RENATHAL,True),
                lambda: DeckSizeRule(RENATHAL,7), lambda: DeckSizeRule(RENATHAL,40,'unknown')):
            with self.assertRaises(ValueError): factory()
        r = registry()
        with self.assertRaises(ValueError): r.register_deck_size_rule(RULE)
        with self.assertRaises(ValueError): r.register_deck_size_rule('40')
        with self.assertRaises(TypeError): r.deck_size_rules[RENATHAL] = RULE
        self.assertNotEqual(r.fingerprint(), registry(rule=replace(RULE,deck_size=41)).fingerprint())
        r.freeze()
        with self.assertRaises(ValueError): r.register_deck_size_rule(DeckSizeRule('another',40))

    def test_unknown_or_unreviewed_source_cannot_freeze(self):
        for rule in (DeckSizeRule('missing',40), DeckSizeRule('card.1',40)):
            with self.assertRaises(ValueError): registry(rule=rule).freeze()

    def test_invalid_extended_deck_rejects_before_freeze_or_any_opening(self):
        r = registry(); config = setup(r, decks=(deck(cards=forty()[:-1]), deck(CardClass.WARRIOR)))
        with self.assertRaises(DeckValidationError): Game.from_decks(config,r)
        r.register_behavior('still.mutable',lambda c:())

    def test_actual_minimum_opening_checks_each_validated_size(self):
        r = registry(); config = setup(r, decks=(deck(cards=forty()),deck(CardClass.WARRIOR,forty())),deck_size=1)
        g = Game.from_decks(config,r)
        self.assertEqual(len(g.state.players[1].original_deck),40)
        self.assertEqual(len(g.state.players[2].original_deck),40)


class DeckSizeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.options = {'scripts':()}

    def game(self, *, actor=1, wait=False, fault=False, extras=(), other_cards=None, cls=CardClass.MAGE, runes=None, seed=None):
        self.options.update(wait=wait, fault=fault)
        r = registry(**self.options)
        own = deck(cls,forty(*(('opening.wait',) if wait else ()),*extras),runes)
        other = deck(CardClass.WARRIOR,other_cards)
        return Game.from_decks(setup(r, first=actor, seed=(0 if actor==1 else 2) if seed is None else seed,
            decks=(own,other) if actor==1 else (other,own)),r)

    def choose(self,g,option_ids=()):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,option_ids))

    def finish(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;self.choose(g,('ok',) if q.options[0].id=='ok' else ())
        return g

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry(**self.options))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(**self.options)).snapshot(),saved)
        for actor in (1,2):self.assertEqual(restored.observe(actor),g.observe(actor))
        return restored

    def hero(self,g,actor=1):
        return g.state.entities[g.state.players[actor].hero_id]

    def reach(self,g,cid,actor=1):
        for _ in range(16):
            source=next((i for i in g.state.players[actor].hand if g.state.entities[i].card_id==cid),None)
            if source is not None and g.state.active_player==actor and g.state.players[actor].mana>=g.registry.card(cid).cost:return source
            g.apply(EndTurn(g.state.active_player))
        self.fail('Necessary card did not reach its ordinary paid action')

    def test_forty_vs_thirty_same_policy_and_both_opening_seats_recover(self):
        for actor in (1,2):
            g=self.game(actor=actor)
            self.assertEqual((self.hero(g,actor).health,self.hero(g,actor).max_health),(40,40))
            self.assertEqual((self.hero(g,3-actor).health,self.hero(g,3-actor).max_health),(30,30))
            self.assertEqual(len(g.state.players[actor].original_deck),40)
            self.assertEqual(len(g.state.players[3-actor].original_deck),30)
            self.assertEqual(len(g.state.players[actor].hand),3)
            self.portable(g);self.choose(g);self.portable(g);self.finish(g);self.portable(g)

    def test_partial_mulligan_uses_forty_original_entities_and_does_not_repeat_health(self):
        g=self.game();offered=g.state.pending_choice.options
        self.choose(g,(offered[0].id,));self.portable(g)
        self.finish(g)
        self.assertEqual(self.hero(g).max_health,40)
        changes=[e for e in g.events if e.kind=='stats_changed' and e.target_id==self.hero(g).id]
        self.assertEqual(len(changes),1)
        self.assertEqual(len(g.state.opening.original_entities[0]),40)
        self.assertEqual(len(g.state.players[1].original_deck),40)
        self.portable(g)

    def test_existing_initial_health_effect_creates_no_rng_or_healing_fact(self):
        g=self.game()
        self.assertFalse(any(e.kind in ('healed','resource_gained') for e in g.events))
        # Compare with the exact two ordinary shuffle operations. No extra
        # source sampling, replacement hand or preliminary draw was performed.
        import random
        rng=random.Random(0);one=list(range(40));two=list(range(30));rng.shuffle(one);rng.shuffle(two)
        self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(self.hero(g).base_health,30)
        self.assertEqual(self.hero(g).enchantments[0].set_health,40)
        self.assertEqual(len(self.hero(g).enchantments),1)

    def test_startup_work_waiting_before_deal_restores_then_deals_normally(self):
        g=self.game(wait=True)
        self.assertEqual(g.state.opening.stage,'dealing')
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(self.hero(g).health,40)
        self.portable(g);self.choose(g,('ok',));self.portable(g);self.finish(g);self.portable(g)
        self.assertEqual(self.hero(g).health,40)

    def test_late_startup_error_rolls_back_only_the_failed_resume(self):
        g=self.game(wait=True,fault=True);before=g.snapshot()
        self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,('ok',))
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(self.hero(g).health,40)

    def test_later_paid_renathal_and_ordinary_death_do_not_reset_initial_health(self):
        self.options['scripts']=(('hurt',lambda c:(Damage(c.state.players[c.player_id].hero_id,7,c.source_id),)),
            ('kill.source',lambda c:tuple(Destroy(i,c.source_id) for i in c.state.players[c.player_id].board)))
        g=self.finish(self.game(extras=('hurt','kill.source'),seed=192))
        source=self.reach(g,RENATHAL);g.apply(PlayCard(1,source))
        hurt=self.reach(g,'hurt');g.apply(PlayCard(1,hurt))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(33,40))
        kill=self.reach(g,'kill.source');g.apply(PlayCard(1,kill))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(33,40))
        self.assertEqual(expected_size(g._match_setup.decks[0],g.registry,g._match_setup.policy),40)
        self.portable(g)

    def test_scenario_renathal_has_no_retroactive_startup(self):
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(RENATHAL,),mana=3,max_mana=3),
            PlayerSetup('warrior.hero')),seed=0),registry())
        source=g.state.players[1].hand[0];g.apply(PlayCard(1,source))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,30))
        self.assertFalse(self.hero(g).enchantments)
        self.portable(g)

    def test_later_generated_source_keeps_original_thirty_and_ordinary_health(self):
        self.options['scripts']=(('grant.source',lambda c:(AddToHand(c.player_id,RENATHAL,c.source_id),)),)
        r=registry(**self.options)
        own=deck(cards=('grant.source',)+tuple(f'card.{n}' for n in range(1,30)))
        g=self.finish(Game.from_decks(setup(r,decks=(own,deck(CardClass.WARRIOR)),first=1,seed=0),r))
        grant=self.reach(g,'grant.source');g.apply(PlayCard(1,grant))
        source=self.reach(g,RENATHAL);g.apply(PlayCard(1,source))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,30))
        self.assertEqual(expected_size(g._match_setup.decks[0],g.registry,g._match_setup.policy),30)
        self.assertEqual(g.state.players[1].original_deck,own.cards)
        self.portable(g)

    def test_ordinary_healing_caps_at_initial_forty_after_real_damage(self):
        self.options['scripts']=(('hurt',lambda c:(Damage(c.state.players[c.player_id].hero_id,7,c.source_id),)),
            ('heal',lambda c:(Heal(c.state.players[c.player_id].hero_id,99,c.source_id),)))
        g=self.finish(self.game(extras=('hurt','heal'),seed=192))
        hurt=self.reach(g,'hurt');g.apply(PlayCard(1,hurt))
        self.assertEqual(self.hero(g).health,33)
        heal=self.reach(g,'heal');g.apply(PlayCard(1,heal))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
        self.assertTrue(any(e.kind=='healed' and e.amount==7 for e in g.events))
        self.portable(g)

    def test_first_turn_and_subsequent_owner_clocks_remain_ordinary(self):
        g=self.finish(self.game())
        self.assertEqual((g.state.turn,g.state.active_player),(1,1))
        for _ in range(4):g.apply(EndTurn(g.state.active_player))
        self.assertEqual((g.state.turn,g.state.active_player),(5,1))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
        self.portable(g)

    def test_enemy_hidden_cards_stay_independent_and_rule_storage_is_not_published(self):
        other=tuple(f'card.{n}' for n in range(1,31))
        g=self.game(other_cards=other);h=self.game(other_cards=tuple(f'card.{n}' for n in range(11,41)))
        self.assertEqual(g.observe(1),h.observe(1))
        self.assertEqual(g.for_player(1).legal_actions(),h.for_player(1).legal_actions())
        enemy=json.dumps(g.observe(2))
        self.assertNotIn(RENATHAL,enemy)
        self.assertNotIn('deck_size_rules',enemy)
        self.assertNotIn('original_deck',enemy)

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return s

    def test_rehashed_origin_size_class_and_policy_changes_are_rejected(self):
        g=self.game();saved=g.snapshot()
        for edit in (lambda s:s['state']['players']['1']['original_deck'].pop(),
                lambda s:s['state']['players']['1'].__setitem__('deck_class',CardClass.WARRIOR.value),
                lambda s:s['match_setup']['decks'][0]['cards'].pop(),
                lambda s:s['match_setup']['policy'].__setitem__('banned_card_ids',[RENATHAL])):
            bad=deepcopy(saved);edit(bad)
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(**self.options))

    def test_registration_change_rejects_waiting_origin(self):
        g=self.game()
        with self.assertRaisesRegex(SnapshotError,'fingerprint'):
            Game.from_snapshot(g.snapshot(),registry(rule=replace(RULE,deck_size=41)))

    def test_rule_only_version_update_preserves_state_effect_and_player_layouts(self):
        g=self.game()
        self.assertEqual((g.ruleset.id,g.mechanics.version,g.snapshot()['schema_version']),
            ('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION))
        self.assertNotIn('deck_size_rule',g.snapshot()['state']['players']['1'])
