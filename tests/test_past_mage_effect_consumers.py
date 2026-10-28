"""Real historical Mage entries reuse the complete shared effect pipelines."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json, tempfile, unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch
from hs_sim.cards import build_registry
from hs_sim.cards import past_mage_effect_consumers as native
from hs_sim.engine import Attack, EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario, UseHandAction
from hs_sim.engine.deck_reveals import EVENT as REVEAL_EVENT, deck_reveal_result
from hs_sim.engine.effects import ChoiceOption, Freeze, InvokeBehavior, ModifyCost, RequestChoice, Silence
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType, TargetSpec, Zone
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool, PoolQuery, resolve_candidates
from hs_sim.engine.card_creation import CardSpellRepeatGrant
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.engine.model import CostSpec
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k621.'
NOOP, POWER, PREP, DECK_COST, SILENCE, FAIL = (P+s for s in ('noop','power','prep','deck_cost','silence','fail'))
COPY_WAIT, COPY_FAIL, REVEAL_WAIT, REVEAL_FAIL = (P+s for s in ('copy_wait','copy_fail','reveal_wait','reveal_fail'))


@lru_cache(None)
def format_for(role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=30, spell_damage=2))
    def prep(c):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='CS2_033')
        return (ModifyCost(entity.id, CostSpec(delta=-4), c.source_id),
            BuffStoredCard(CardReference.capture(entity), 2, 3, c.source_id))
    def deck_cost(c):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.SPELL)
        return (ModifyStoredCost(CardReference.capture(entity), CostSpec(set_to=2), c.source_id),)
    r.register_behavior(PREP, prep); r.register_behavior(DECK_COST, deck_cost)
    r.register_behavior(SILENCE, lambda c: (Silence(c.target_id),))
    for cid in (PREP, DECK_COST, SILENCE):
        fields = dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))) if cid==SILENCE else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, **fields))
    def fail(c): raise ResolutionError('K621 deliberate native reaction failure')
    r.register_behavior(FAIL, fail)
    for cid, event, failure in ((COPY_WAIT,'minion_summoned',False),(COPY_FAIL,'minion_summoned',True),
            (REVEAL_WAIT,REVEAL_EVENT,False),(REVEAL_FAIL,REVEAL_EVENT,True)):
        def watch(c, event=event, failure=failure):
            if failure: return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
            options = [ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))]
            if event==REVEAL_EVENT:
                result = deck_reveal_result(c.event)
                if result.card is not None:
                    options.append(ChoiceOption('change','Change the later stored price',
                        (ModifyStoredCost(result.card.card,CostSpec(set_to=9),c.source_id),)))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_behavior(cid, watch)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=50,
            limited_triggers=(LimitedTriggerSpec(event,cid),)))
    r.validate(); return f


def registry(mode='normal', role='writer'):
    if mode!='normal': raise ValueError('Unknown past Mage consumer fixture')
    return format_for(role).registry


class PastMageEffectConsumerTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, hand, *, board=(), deck=('CORE_EX1_162',)*8, enemy=(), enemy_hand=(), weapon=None, seed=621):
        f = format_for()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            weapon_card_id=weapon,mana=10,max_mana=10),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,
                deck=('CORE_EX1_162',)*8,mana=10,max_mana=10)),seed=seed,generation_context=f.context),f.registry)

    def choose_card(self,g,cid): self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))

    def test_full_eighteen_rows_twenty_four_faces_and_twelve_original_leaf_roles(self):
        d = native.load_batch()
        self.assertEqual(len(d['dependencies']),12); self.assertEqual(len(d['existing_dependencies']),6)
        self.assertEqual(len(d['official_observations']),24); self.assertTrue(d['gift_domain_bound'])
        self.assertFalse(d['full_past_mage_source_bound']); self.assertFalse(d['formal_pool_complete'])
        self.assertFalse(d['new_standard_roots'])

    def test_core_aliases_keep_every_original_native_field_and_canonical_secret_key(self):
        r = format_for().registry
        for cid, original in native.ALIASES.items():
            actual, old = asdict(r.card(cid)), asdict(r.card(original))
            for key in ('id','name','metadata'): actual.pop(key); old.pop(key)
            self.assertEqual(actual,old); self.assertEqual(r.card(cid).secret.key,cid)

    def test_original_oasis_ally_summons_real_water_elemental_that_later_freezes_on_damage(self):
        g = self.game(('BAR_812',),board=('CORE_EX1_162',),enemy=('CORE_CS2_189',))
        self.play(g,'BAR_812'); g.apply(EndTurn(1)); attacker=self.entity(g,'CORE_CS2_189',2,'board').id
        g.apply(Attack(2,attacker,self.entity(g,'CORE_EX1_162',1,'board').id))
        water=self.entity(g,'CS2_033',1,'board'); self.assertEqual(water.max_health,6)
        g.apply(EndTurn(2)); g.apply(Attack(1,water.id,g.state.players[2].hero_id))
        self.assertTrue(g.state.entities[g.state.players[2].hero_id].frozen)

    def test_original_explosive_runes_keeps_native_six_damage_and_real_excess_to_enemy_hero(self):
        g=self.game(('LOOT_101',),enemy_hand=('CORE_EX1_162',)); self.play(g,'LOOT_101');g.apply(EndTurn(1))
        target=self.play(g,'CORE_EX1_162',player=2)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.portable(g)

    def test_gift_has_all_three_named_spells_each_temporary_copy_really_pays_and_runs_original_body(self):
        for cid in native.GIFT_IDS:
            g=self.game(('GIFT_02',));self.play(g,'GIFT_02')
            self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(native.GIFT_IDS))
            self.choose_card(g,cid);e=self.entity(g,cid);self.assertIsNotNone(e.hand_lifetime)
            self.assertEqual(e.base_cost,g.registry.card(cid).cost);before=g.state.players[1].mana
            self.play(g,cid,None if cid=='CS2_023'else g.state.players[2].hero_id)
            self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
            if cid=='CS2_023':self.assertEqual(len(g.state.players[1].hand),2)
            else:self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27 if cid=='CS2_024' else 24)

    def test_gift_original_menu_and_temporary_lifetime_restore_then_expire_at_current_turn_end(self):
        g=self.game(('GIFT_02',));self.play(g,'GIFT_02');g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'unknown-offer')
        self.assertEqual(g.snapshot(),saved);self.choose_card(g,'CS2_029');eid=self.entity(g,'CS2_029').id
        g=self.portable(g);g.apply(EndTurn(1));self.assertNotIn(eid,g.state.players[1].hand)
        self.assertNotEqual(g.state.entities[eid].zone,Zone.HAND)

    def test_second_seat_gift_still_offers_every_named_spell_after_one_mana_payment_leaves_none(self):
        f=format_for()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08'),PlayerSetup('HERO_03',hand=('GIFT_02',),
            mana=1,max_mana=1)),active_player=2,seed=621,generation_context=f.context),f.registry)
        self.play(g,'GIFT_02',player=2);self.assertEqual(g.state.players[2].mana,0)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(native.GIFT_IDS))
        self.choose_card(g,'CS2_029');card=self.entity(g,'CS2_029',2);self.assertEqual(card.cost,4)
        self.assertIsNotNone(card.hand_lifetime);g=self.portable(g);g.apply(EndTurn(2))
        self.assertNotIn(card.id,g.state.players[2].hand)

    def test_temporary_spell_discovery_is_plain_and_does_not_admit_other_kinds_or_repeat_grants(self):
        fields=dict(player_id=1,pool_id=native.GIFT_POOL,query=PoolQuery(kinds=(CardType.SPELL,),collectible=True),
            source_id=1,temporary_until_turn=1)
        self.assertEqual(DiscoverFromPool(**fields).temporary_until_turn,1)
        for changes in ({'query':PoolQuery(kinds=(CardType.HERO,),collectible=True)},
                {'query':PoolQuery(kinds=(CardType.MINION,CardType.SPELL),collectible=True)},
                {'spell_repeat':CardSpellRepeatGrant()},{'source_id':None},{'cost':CostSpec(delta=-1)},
                {'delivery':'after_all'},{'discoveries':2}):
            with self.assertRaises(ValueError):DiscoverFromPool(**(fields|changes))

    def test_simulacrum_uses_current_lowest_price_and_copies_current_buffs_into_distinct_entity(self):
        g=self.game(('ICC_823',PREP,'CS2_033','CORE_CS2_189'));self.play(g,PREP)
        original=self.entity(g,'CS2_033');self.assertEqual((original.cost,original.attack,original.max_health),(0,5,9))
        rng=g._rng.getstate();self.play(g,'ICC_823');copies=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id=='CS2_033']
        self.assertEqual(len(copies),2);self.assertNotEqual(copies[0].id,copies[1].id)
        self.assertTrue(all((e.cost,e.attack,e.max_health)==(0,5,9)for e in copies));self.assertEqual(g._rng.getstate(),rng)

    def test_simulacrum_ties_use_each_physical_slot_once_and_empty_hand_minion_pool_does_not_sample(self):
        g=self.game(('ICC_823','CORE_CS2_189','CORE_CS2_189'));candidates=[i for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION]
        rng=Random();rng.setstate(g._rng.getstate());expected=g.state.entities[rng.choice(candidates)].card_id
        self.play(g,'ICC_823');self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,expected)
        self.assertEqual(g._rng.getstate(),rng.getstate())
        g=self.game(('ICC_823',NOOP));rng=g._rng.getstate();self.play(g,'ICC_823')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[NOOP]);self.assertEqual(g._rng.getstate(),rng)

    def test_buy_one_get_one_freeze_has_frozen_original_and_frozen_current_copy_at_first_entry_wait(self):
        g=self.game(('MIS_302',),enemy=('CS2_033',),weapon=COPY_WAIT);target=self.entity(g,'CS2_033',2,'board')
        self.play(g,'MIS_302',target.id);self.assertIsNotNone(g.state.pending_choice)
        copied=self.entity(g,'CS2_033',1,'board');self.assertTrue(g.state.entities[target.id].frozen);self.assertTrue(copied.frozen)
        self.assertNotEqual(copied.id,target.id);self.assertEqual(g.state.players[1].mana,7)
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K621'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g)

    def test_copy_entry_failure_rolls_back_original_freeze_payment_copy_and_random(self):
        g=self.game(('MIS_302',),enemy=('CS2_033',),weapon=COPY_FAIL);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K621'):self.play(g,'MIS_302',self.entity(g,'CS2_033',2,'board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_dragons_fury_uses_original_revealed_deck_price_and_spell_power_after_reveal_wait(self):
        g=self.game((DECK_COST,'LOOT_172'),deck=('CORE_EX1_162','CS2_029'),board=('CS2_033',POWER),
            enemy=('CS2_033',),weapon=REVEAL_WAIT);self.play(g,DECK_COST);order=tuple(g.state.players[1].deck)
        self.play(g,'LOOT_172');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.entity(g,'CS2_033',1,'board').health,6);g=self.portable(g)
        self.choose(g,'change');self.assertEqual(tuple(g.state.players[1].deck),order)
        self.assertEqual(g.state.entities[order[1]].cost,9)
        # Original stored 2 plus the actual source's Spell Damage 2.
        self.assertEqual(self.entity(g,'CS2_033',1,'board').health,2)
        self.assertEqual(self.entity(g,'CS2_033',2,'board').health,2);self.assertFalse(g.state.draw_history)
        self.assertIn('CS2_029',json.dumps(g.player_events(2)));self.portable(g)

    def test_dragons_fury_empty_spell_deck_neither_damages_from_spell_power_nor_samples(self):
        g=self.game(('LOOT_172',),board=(POWER,),enemy=('CS2_033',));rng=g._rng.getstate();self.play(g,'LOOT_172')
        self.assertEqual(self.entity(g,'CS2_033',2,'board').health,6);self.assertEqual(g._rng.getstate(),rng)

    def test_reveal_reaction_failure_rolls_back_knowledge_price_payment_and_random(self):
        g=self.game(('LOOT_172',),deck=('CS2_029',),weapon=REVEAL_FAIL);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K621'):self.play(g,'LOOT_172')
        self.assertEqual(g.snapshot(),saved)

    def test_drakefire_real_trade_costs_one_and_draws_without_casting_or_discovering(self):
        g=self.game(('ONY_029',));source=self.entity(g,'ONY_029').id
        g.apply(UseHandAction(1,source,'trade'));self.assertEqual(g.state.players[1].mana,9)
        self.assertIsNone(g.state.pending_choice);self.assertIn(source,g.state.players[1].deck)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,'CORE_EX1_162')
        self.assertFalse(any(e.kind=='card_played'and e.source_id==source for e in g.events))

    def test_drakefire_pays_ten_and_accepts_two_full_dragon_menus_before_shared_summon_delivery(self):
        g=self.game(('ONY_029',));self.play(g,'ONY_029');selected=[]
        for _ in range(2):
            choice=g.state.pending_choice;self.assertIsNotNone(choice);self.assertFalse(g.state.players[1].board)
            for o in choice.options:self.assertIn('dragon',g.registry.card(o.card_id).metadata.tribes)
            cid=next(o.card_id for o in choice.options if not g.registry.card(o.card_id).colossal)
            selected.append(cid);self.choose_card(g,cid)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],selected)
        self.assertEqual(g.state.players[1].mana,0)

    def test_solid_alibi_caps_independent_damage_instances_until_original_owner_next_turn_starts(self):
        g=self.game(('REV_504','CS2_029','CS2_029'),enemy_hand=('CS2_029',));hero=g.state.players[1].hero_id
        self.play(g,'REV_504');self.play(g,'CS2_029',hero);self.assertEqual(g.state.entities[hero].health,29)
        g=self.portable(g);g.apply(EndTurn(1));self.play(g,'CS2_029',hero,player=2)
        self.assertEqual(g.state.entities[hero].health,28);g.apply(EndTurn(2));self.play(g,'CS2_029',hero)
        self.assertEqual(g.state.entities[hero].health,22)

    def test_spot_the_difference_uses_actual_deck_condition_and_repeats_at_most_once(self):
        for has_minion in (False,True):
            g=self.game(('TOY_374',),deck=('CORE_EX1_162',)if has_minion else ('CS2_029',)*3)
            self.play(g,'TOY_374');count=0
            while g.state.pending_choice is not None:
                count+=1;self.assertLessEqual(count,2)
                self.assertTrue(all(g.registry.card(o.card_id).cost==3 for o in g.state.pending_choice.options))
                self.choose(g,g.state.pending_choice.options[0].id)
            self.assertEqual(count,1 if has_minion else 2);self.assertEqual(len(g.state.players[1].board),count)
            self.assertEqual(g.state.players[1].mana,6)

    def test_volcanomancy_grants_real_deathrattle_and_its_three_damage_ignores_spell_power(self):
        g=self.game(('TSC_056','CS2_029'),board=('CS2_033',POWER),enemy=('CORE_EX1_162','CS2_033'))
        target=self.entity(g,'CORE_EX1_162',2,'board').id;self.play(g,'TSC_056',target);self.play(g,'CS2_029',target)
        self.assertEqual(self.entity(g,'CS2_033',1,'board').health,3)
        self.assertEqual(self.entity(g,'CS2_033',2,'board').health,3)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_volcanomancy_silence_removes_the_granted_body_and_repeated_grants_remain_independent(self):
        for silence in (True,False):
            g=self.game(('TSC_056','TSC_056',SILENCE,'CS2_029'),board=('CS2_033',),enemy=('CORE_EX1_162',))
            target=self.entity(g,'CORE_EX1_162',2,'board').id;self.play(g,'TSC_056',target);self.play(g,'TSC_056',target)
            if silence:self.play(g,SILENCE,target)
            self.play(g,'CS2_029',target);water=next(e for e in g.state.entities.values()if e.card_id=='CS2_033')
            self.assertEqual(water.zone,Zone.BOARD if silence else Zone.GRAVEYARD)
            if silence:self.assertEqual(water.health,6)

    def test_vaporize_destroys_original_minion_before_combat_and_prevents_hero_damage(self):
        g=self.game(('EX1_594',),enemy=('CORE_CS2_189',));self.play(g,'EX1_594');g.apply(EndTurn(1))
        attacker=self.entity(g,'CORE_CS2_189',2,'board').id;g.apply(Attack(2,attacker,g.state.players[1].hero_id))
        self.assertEqual(g.state.entities[attacker].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30);self.portable(g)

    def test_flame_ward_waits_for_completed_minion_attack_then_deals_three_to_all_enemy_minions(self):
        g=self.game(('ULD_239',),enemy=('CORE_CS2_189','CS2_033'));self.play(g,'ULD_239');g.apply(EndTurn(1))
        attacker=self.entity(g,'CORE_CS2_189',2,'board').id;g.apply(Attack(2,attacker,g.state.players[1].hero_id))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        self.assertEqual(g.state.entities[attacker].zone,Zone.GRAVEYARD)
        self.assertEqual(self.entity(g,'CS2_033',2,'board').health,3)

    def test_gift_offers_temporary_hand_material_and_unrevealed_secret_remain_private(self):
        g=self.game(('GIFT_02','EX1_594'));self.play(g,'EX1_594');self.play(g,'GIFT_02')
        other=g.for_player(2).observe();raw=json.dumps(other)+json.dumps(g.player_events(2))
        for private in ('candidate_ids','rng_state','resolution_frame',native.POLICY,native.GIFT_POOL):self.assertNotIn(private,raw)
        self.assertNotIn('EX1_594',raw)
        self.choose_card(g,'CS2_029');row=g.for_player(2).observe()['observation']['players'][0]
        self.assertTrue(all(card['card_id']is None for card in row['hand']))

    def test_last_invalid_native_face_cannot_partially_register_cards_metadata_or_behaviors(self):
        r=card_batch.registration_prefix(build_registry,
            'hs_sim.cards.past_mage_effect_consumers.register_past_mage_effect_consumers',lambda registry:None)
        before=r.fingerprint();d=deepcopy(native.load_batch());d['dependencies'][-1]['record']['type']='MINION'
        with patch.object(native,'load_batch',lambda:d),self.assertRaises(TargetValidationError):native.register_past_mage_effect_consumers(r)
        self.assertEqual(r.fingerprint(),before);self.assertTrue(set(native.LEAVES).isdisjoint(r.cards))

    def test_named_domain_preparation_is_pure_and_rehashed_crop_weight_or_full_scope_claim_is_rejected(self):
        f=format_for();before=f.registry.fingerprint();p=native.gift_pool(f.registry,f.context)
        self.assertEqual(tuple(m.card_id for m in p.members),native.GIFT_IDS);self.assertEqual(f.registry.fingerprint(),before)
        for mode in ('crop','weight','scope'):
            d=deepcopy(native.load_batch())
            if mode=='crop':d['gift_inventory']['candidate_ids'].pop()
            elif mode=='weight':d['gift_inventory']['weights'][0]=2
            else:d['full_past_mage_source_bound']=True
            with tempfile.TemporaryDirectory()as folder:
                path=Path(folder)/'changed.json';path.write_text(json.dumps(d),encoding='utf8')
                with patch.object(native,'BATCH_PATH',path),patch.object(native,'BATCH_HASH',canonical_digest(d)):
                    with self.assertRaises(TargetValidationError):native.load_batch()

    def test_original_launch_deck_roots_and_complete_past_source_restrictions_are_preserved(self):
        original=build_cn37_launch_candidate_format();f=format_for()
        self.assertEqual(f.root_card_ids,original.root_card_ids);self.assertEqual(f.policy.allowed_card_ids,original.policy.allowed_card_ids)
        self.assertTrue(set(native.LEAVES).isdisjoint(f.root_card_ids))
        self.assertFalse(native.load_batch()['full_past_mage_source_bound'])


if __name__=='__main__':unittest.main()
