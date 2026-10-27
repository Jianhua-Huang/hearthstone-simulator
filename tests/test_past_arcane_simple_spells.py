"""Original Arcane spell identities use full ordinary pools and real cast paths."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_simple_spells as native
from hs_sim.cards.candidate_generation_catalog import candidate_pool_rows
from hs_sim.cards.simple_followup_p89_cards import QUERIES
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, IllegalAction, Keyword,
    PlayerSetup, ResolutionError, Scenario, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest
from tools import card_batch as batch

P = 'k589.'
UNIT, POWER, FRAGILE, WATCH, FAULT = (P+v for v in ('unit','power','fragile','watch','fault'))
FULL = GenerationContext(P+'complete84-native-audit','experimental')


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def fail(c): raise ResolutionError('K589 deliberate continuation failure')
    def death(c):
        if mode == 'missile-wait':
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
        return (SummonByCard(c.player_id,(SummonEntryMaterial(UNIT),),SummonCause.capture(c)),)
    def watch(c):
        e = c.event
        source = c.state.entities.get(e.source_id)
        if e.player_id != c.player_id or source is None or source.card_id not in native.LEAVES: return ()
        if mode == 'generation-fail' and len(c.state.players[c.player_id].hand) >= 2:
            return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
        if mode != 'delivery-wait': return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(FAULT,fail); r.register_behavior(P+'death',death); r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=1,attack=1,health=6))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=5,spell_damage=1))
    r.register_card(CardDefinition(FRAGILE,FRAGILE,CardType.MINION,attack=1,health=1,deathrattle=P+'death'))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),)))
    if mode == 'full-reference':
        reference = batch.read(native.load_batch()['reference_document']); rows = reference['candidate_records']
        zeros = {v['record']['id']:dict(record=v['record'],reviewed_cost=0) for v in rows if v['record']['cost'] is None}
        # The raw tag is a positive threshold, not a Boolean keyword tag.
        thirst = {v['record']['id']:v['record']['tags']['MANATHIRST'] for v in rows if 'MANATHIRST' in v['record']['tags']}
        if thirst != {'RLK_804':6,'RLK_843':8}: raise ValueError('Unreviewed full-reference Manathirst metadata')
        overrides = {cid:('manathirst',) for cid in thirst}
        for row in candidate_pool_rows(batch=dict(cards=rows,printed_keyword_overrides=overrides),zero_costs=zeros,zero_attacks={}):
            if row.card_id not in r.pool_cards: r.register_pool_card(row)
        r.register_pool(PoolDefinition('constructed.past.cards',P+'complete-raw84',FULL.target_id,FULL.mode,
            tuple(PoolMember(cid) for cid in reference['candidate_ids']),complete=True))
    r.validate(); return f


def ordinary_candidates(g,cid,query):
    return resolve_candidates(g.registry,g._generation_context,native.POOL,query,
        current_class=g.state.players[g.state.active_player].hero_class if query.class_mode == 'current' else None,
        source_card_id=cid,player_id=g.state.active_player,exclude_source_by_rule=True)


def seed_for(cid,query,desired,*,count=1,discover=False):
    f = host(); rows = resolve_candidates(f.registry,f.context,native.POOL,query,
        source_card_id=cid,exclude_source_by_rule=True)
    if desired not in {v.card_id for v in rows}: raise ValueError('Expected followup is outside the actual full ordinary pool: '+desired)
    return next(n for n in range(20000) if desired in sample_candidates(Random(n),rows,3 if discover else count,replacement=not discover))


class PastArcaneSimpleSpellTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode,role:host(mode,role).registry)

    def game(self,hand=(),*,own=(),enemy=(),deck=None,seed=3,player=1,hero='HERO_08',mode='normal'):
        self.mode = mode; f = host(mode)
        if mode in ('generation-fail','delivery-wait'): own = (WATCH,*own)
        players = tuple(PlayerSetup(hero if p == player else 'HERO_08',hand=hand if p == player else (),
            board=own if p == player else enemy,deck=((UNIT,)*12 if deck is None else deck) if p == player else (UNIT,)*12,
            mana=60,max_mana=60,mana_cap=60) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,
            generation_context=FULL if mode == 'full-reference' else f.context),f.registry)

    def damage_rows(self,g,cid):
        return [v.health_result for v in g.state.damage_history if v.health_result.source_card_id == cid]

    def test_full84_reference_complete_rows_primary_faces_zeros_and_dynamic_display(self):
        d = native.load_batch(); ref = batch.read(d['reference_document'])
        self.assertEqual(len(ref['candidate_ids']),84); self.assertEqual(len(set(ref['candidate_ids'])),84)
        self.assertEqual(len(ref['official_observations']),170)
        raw = {v['record']['id']:v['record'] for v in ref['candidate_records']}
        raw['TIME_857'] = ref['source_producer']['record']
        for face in ref['official_observations']:
            cid = face['card_id']; batch.check_face(raw[cid],face['face'],face['locale'],
                ref['display_normalizations'].get(cid),numeric_normalizations=ref['numeric_normalizations'].get(cid))
        self.assertEqual(ref['display_normalizations'],{'ETC_528':{'@':''}})
        self.assertEqual(set(ref['numeric_normalizations']),{'CS2_008','LOOT_104'})
        self.assertEqual(len(ref['class_metadata_views']['mage']),57)
        self.assertEqual(ref['class_metadata_views']['warrior'],[])
        self.assertFalse(ref['membership_uses_executable_coverage']); self.assertFalse(ref['runtime_bindings_added'])

    def test_batch_complete_fifteen_roots_named_forms_and_original_body_pins(self):
        d = native.load_batch(); r = host().registry
        raw = {v['record']['id']:v['record'] for v in d['dependencies']+d['existing_dependencies']}
        for face in d['official_observations']: batch.check_face(raw[face['card_id']],face['face'],face['locale'])
        self.assertEqual(len(d['official_observations']),36)
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        for cid,form in (('AT_005','AT_005t'),('TID_708','TID_708t')):
            faces = [v['face'] for v in d['official_observations'] if v['card_id'] == cid]
            self.assertTrue(all(raw[form]['dbf_id'] in face['childIds'] for face in faces))
        self.assertEqual(len(native.LEAVES),15); self.assertEqual(len(native.DEPENDENCIES),17)
        self.assertFalse(d['source_scope_bound']); self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_original_intellect_and_shot_reuse_existing_bodies_with_real_payment_in_both_seats(self):
        for p in (1,2):
            g = self.game(('CS2_023','DS1_185'),player=p,own=(POWER,))
            before = tuple(g.state.players[p].deck); self.play(g,'CS2_023',player=p)
            self.assertEqual(g.state.players[p].deck,list(before[2:]))
            self.assertTrue(set(before[:2]) <= set(g.state.players[p].hand))
            target = g.state.players[3-p].hero_id; self.play(g,'DS1_185',target,player=p)
            self.assertEqual(g.state.entities[target].health,27); self.assertEqual(g.state.players[p].mana,56)
        self.portable(g)

    def test_explosion_uses_one_simultaneous_boundary_and_does_not_hit_new_deathrattle_bodies(self):
        g = self.game(('CS2_025',),own=(POWER,UNIT),enemy=(FRAGILE,FRAGILE))
        old = set(g.state.players[2].board); self.play(g,'CS2_025')
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in old))
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[6,6])
        rows = self.damage_rows(g,'CS2_025'); self.assertEqual(len(rows),2)
        self.assertEqual(len({v.batch_id for v in rows}),1)
        self.assertEqual(self.entity(g,UNIT,zone='board').health,6); self.portable(g)

    def test_greater_missiles_are_three_individual_three_plus_bonus_hits_not_split_points(self):
        g = self.game(('CFM_623',),own=(POWER,)); target = g.state.players[2].hero_id
        self.play(g,'CFM_623'); rows = self.damage_rows(g,'CFM_623')
        self.assertEqual([v.modified_amount for v in rows],[4,4,4])
        self.assertEqual(g.state.entities[target].health,18); self.assertEqual(g.state.players[1].mana,53)
        self.assertEqual(len(g.state.cast_history),1); self.portable(g)

    def test_missile_death_wait_restores_then_requeries_surviving_targets(self):
        g = self.game(('CFM_623',),enemy=(FRAGILE,),seed=0,mode='missile-wait')
        self.play(g,'CFM_623'); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.damage_rows(g,'CFM_623')),1)
        before = g.snapshot(); restored = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored): self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)
        self.assertEqual(len(self.damage_rows(g,'CFM_623')),3); self.portable(g)

    def test_moonbeam_adds_spell_damage_to_each_enemy_hit_and_rejects_friendly_targets(self):
        g = self.game(('TID_001',),own=(POWER,UNIT)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'TID_001',self.entity(g,UNIT,zone='board').id)
        self.assertEqual(g.snapshot(),before)
        target = g.state.players[2].hero_id; self.play(g,'TID_001',target)
        self.assertEqual([v.modified_amount for v in self.damage_rows(g,'TID_001')],[2,2])
        self.assertEqual(g.state.entities[target].health,26)

    def test_moonbeam_first_lethal_hit_does_not_redirect_second_hit_to_hero_or_new_body(self):
        g = self.game(('TID_001',),enemy=(FRAGILE,)); target = self.entity(g,FRAGILE,2,'board').id
        self.play(g,'TID_001',target)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(self.entity(g,UNIT,2,'board').health,6)
        self.assertEqual(sum(v.health_lost for v in self.damage_rows(g,'TID_001')),1)

    def test_all_three_named_transforms_replace_old_native_material_without_death(self):
        for cid,face in native.TRANSFORMS.items():
            with self.subTest(card=cid):
                g = self.game((cid,),enemy=(FRAGILE,)); eid = self.entity(g,FRAGILE,2,'board').id
                self.play(g,cid,eid); e = g.state.entities[eid]; definition = g.registry.card(face)
                self.assertEqual((e.card_id,e.attack,e.max_health),(face,definition.attack,definition.health))
                self.assertEqual(g.state.players[2].board,[eid]); self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_named_boar_charges_and_jellyfish_grants_live_two_spell_damage(self):
        g = self.game((UNIT,'AT_005')); eid = self.play(g,UNIT); self.play(g,'AT_005',eid)
        g.apply(Attack(1,eid,g.state.players[2].hero_id)); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
        g = self.game(('TID_708','DS1_185'),own=(UNIT,)); eid = self.entity(g,UNIT,zone='board').id
        self.play(g,'TID_708',eid); self.play(g,'DS1_185',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
        self.portable(g)

    def test_draw_full_hand_and_empty_deck_use_ordinary_burn_and_fatigue(self):
        g = self.game(('CS2_023',)+(UNIT,)*9,deck=(UNIT,UNIT)); self.play(g,'CS2_023')
        self.assertEqual(len(g.state.players[1].hand),10); self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(len(g.state.draw_history),2)
        g = self.game(('CS2_023',),deck=()); self.play(g,'CS2_023')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_five_generation_sources_use_full_standard_candidates_counts_costs_and_rng(self):
        for cid,query,count,discount in (('BOT_101',native.MINIONS,2,0),('GVG_003',native.MINIONS,1,3),
                ('EX1_180',native.MAGE_SPELLS,1,0),('OG_090',native.MAGE_SPELLS,3,0),('WON_037',native.MAGE_SPELLS,3,0)):
            with self.subTest(card=cid):
                g = self.game((cid,)); rows = ordinary_candidates(g,cid,query); probe = Random(); probe.setstate(g._rng.getstate())
                expected = sample_candidates(probe,rows,count,replacement=True)
                self.play(g,cid)
                actual = [g.state.entities[i] for i in g.state.players[1].hand]
                self.assertEqual([v.card_id for v in actual],list(expected)); self.assertEqual(g._rng.getstate(),probe.getstate())
                self.assertEqual([quote_unselected_cost(g.state,g.registry,v).amount for v in actual],
                    [max(0,g.registry.card(v).cost-discount) for v in expected])
                self.assertEqual(g.state.players[1].mana,60-g.registry.card(cid).cost)
        self.portable(g)

    def test_full_portal_can_generate_and_play_real_zero_cost_minion(self):
        desired='BE_255'; seed=seed_for('GVG_003',native.MINIONS,desired)
        g = self.game(('GVG_003',),seed=seed); self.play(g,'GVG_003')
        e = self.entity(g,desired); self.assertEqual(quote_unselected_cost(g.state,g.registry,e).amount,0)
        self.play(g,desired); self.assertEqual(g.state.play_history[-1].cost,0)

    def test_fixed_mage_generation_on_other_hero_can_cast_real_generated_draw_spell(self):
        desired='CORE_CS2_023'; seed=seed_for('EX1_180',native.MAGE_SPELLS,desired)
        g = self.game(('EX1_180',),seed=seed,player=2,hero='HERO_03')
        self.play(g,'EX1_180',player=2); self.play(g,desired,player=2)
        self.assertEqual(len(g.state.players[2].deck),10); self.assertEqual(g.state.players[2].mana,56)
        self.portable(g)

    def test_both_discovery_sources_use_full_actual_queries_and_glyph_discount(self):
        for cid,query,discount in (('DAL_608',native.SMALL_SPELLS,0),('UNG_941',native.SPELLS,2)):
            with self.subTest(card=cid):
                g = self.game((cid,)); rows = ordinary_candidates(g,cid,query); probe = Random(); probe.setstate(g._rng.getstate())
                expected = sample_candidates(probe,rows,3,replacement=False); self.play(g,cid)
                self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),expected)
                self.assertEqual(g._rng.getstate(),probe.getstate())
                self.choose(g,g.state.pending_choice.options[0].id); e = self.entity(g,expected[0])
                self.assertEqual(quote_unselected_cost(g.state,g.registry,e).amount,max(0,g.registry.card(e.card_id).cost-discount))
        self.portable(g)

    def test_discovery_and_discounted_delivery_waits_restore_without_reselection(self):
        g = self.game(('UNG_941',),mode='delivery-wait'); self.play(g,'UNG_941'); restored = self.portable(g)
        option = g.state.pending_choice.options[0]; before = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g,'invalid-discover-option')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored): self.choose(current,option.id)
        self.assertEqual(g.snapshot(),restored.snapshot()); waiting = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for current in (g,waiting): self.choose(current)
        self.assertEqual(g.snapshot(),waiting.snapshot()); self.assertEqual(len(g.state.players[1].hand),1)

    def test_late_second_generated_card_failure_rolls_back_whole_cast_payment_and_rng(self):
        g = self.game(('BOT_101',),mode='generation-fail'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate continuation failure'): self.play(g,'BOT_101')
        self.assertEqual(g.snapshot(),saved)

    def test_complete84_still_errors_on_missing_native_and_real_production_scope_stays_closed(self):
        g = self.game(('TIME_857',)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'): self.play(g,'TIME_857')
        self.assertEqual(g.snapshot(),saved)
        g = self.game(('TIME_857',),mode='full-reference'); saved = g.snapshot()
        self.assertEqual(len(g.registry.pool('constructed.past.cards',FULL).members),84)
        with self.assertRaisesRegex(ResolutionError,'AT_004'): self.play(g,'TIME_857')
        self.assertEqual(g.snapshot(),saved)

    def test_late_existing_body_pin_failure_adds_no_partial_native_cards_or_behaviors(self):
        r = build_registry()
        for cid in native.DEPENDENCIES:r._cards.pop(cid);r._pool_cards.pop(cid)
        old='CORE_DS1_185';r._cards[old]=replace(r.card(old),cost=2)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with self.assertRaises(TargetValidationError):native.register_past_arcane_simple_spells(r)
        self.assertEqual((dict(r.cards),dict(r.pool_cards),dict(r._behaviors)),before)

    def test_generated_cards_and_internal_reference_material_stay_private(self):
        seed=seed_for('EX1_180',native.MAGE_SPELLS,'CORE_CS2_023')
        g=self.game(('EX1_180',),player=2,seed=seed);self.play(g,'EX1_180',player=2)
        self.assertIn('CORE_CS2_023',json.dumps(g.observe(2)))
        self.assertNotIn('CORE_CS2_023',json.dumps(g.observe(1)))
        for player in (1,2):
            text=json.dumps(g.observe(player))
            for field in ('reference_canonical_sha256','official_observations','rng_state','resolution_frame'):
                self.assertNotIn('"'+field+'"',text)


if __name__ == '__main__':unittest.main()
