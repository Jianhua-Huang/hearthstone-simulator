"""Finite real-card sequences, causal draw counts and original drawn identities."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.spell_sequence_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastWhenDrawnSpec,
    Game, GenerationContext, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
                                  InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import Zone
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.engine.representative import HERALD_POOL_IDS
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_sequences import (DamageMinionsDrawDeaths, DecreasingMinionDamage,
    DrawSpellBatchDeaths, DrawWithCostReduction, MinionDamageWave)
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r = build_registry()
    # This isolated effect fixture supplies the explicit experimental inventory
    # used by the native Rogue/DK Soldier bodies; it is not the standard pool.
    r.register_pool(PoolDefinition('constructed.cards','k17.herald-fixture-v1',
        'local-2026-09-23','experimental',tuple(PoolMember(cid) for cid in HERALD_POOL_IDS)))
    meta = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
    for name, health, extra in (
        ('big', 20, {}), ('small', 1, {}), ('bonus', 1, dict(spell_damage=1)),
        ('shield', 20, dict(keywords=(Keyword.DIVINE_SHIELD,))),
        ('immune', 20, dict(keywords=(Keyword.IMMUNE,))),
        ('sleep', 20, dict(dormant_turns=2)),
        ('egg', 1, dict(deathrattle='k17.spawn')),
    ):
        r.register_card(CardDefinition('k17.'+name, name, CardType.MINION, health=health,
                                      attack=1, metadata=meta, **extra))
    scripts = {
        'spawn': lambda c: (Summon(c.player_id, 'CORE_CS2_182'),),
        'noop': lambda c: (),
        'wound': lambda c: (Damage(c.state.players[1].hero_id, 8, c.source_id),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k17'),),
        'auto': lambda c: (GainArmor(c.player_id, 2),),
        'cap': lambda c: (SetHandCapacity(c.player_id, 1),),
        'invalid': lambda c: (DecreasingMinionDamage(c.player_id, 99999, c.source_id, 3),),
    }
    for name, body in scripts.items(): r.register_behavior('k17.'+name, body)
    for name in ('noop', 'wound', 'invalid', 'cap'):
        r.register_card(CardDefinition('k17.'+name, name, CardType.SPELL, on_play='k17.'+name,
                                      metadata=meta))
    r.register_card(CardDefinition('k17.auto', 'auto', CardType.SPELL, cost=7,
        on_play='k17.auto', keywords=(Keyword.CASTS_WHEN_DRAWN,),
        cast_when_drawn=CastWhenDrawnSpec(), metadata=meta))
    if mode:
        def watch(c):
            if mode == 'draw':
                if c.state.entities[c.event.source_id].card_id != 'CORE_CS2_053': return ()
                entity = c.state.entities[c.event.target_id]
                reference = CardReference.capture(entity)
                options = (
                    ChoiceOption('ok', 'Extra draw', (Draw(1, source_id=c.source_id),)),
                    ChoiceOption('cycle', 'Leave and draw same card',
                        (MoveCard(reference, 1, Zone.DECK, position='top'), Draw(1, source_id=c.source_id))),
                )
            elif mode == 'death':
                if c.state.entities[c.event.target_id].card_id != 'k17.small': return ()
                options = (ChoiceOption('ok', 'Extra unrelated death', (Destroy(c.source_id),)),)
            else:
                if (c.state.entities[c.event.source_id].card_id != 'CATA_491' or
                        c.state.entities[c.event.target_id].card_id != 'k17.big'): return ()
                rows = [row for row in c.state.damage_history if row.health_result.source_card_id == 'CATA_491'
                        and row.health_result.target_card_id == 'k17.big']
                if len(rows) != 1: return ()
                options = (ChoiceOption('ok', 'Continue', (GainArmor(1, 1),)),)
            return (RequestChoice(1, (*options,
                ChoiceOption('bad', 'Rollback', (InvokeBehavior('k17.fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior('k17.watch', watch)
        r.register_card(CardDefinition('k17.watch', 'Observer', CardType.MINION, health=20, metadata=meta,
            triggers=(TriggerSpec({'draw':'card_drawn','death':'minion_died'}.get(mode,'damage_dealt'), 'k17.watch'),)))
    return r


class SpellSequenceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry = registry()

    def game(self, hand=(), *, board=(), enemy=(), deck=('CORE_CS2_182',)*6,
             hero='HERO_02', mode=None, hand_cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=deck, mana=30, max_mana=30,
                        mana_cap=30, hand_cap=hand_cap),
            PlayerSetup('HERO_08', board=enemy, deck=('CORE_CS2_182',)*5)), seed=251,
            generation_context=GenerationContext('local-2026-09-23', 'experimental')),
            registry(mode) if mode else self.registry)
    def play(self, g, cid, target=None):
        eid = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid
    def rows(self, g, cid, target=None):
        return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id == cid
                and (target is None or r.health_result.target_id == target)]
    def choose(self, g, option='ok'):
        choice = g.state.pending_choice; g.apply(SelectChoice(choice.player_id, choice.id, (option,)))
    def price(self, g, eid):
        state = g.state; return quote_cost(state, g.registry, state.entities[eid]).amount
    def portable(self, g, mode=None):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved)
        return other

    def test_full_seven_source_records_and_all_printed_keywords(self):
        rows = load_batch()['cards']; self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            card = self.registry.card(row['record']['id'])
            self.assertEqual(card.cost, row['record']['cost'])
            for keyword in (Keyword.COMBO, Keyword.OUTCAST, Keyword.HERALD):
                self.assertEqual(keyword in card.keywords, row['record']['tags'].get(keyword.name) == 1)

    def test_tentacles_three_two_one_and_both_seats(self):
        g = self.game(('CATA_491',), board=('k17.big',), enemy=('k17.big',))
        ids = [g.state.players[p].board[0] for p in (1, 2)]
        self.play(g, 'CATA_491')
        for eid in ids:
            self.assertEqual([row.base_amount for row in self.rows(g, 'CATA_491', eid)], [3,2,1])
            self.assertEqual(g.state.entities[eid].health, 14)

    def test_tentacles_quote_bonus_once_even_provider_dies_and_requery_death_spawn(self):
        g = self.game(('CATA_491',), board=('k17.bonus',), enemy=('k17.egg','k17.big'))
        big = g.state.players[2].board[1]
        self.play(g, 'CATA_491')
        self.assertEqual([r.base_amount for r in self.rows(g,'CATA_491',big)], [4,3,2,1])
        spawned = [r for r in self.rows(g,'CATA_491') if r.target_card_id == 'CORE_CS2_182']
        self.assertEqual([r.base_amount for r in spawned], [3,2])
        self.assertTrue(all(r.spell_bonus == 0 for r in self.rows(g, 'CATA_491')))

    def test_tentacles_shield_immune_dormant_and_empty(self):
        g = self.game(('CATA_491',), enemy=('k17.shield','k17.immune','k17.sleep'))
        shield, immune, sleep = g.state.players[2].board
        self.play(g, 'CATA_491')
        self.assertEqual([r.damage_dealt for r in self.rows(g,'CATA_491',shield)],[0,2,1])
        self.assertEqual(g.state.entities[immune].health,20); self.assertFalse(self.rows(g,'CATA_491',sleep))
        empty = self.game(('CATA_491',)); self.play(empty,'CATA_491')
        self.assertFalse(self.rows(empty,'CATA_491'))

    def test_tentacles_waiting_codec_rollback_restore_clone_replay_and_projection(self):
        g = self.game(('CATA_491',), board=('k17.watch',), enemy=('k17.big',), mode='wave')
        self.play(g,'CATA_491'); self.assertIsNotNone(g.state.pending_choice)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(), before)
        other = self.portable(g,'wave')
        for current in (g,other): self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertNotIn('MinionDamageWave',json.dumps(g.observe(2)))
        self.assertNotIn('cast_history',json.dumps(g.observe(2)))

    def test_last_stand_counts_simultaneous_actual_deaths_both_sides(self):
        g = self.game(('CATA_526',), board=('k17.small',), enemy=('k17.small','CORE_EX1_008'))
        self.play(g,'CATA_526')
        self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(len({r.batch_id for r in self.rows(g,'CATA_526')}),1)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],['CORE_CS2_182']*2)

    def test_last_stand_does_not_count_deathrattle_draw_or_spawn_as_killed(self):
        g = self.game(('CATA_526',), enemy=('CORE_EX1_012','k17.egg'))
        # Enemy bloodmage draws for its own death; only two original deaths reward player 1.
        self.play(g,'CATA_526')
        self.assertEqual(sum(r.player_id == 1 for r in g.state.draw_history),2)
        self.assertEqual(sum(r.player_id == 2 for r in g.state.draw_history),1)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].board],['CORE_CS2_182'])

    def test_last_stand_empty_and_protected_no_draw_fatigue_uses_shared_flow(self):
        for enemy in ((),('CORE_EX1_008',)):
            g = self.game(('CATA_526',),enemy=enemy,deck=()); self.play(g,'CATA_526')
            self.assertFalse(g.state.draw_history)
        g = self.game(('CATA_526',),enemy=('k17.small','k17.small'),deck=())
        self.play(g,'CATA_526')
        self.assertEqual([r.outcome for r in g.state.draw_history],['fatigue','fatigue'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_last_stand_waiting_unrelated_destroy_not_counted_and_portable(self):
        g = self.game(('CATA_526',),board=('k17.watch',),enemy=('k17.small',),mode='death')
        self.play(g,'CATA_526'); self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.draw_history)
        other=self.portable(g,'death')
        for current in (g,other): self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(len(g.state.death_history),2)

    def test_flash_flood_single_minion_two_packets_and_shield(self):
        g=self.game(('k17.noop','CATA_533','k17.noop'),enemy=('k17.shield',))
        eid=g.state.players[2].board[0]; self.play(g,'CATA_533')
        self.assertEqual([r.damage_dealt for r in self.rows(g,'CATA_533',eid)],[0,5])

    def test_flash_flood_outcast_recaptures_new_edges_after_first_deaths(self):
        g=self.game(('CATA_533',),enemy=('k17.small','k17.big','k17.small'))
        middle=g.state.players[2].board[1]; self.play(g,'CATA_533')
        self.assertEqual([r.damage_dealt for r in self.rows(g,'CATA_533',middle)],[5,5])
        self.assertEqual(g.state.entities[middle].health,10)

    def test_flash_flood_dormant_end_does_not_shift_inward(self):
        g=self.game(('k17.noop','CATA_533','k17.noop'),enemy=('k17.sleep','k17.big','k17.big'))
        sleep,middle,right=g.state.players[2].board; self.play(g,'CATA_533')
        self.assertFalse(self.rows(g,'CATA_533',sleep)); self.assertFalse(self.rows(g,'CATA_533',middle))
        self.assertEqual(g.state.entities[right].health,15)

    def test_far_sight_original_cost_floor_and_full_deck_identity(self):
        g=self.game(('CORE_CS2_053',),deck=('CORE_CS2_182',)); self.play(g,'CORE_CS2_053')
        record=g.state.draw_history[0]; self.assertEqual(record.card_id,'CORE_CS2_182')
        self.assertEqual(self.price(g,record.entity_id),1)
        g=self.game(('CORE_CS2_053',),deck=('CORE_EX1_008',)); self.play(g,'CORE_CS2_053')
        self.assertEqual(self.price(g,g.state.draw_history[0].entity_id),0)

    def test_far_sight_cast_when_drawn_replacement_is_not_discounted(self):
        g=self.game(('CORE_CS2_053',),deck=('k17.auto','CORE_CS2_182'))
        self.play(g,'CORE_CS2_053')
        self.assertEqual([r.outcome for r in g.state.draw_history],['cast','hand'])
        self.assertEqual(self.price(g,g.state.draw_history[1].entity_id),4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2); self.portable(g)

    def test_far_sight_fatigue_and_burn_do_not_discount_other_cards(self):
        g=self.game(('CORE_CS2_053',),deck=()); self.play(g,'CORE_CS2_053')
        self.assertEqual(g.state.draw_history[0].outcome,'fatigue')
        g=self.game(('k17.cap','CORE_CS2_053','CORE_CS2_182'))
        self.play(g,'k17.cap')
        self.play(g,'CORE_CS2_053'); self.assertEqual(g.state.draw_history[0].outcome,'burned')
        self.assertEqual(self.price(g,g.state.players[1].hand[0]),4)

    def test_far_sight_waiting_extra_draw_does_not_change_discount_subject(self):
        g=self.game(('CORE_CS2_053',),board=('k17.watch',),mode='draw')
        self.play(g,'CORE_CS2_053'); original=g.state.draw_history[0].entity_id
        self.assertEqual(self.price(g,original),4)
        before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        other=self.portable(g,'draw')
        for current in (g,other): self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.price(g,original),1)
        self.assertEqual(self.price(g,g.state.draw_history[1].entity_id),4)

    def test_far_sight_departure_and_redraw_same_physical_entity_does_not_rebind(self):
        g=self.game(('CORE_CS2_053',),board=('k17.watch',),mode='draw')
        self.play(g,'CORE_CS2_053'); original=g.state.draw_history[0].entity_id
        self.choose(g,'cycle')
        self.assertEqual(g.state.draw_history[1].entity_id,original)
        self.assertEqual(self.price(g,original),4)

    def test_embrace_heal_draw_then_shaman_imbue_with_fatigue(self):
        g=self.game(('k17.wound','EDR_231'),deck=())
        self.play(g,'k17.wound'); hero=g.state.players[1].hero_id
        self.play(g,'EDR_231',hero)
        self.assertEqual(g.state.entities[hero].health,25)
        self.assertEqual(len(g.state.imbue_history),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_448p')
        self.portable(g)

    def test_rite_no_combo_has_no_target_and_combo_damage_after_herald(self):
        g=self.game(('CATA_785',),hero='HERO_03'); self.play(g,'CATA_785')
        self.assertEqual(len(g.state.herald_history),1)
        self.assertFalse(self.rows(g,'CATA_785'))
        g=self.game(('k17.noop','CATA_785'),hero='HERO_03',enemy=('k17.big',))
        self.play(g,'k17.noop'); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'CATA_785')
        self.assertEqual(g.snapshot(),before)
        eid=g.state.players[2].board[0]; self.play(g,'CATA_785',eid)
        self.assertEqual(g.state.entities[eid].health,17)
        self.assertEqual(len(g.state.herald_history),1)

    def test_animation_herald_before_enemy_only_batch_and_no_friendly_fire(self):
        g=self.game(('CATA_156',),hero='HERO_11',board=('k17.big',),enemy=('k17.big',))
        own=g.state.players[1].board[0]; enemy=g.state.players[2].board[0]
        self.play(g,'CATA_156'); self.assertEqual(len(g.state.herald_history),1)
        self.assertEqual(g.state.entities[own].health,20); self.assertEqual(g.state.entities[enemy].health,16)
        self.assertEqual(len(self.rows(g,'CATA_156')),1); self.portable(g)

    def test_invalid_active_cast_rejected_and_command_rolled_back(self):
        g=self.game(('k17.invalid',),enemy=('k17.big',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'k17.invalid')
        self.assertEqual(g.snapshot(),before)

    def test_typed_sequence_request_rejects_impossible_numbers(self):
        for factory in (lambda:MinionDamageWave(1,1,1,3,4),
                lambda:DecreasingMinionDamage(1,1,1,0),
                lambda:DamageMinionsDrawDeaths(3,1,1,1),
                lambda:DrawSpellBatchDeaths(1,1,1,0),
                lambda:DrawWithCostReduction(1,-1,1)):
            with self.assertRaises(ValueError): factory()
