"""Costume Merchant: complete named Masks and the actual generated recipient."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
from types import SimpleNamespace
import unittest

from hs_sim.cards.mask_battlecry_combo_card import CARD, MASKS, load_batch
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata, CardType,
    ComboRepeatSpec, Game, Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.battlecry_weapon_outputs import (GenerateBattlecryCard,
    GenerateBattlecryWeapon, combo_card, validate_work)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.hand_upgrades import BuffStoredCard, UpgradeHandCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerateFromCandidates, GenerateFromPool, PoolMember, PoolQuery, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k218.'
NOP, PLAIN, REPEAT = (P + x for x in ('nop', 'plain', 'repeat'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def registry(role):
    from hs_sim.cards import build_registry
    r = build_registry()
    r.register_behavior(NOP, lambda c: ())
    r.register_card(CardDefinition(NOP, NOP, CardType.SPELL, on_play=NOP, metadata=META))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=1, health=4, metadata=META))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=10, metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),), combo_repeats=(ComboRepeatSpec(),)))
    for field in ('attack','health'):
        key = P+'bad_'+field
        def bad_buff(c, field=field):
            card = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                        if c.state.entities[i].card_id in MASKS)
            return (BuffStoredCard(CardReference.capture(card), source_id=c.source_id,
                cost=CostSpec(delta=-2), **{field:1}),)
        r.register_behavior(key,bad_buff)
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,metadata=META))
    def fail(c):
        raise ResolutionError('Deliberate Mask rollback')
    r.register_behavior(P+'raise', fail)
    def wait(c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'raise', c.source_id, c.player_id),))), c.source_id),)
    def back(c):
        return (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
            Zone.HAND, source_id=c.source_id),)
    r.register_behavior(P+'back', back)
    for action in ('wait', 'fail', 'move', 'reenter', 'transfer', 'morph', 'kill', 'fill', 'combo_wait'):
        key = P+action
        def watcher(c, action=action):
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != CARD:
                return ()
            if action == 'fill':
                return tuple(AddToHand(c.player_id, NOP, c.source_id) for _ in range(10))
            if action == 'combo_wait': return wait(c)
            if c.event.target_id is None or c.state.entities[c.event.target_id].card_id not in MASKS:
                return ()
            if action == 'wait': return wait(c)
            if action == 'fail': return (InvokeBehavior(P+'raise', c.source_id, c.player_id),)
            if action == 'kill': return (Destroy(c.event.source_id),)
            original = CardReference.capture(c.state.entities[c.event.target_id])
            if action == 'morph':
                other = next(cid for cid in MASKS if cid != original.card_id)
                return (UpgradeHandCard(original, other, c.source_id),)
            work = [MoveCard(original, 3-c.player_id if action == 'transfer' else c.player_id,
                Zone.HAND if action == 'transfer' else Zone.DECK,
                source_id=c.source_id, position='top' if action != 'transfer' else 'bottom')]
            if action == 'reenter':
                work.append(InvokeBehavior(P+'back', c.source_id, c.player_id, original.entity_id))
            work.append(AddToHand(c.player_id, 'DINO_429', c.source_id))
            return tuple(work)
        r.register_behavior(key, watcher)
        event = 'battlecry_started' if action == 'fill' else 'combo_started' if action == 'combo_wait' else 'card_added_to_hand'
        r.register_card(CardDefinition(key, key, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, key),)))
    r.validate(); return r


class MaskBattlecryComboTests(unittest.TestCase):
    def game(self, hand=(NOP, CARD), board=(), owner=1, hero='HERO_03', seed=218):
        players = [PlayerSetup('HERO_08', deck=(PLAIN,)*6) for _ in (1, 2)]
        players[owner-1] = PlayerSetup(hero, hand=hand, board=board, deck=(PLAIN,)*6,
            mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario(tuple(players), active_player=owner, seed=seed), registry('writer'))

    def play(self, g, cid):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        position = len(g.state.players[p].board) if g.state.entities[eid].kind == CardType.MINION else None
        g.apply(PlayCard(p, eid, position=position)); return eid

    def combo(self, g):
        self.play(g, NOP); return self.play(g, CARD)

    def output(self, g, index=-1):
        return g.state.entities[g.state.battlecry_weapon_outputs[index].created.entity_id]

    def price(self, g, entity):
        return quote_cost(g.state, g.registry, entity).amount

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = registry('reader' if g.registry is registry('writer') else 'writer')
        self.assertIsNot(other, g.registry)
        restored = Game.from_snapshot(saved, other)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), other).snapshot(), saved)
        return restored

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_complete_bilingual_domain_and_real_assembly(self):
        data = load_batch()
        self.assertEqual((len(data['cards']), len(data['existing_dependencies'])), (1,5))
        dbfs = {row['record']['dbf_id'] for row in data['existing_dependencies']}
        self.assertEqual(len(data['official_observations']), 2)
        for face in data['official_observations']:
            self.assertEqual(set(face['face']['childIds']), dbfs)
        card = registry('writer').card(CARD)
        self.assertEqual((card.cost,card.attack,card.health), (3,2,4))
        self.assertIn(Keyword.COMBO, card.keywords)

    def test_first_card_generates_without_discount_or_invented_combo(self):
        g = self.game(hand=(CARD,)); self.play(g, CARD)
        card = self.output(g)
        self.assertIn(card.card_id, MASKS)
        self.assertEqual(self.price(g,card), g.registry.card(card.card_id).cost)
        self.assertEqual((len(g.state.battlecry_history),len(g.state.combo_history)), (1,0))
        self.check(g)

    def test_combo_binds_one_generated_spell_and_pays_only_once_both_seats(self):
        for owner in (1,2):
            g = self.game(owner=owner); source = self.combo(g); card = self.output(g)
            self.assertEqual(self.price(g,card), g.registry.card(card.card_id).cost-2)
            self.assertEqual(g.state.players[owner].mana, 27)
            row = g.state.battlecry_weapon_outputs[-1]
            self.assertEqual((row.created.kind,row.created.controller), (CardType.SPELL,owner))
            self.assertEqual(g.state.battlecry_history[row.battlecry_id-1].source_id, source)
            self.check(g)

    def test_current_mage_class_excludes_its_own_sheep_mask(self):
        for seed in (218,219,220):
            g = self.game(hero='HERO_08', seed=seed); self.play(g,NOP)
            rng = Random(); rng.setstate(g._rng.getstate())
            expected, = sample_candidates(rng, tuple(PoolMember(cid) for cid in sorted(MASKS)
                if cid != 'DINO_429'), 1, replacement=True)
            self.play(g,CARD)
            self.assertEqual(self.output(g).card_id,expected)
            self.assertEqual(g._rng.getstate(),rng.getstate())
        self.check(g)

    def test_same_named_existing_hand_card_is_not_discounted(self):
        g = self.game(hand=(NOP,CARD,*MASKS)); existing = set(g.state.players[1].hand)
        self.combo(g)
        for eid in existing & set(g.state.players[1].hand):
            card = g.state.entities[eid]
            self.assertEqual(self.price(g,card), g.registry.card(card.card_id).cost)
        self.assertEqual(self.price(g,self.output(g)), g.registry.card(self.output(g).card_id).cost-2)
        self.check(g)

    def test_repeated_battlecries_and_combos_use_last_actual_output(self):
        g = self.game(board=(REPEAT,)); self.combo(g)
        first,last = self.output(g,0),self.output(g,1)
        self.assertEqual(self.price(g,first), g.registry.card(first.card_id).cost)
        self.assertEqual(self.price(g,last), max(0,g.registry.card(last.card_id).cost-4))
        self.assertEqual((len(g.state.battlecry_history),len(g.state.combo_history)), (2,2))
        self.check(g)

    def test_creation_waiting_restores_then_discounts_original_only(self):
        g = self.game(board=(P+'wait',)); self.combo(g)
        self.assertIsNotNone(g.state.pending_choice)
        restored = self.check(g)
        for branch in (g,restored): self.choose(branch); self.check(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
        card=self.output(g); self.assertEqual(self.price(g,card),g.registry.card(card.card_id).cost-2)

    def test_combo_start_waiting_retains_output_prefix_and_recipient(self):
        g = self.game(board=(P+'combo_wait',)); self.combo(g); self.check(g)
        self.choose(g); card=self.output(g)
        self.assertEqual(self.price(g,card),g.registry.card(card.card_id).cost-2); self.check(g)

    def test_failed_waiting_choice_rolls_back_exactly(self):
        g = self.game(board=(P+'wait',)); self.combo(g); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before); self.check(g)

    def test_failed_creation_reaction_rolls_back_rng_payment_and_journal(self):
        g = self.game(board=(P+'fail',)); self.play(g,NOP); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,CARD)
        self.assertEqual(g.snapshot(),before); self.check(g)

    def test_departed_and_reentered_original_never_rebind_to_decoy(self):
        for action in ('move','reenter'):
            g=self.game(board=(P+action,)); self.combo(g)
            for entity in g.state.entities.values():
                if entity.card_id in MASKS and entity.zone in (Zone.HAND,Zone.DECK):
                    self.assertEqual(self.price(g,entity),g.registry.card(entity.card_id).cost)
            self.check(g)

    def test_transferred_original_is_not_discounted(self):
        g=self.game(board=(P+'transfer',)); self.combo(g); card=self.output(g)
        self.assertIn(card.id,g.state.players[2].hand)
        self.assertEqual(self.price(g,card),g.registry.card(card.card_id).cost); self.check(g)

    def test_transformed_original_does_not_regain_binding(self):
        g=self.game(board=(P+'morph',)); self.combo(g); card=self.output(g)
        self.assertNotEqual(card.card_id,g.state.battlecry_weapon_outputs[-1].created.card_id)
        self.assertEqual(self.price(g,card),g.registry.card(card.card_id).cost); self.check(g)

    def test_source_death_does_not_cancel_accepted_combo(self):
        g=self.game(board=(P+'kill',)); source=self.combo(g); card=self.output(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.price(g,card),g.registry.card(card.card_id).cost-2); self.check(g)

    def test_full_hand_records_burn_without_discounting_another_card(self):
        g=self.game(board=(P+'fill',)); self.combo(g); card=self.output(g)
        self.assertEqual(card.zone,Zone.GRAVEYARD)
        self.assertEqual(card.enchantments,[]); self.check(g)

    def test_private_output_and_rehashed_missing_journal_rejected(self):
        g=self.game(); self.combo(g)
        for owner in (1,2):
            dto=json.dumps(g.observe(owner))
            self.assertNotIn('battlecry_weapon_outputs',dto)
            self.assertNotIn('battlecry_weapon_bound',dto)
        saved=deepcopy(g.snapshot()); saved['state']['battlecry_weapon_outputs']=[]
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved),registry('reader'))

    def test_strict_weapon_wrapper_and_finite_request_guards(self):
        request=GenerateFromPool(1,'fixture',PoolQuery(kinds=(CardType.SPELL,),collectible=True),source_id=1)
        GenerateBattlecryCard(1,request)
        with self.assertRaises(ValueError): GenerateBattlecryWeapon(1,request)
        for bad in (replace(request,count=2),replace(request,source_id=None)):
            with self.assertRaises(ValueError): GenerateBattlecryCard(1,bad)
        with self.assertRaises(ValueError):
            validate_work(GenerateBattlecryCard(1,GenerateFromCandidates(1,(PLAIN,),1)),registry('writer'))
        with self.assertRaises(ValueError):
            validate_work(GenerateBattlecryCard(1,GenerateFromCandidates(1,(MASKS[0],PLAIN),1)),registry('writer'))

    def test_wrong_combo_consumer_kind_fails_instead_of_silently_skipping(self):
        g=self.game(); self.combo(g)
        c=SimpleNamespace(combo=g.state.combo_history[-1],state=g.state)
        self.assertEqual(combo_card(c,g.registry,kind=CardType.SPELL).entity_id,self.output(g).id)
        with self.assertRaises(ValueError): combo_card(c,g.registry,kind=CardType.WEAPON)

    def test_cost_only_spell_support_does_not_allow_spell_attack_or_health(self):
        for field in ('attack','health'):
            key=P+'bad_'+field; g=self.game(hand=(key,MASKS[0])); before=g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g,key)
            self.assertEqual(g.snapshot(),before)


if __name__ == '__main__':
    unittest.main()
