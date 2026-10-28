"""Real physical forms; shared progress/payment/CAST entry and recovery."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_mage_upgrade_forms as native
from hs_sim.engine import EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario, UseHandAction
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Damage, Draw,
    InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CostSpec, DamageKind,
    LimitedTriggerSpec, SpellSchool, TargetSpec, TribeChangeSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

P='k622.'
EL,OTHER,POWER,WEAK,DORMANT,LOCATION,NOOP,MAGE,FOREIGN=(P+x for x in
    ('elemental','other','power','weak','dormant','location','noop','mage_reward','foreign_reward'))
GAIN,GAIN5,LOSE,GET,SUMMON,DRAW,ADD_TRIBE,REMOVE_TRIBE,DISCOUNT=(P+x for x in
    ('gain','gain5','lose','get','summon','draw','add_tribe','remove_tribe','discount'))
PROGRESS_WAIT,FORGE_WAIT,DAMAGE_WAIT,DAMAGE_FAIL,FAIL=(P+x for x in
    ('progress_wait','forge_wait','damage_wait','damage_fail','fail'))
CONTEXT=GenerationContext('k622-native-diagnostic','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    if mode!='normal': raise ValueError('Unknown K622 fixture')
    r=opening_registry()
    native.register_past_mage_upgrade_forms(r)
    r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP,metadata=metadata(tribes=())))
    for cid,tribes,health,power,dormant in ((EL,('elemental',),30,0,0),(OTHER,(),30,0,0),
            (POWER,(),30,2,0),(WEAK,(),2,0,0),(DORMANT,(),30,0,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=health,
            spell_damage=power,dormant_turns=dormant,metadata=metadata(tribes=tribes)))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP))
    for cid,cls in ((MAGE,CardClass.MAGE),(FOREIGN,CardClass.WARRIOR)):
        r.register_behavior(cid,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
        card=CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,targeting=TargetSpec(),
            spell_school=SpellSchool.ARCANE,metadata=metadata(cls,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition(native.POOL,'k622-complete-two-reward-fixture',CONTEXT.target_id,
        CONTEXT.mode,(PoolMember(MAGE),PoolMember(FOREIGN)),complete=True))
    def stored(c,cid):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
    scripts={GAIN:lambda c:(ChangeManaCrystals(c.player_id,1),),
        GAIN5:lambda c:(ChangeManaCrystals(c.player_id,5),),
        LOSE:lambda c:(ChangeManaCrystals(c.player_id,-6),),
        GET:lambda c:(AddToHand(c.player_id,native.FLURRY[0],c.source_id),),
        SUMMON:lambda c:(Summon(c.player_id,EL),),DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        ADD_TRIBE:lambda c:(ChangeMinionTribes(CardReference.capture(stored(c,OTHER)),TribeChangeSpec('add',('elemental',)),c.source_id),),
        REMOVE_TRIBE:lambda c:(ChangeMinionTribes(CardReference.capture(stored(c,EL)),TribeChangeSpec('remove',('elemental',)),c.source_id),),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(stored(c,native.RUBY[0])),CostSpec(delta=-1),c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=())))
    def fail(c):raise ResolutionError('K622 deliberate native reaction failure')
    r.register_behavior(FAIL,fail)
    for cid,event in ((PROGRESS_WAIT,'hand_card_upgraded'),(FORGE_WAIT,'card_forged'),
            (DAMAGE_WAIT,'damage_dealt'),(DAMAGE_FAIL,'damage_dealt')):
        def eligible(c,event=event):
            source=c.state.entities.get(c.event.source_id)
            target=c.state.entities.get(c.event.target_id)
            return (source is not None and source.card_id==native.RUNE[1] if event=='damage_dealt' else
                target is not None and target.card_id in native.RUBY+native.RUNE)
        def watch(c,cid=cid):
            failure=InvokeBehavior(FAIL,c.source_id,c.player_id)
            return ((failure,) if cid==DAMAGE_FAIL else (RequestChoice(c.player_id,
                (ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(failure,))),c.source_id),))
        r.register_behavior(cid,watch);r.register_trigger_condition(cid,eligible)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    r.validate();return r


class PastMageUpgradeFormTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand,*,board=(),enemy=(),deck=(),enemy_hand=(),maximum=10,mana=None,weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,deck=deck,board=board,weapon_card_id=weapon,
                mana=maximum if mana is None else mana,max_mana=maximum),
            PlayerSetup('warrior.hero',hand=enemy_hand,deck=('card.1',)*8,board=enemy,mana=10,max_mana=10)),
            seed=622,generation_context=CONTEXT),registry())

    def value(self,g,eid):return progress_ability(g.state.entities[eid]).progress_value
    def hero(self,g,player=2):return g.state.players[player].hero_id
    def rollback_choice(self,g):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);return g

    def test_all_nine_complete_rows_and_eighteen_bilingual_primary_faces(self):
        d=native.load_batch();self.assertEqual(len(d['dependencies']),9)
        rows={v['record']['id']:v['record'] for v in d['dependencies']}
        for observation in d['official_observations']:
            cid=observation['card_id']
            batch.check_face(rows[cid],observation['face'],observation['locale'],
                d['display_normalizations'].get(cid),numeric_normalizations=d['numeric_normalizations'].get(cid))
        for cid in native.FLURRY:self.assertIsNone(rows[cid]['cost'])
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['source_scope_bound'])

    def test_spellstone_separator_review_rejects_changed_body_parent_or_unreviewed_card(self):
        d=native.load_batch();rows={v['record']['id']:v['record'] for v in d['dependencies']}
        for cid in native.RUBY[:2]:
            for o in (v for v in d['official_observations'] if v['card_id']==cid):
                for raw,face in ((dict(rows[cid],text=rows[cid]['text']+'额外效果',text_en=rows[cid]['text_en']+'Extra effect'),o['face']),
                        (rows[cid],dict(o['face'],text=o['face']['text']+'Extra effect')),
                        (rows[cid],dict(o['face'],parentId=999))):
                    with self.assertRaises(ValueError):batch.check_face(raw,face,o['locale'],{'@':''})

    def test_nine_native_faces_have_real_bodies_and_original_form_declarations(self):
        r=registry()
        for cid in native.DEPENDENCIES:
            self.assertEqual(r.card(cid).on_play,native.PREFIX+cid)
            self.assertEqual(r.pool_card(cid),PoolCard.from_definition(r.card(cid)))
        self.assertEqual(r.mana_rank_families[native.RANK.id],native.RANK)
        for a,b in zip(native.RUBY,native.RUBY[1:]):
            self.assertEqual(r.card(a).hand_progress.upgrade_card_id,b)
            self.assertEqual(r.card(a).hand_progress.goal,2)
        self.assertIsNone(r.card(native.RUBY[-1]).hand_progress)

    def test_last_face_failure_preserves_the_entire_registration_boundary(self):
        r=opening_registry();before=r.fingerprint();d=deepcopy(native.load_batch())
        d['dependencies'][-1]['record']['cost']=-1
        with patch.object(native,'load_batch',return_value=d),self.assertRaises(ValueError):
            native.register_past_mage_upgrade_forms(r)
        self.assertEqual(r.fingerprint(),before);self.assertFalse(r.mana_rank_families)

    def test_each_flurry_rank_really_freezes_distinct_active_enemies_for_zero_mana(self):
        for maximum,count in ((4,1),(5,2),(10,3)):
            g=self.game((native.FLURRY[0],),board=(OTHER,),enemy=(OTHER,OTHER,OTHER,DORMANT),maximum=maximum)
            self.play(g,native.FLURRY[count-1]);self.assertEqual(g.state.players[1].mana,maximum)
            enemies=[g.state.entities[i] for i in g.state.players[2].board]
            self.assertEqual(sum(e.frozen for e in enemies),count)
            self.assertFalse(self.entity(g,OTHER,zone='board').frozen)
            self.assertFalse(self.entity(g,DORMANT,2,'board').frozen)

    def test_rank_thresholds_upgrade_original_hand_and_deck_entities_and_never_downgrade(self):
        g=self.game((native.FLURRY[0],GAIN,GAIN5,LOSE),deck=(native.FLURRY[0],),maximum=4)
        h=self.entity(g,native.FLURRY[0]).id;d=self.entity(g,native.FLURRY[0],zone='deck').id
        self.play(g,GAIN);self.assertEqual([g.state.entities[i].card_id for i in(h,d)],[native.FLURRY[1]]*2)
        g=self.portable(g);self.play(g,GAIN5);self.play(g,LOSE)
        self.assertEqual(g.state.players[1].max_mana,4)
        self.assertEqual([g.state.entities[i].card_id for i in(h,d)],[native.FLURRY[2]]*2)

    def test_new_flurry_at_ten_is_immediately_rank_three_with_zero_available_mana(self):
        g=self.game((GET,),mana=0);self.play(g,GET)
        self.assertEqual(self.entity(g,native.FLURRY[2]).cost,0);self.play(g,native.FLURRY[2])
        self.assertEqual(g.state.players[1].mana,0)

    def test_empty_or_insufficient_freeze_pool_does_not_spend_rng(self):
        for enemy in ((),(OTHER,)):
            g=self.game((native.FLURRY[0],),enemy=enemy);before=g._rng.getstate()
            self.play(g,native.FLURRY[2]);self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(sum(g.state.entities[i].frozen for i in g.state.players[2].board),len(enemy))

    def test_four_distinct_elemental_plays_finish_two_stages_on_the_same_physical_spellstone(self):
        g=self.game((native.RUBY[0],EL,EL,EL,EL));eid=self.entity(g,native.RUBY[0]).id
        for index in range(4):
            self.play(g,EL)
            self.assertEqual(g.state.entities[eid].card_id,native.RUBY[(index+1)//2])
            if index<3:self.assertEqual(self.value(g,eid),(index+1)%2)
        self.play(g,native.RUBY[2]);hand=g.state.players[1].hand
        self.assertEqual(len(hand),3);self.assertEqual(len(set(hand)),3)
        self.assertTrue(all(g.state.entities[i].card_id==MAGE for i in hand))
        self.assertEqual(g.state.players[1].mana,4)

    def test_all_three_spellstone_forms_pay_two_and_generate_one_two_three_usable_mage_spells(self):
        for count,cid in enumerate(native.RUBY,1):
            g=self.game((cid,));self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,8);self.assertEqual(len(g.state.players[1].hand),count)
            self.assertTrue(all(g.state.entities[i].card_id==MAGE for i in g.state.players[1].hand))
            self.play(g,MAGE,self.hero(g));self.assertEqual(g.state.entities[self.hero(g)].health,29)

    def test_spellstone_rewards_use_mage_class_even_for_a_warrior_holder(self):
        g=self.game((),enemy_hand=(native.RUBY[2],));g.apply(EndTurn(1));self.play(g,native.RUBY[2],player=2)
        ids=[g.state.entities[i].card_id for i in g.state.players[2].hand]
        self.assertEqual(ids.count(MAGE),3);self.assertNotIn(FOREIGN,ids)

    def test_only_owner_elemental_hand_plays_count_not_summons_spells_or_opponent_plays(self):
        g=self.game((native.RUBY[0],SUMMON,OTHER,EL),enemy_hand=(EL,));eid=self.entity(g,native.RUBY[0]).id
        self.play(g,SUMMON);self.play(g,OTHER);self.assertEqual(self.value(g,eid),0)
        g.apply(EndTurn(1));self.play(g,EL,player=2);g.apply(EndTurn(2))
        self.assertEqual(self.value(g,eid),0);self.play(g,EL);self.assertEqual(self.value(g,eid),1)

    def test_deck_spellstone_does_not_progress_or_receive_retroactive_credit_when_drawn(self):
        g=self.game((native.RUBY[0],EL,EL,DRAW),deck=(native.RUBY[0],))
        h=self.entity(g,native.RUBY[0]).id;d=self.entity(g,native.RUBY[0],zone='deck').id
        self.play(g,EL);self.assertEqual(self.value(g,h),1);self.assertEqual(self.value(g,d),0)
        self.play(g,DRAW);self.play(g,EL)
        self.assertEqual(g.state.entities[h].card_id,native.RUBY[1]);self.assertEqual(self.value(g,d),1)

    def test_original_submitted_current_tribes_qualify_added_elemental_and_reject_removed_elemental(self):
        g=self.game((native.RUBY[0],ADD_TRIBE,OTHER,REMOVE_TRIBE,EL));eid=self.entity(g,native.RUBY[0]).id
        self.play(g,ADD_TRIBE);self.play(g,OTHER);self.assertEqual(self.value(g,eid),1)
        self.play(g,REMOVE_TRIBE);self.play(g,EL);self.assertEqual(self.value(g,eid),1)

    def test_real_spellstone_upgrade_clears_local_cost_only_on_the_completed_stage(self):
        g=self.game((native.RUBY[0],DISCOUNT,EL,EL));eid=self.entity(g,native.RUBY[0]).id
        self.play(g,DISCOUNT);self.play(g,EL);self.assertEqual(g.state.entities[eid].cost,1)
        self.play(g,EL);self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].cost),(native.RUBY[1],2))

    def test_progress_upgrade_wait_restores_replays_and_failed_choice_does_not_credit_next_stage(self):
        g=self.game((native.RUBY[0],EL,EL),weapon=PROGRESS_WAIT);eid=self.entity(g,native.RUBY[0]).id
        self.play(g,EL);self.play(g,EL);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[eid].card_id,native.RUBY[1]);g=self.rollback_choice(g)
        self.assertEqual(self.value(g,eid),0);self.assertEqual(g.state.players[1].mana,8)

    def test_forge_pays_two_without_a_play_or_cast_then_forged_rune_pays_three_once(self):
        g=self.game((native.RUNE[0],));eid=self.entity(g,native.RUNE[0]).id
        g.apply(UseHandAction(1,eid,'forge'))
        self.assertEqual(g.state.entities[eid].card_id,native.RUNE[1]);self.assertEqual(g.state.players[1].mana,8)
        self.assertFalse(g.state.play_history);self.assertFalse(g.state.cast_history)
        self.play(g,native.RUNE[1],self.hero(g));self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(g.state.entities[self.hero(g)].health,24);self.assertEqual(len(g.state.players[1].hand),2)
        self.assertEqual(len(g.state.cast_history),1)

    def test_base_rune_damage_uses_spell_power_and_generates_one_any_class_spell(self):
        g=self.game((native.RUNE[0],),board=(POWER,));self.play(g,native.RUNE[0],self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,25);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(g.state.players[1].mana,7)
        self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,(MAGE,FOREIGN))

    def test_forged_rune_has_two_separate_spell_power_damage_packets(self):
        g=self.game((native.RUNE[1],),board=(POWER,));self.play(g,native.RUNE[1],self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,20);self.assertEqual(len(g.state.players[1].hand),2)

    def test_forged_rune_target_dead_after_first_packet_still_generates_both_rewards(self):
        g=self.game((native.RUNE[1],),enemy=(WEAK,));eid=self.entity(g,WEAK,2,'board').id
        self.play(g,native.RUNE[1],eid);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),2)

    def test_forge_notification_wait_keeps_original_payment_and_form_after_recovery(self):
        g=self.game((native.RUNE[0],),weapon=FORGE_WAIT);eid=self.entity(g,native.RUNE[0]).id
        g.apply(UseHandAction(1,eid,'forge'));self.assertIsNotNone(g.state.pending_choice)
        g=self.rollback_choice(g);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.entities[eid].card_id,native.RUNE[1]);self.assertFalse(g.state.cast_history)

    def test_second_rune_packet_and_rewards_resume_after_first_damage_choice_without_repayment(self):
        g=self.game((native.RUNE[1],),weapon=DAMAGE_WAIT);self.play(g,native.RUNE[1],self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,27);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.players[1].hand);g=self.rollback_choice(g)
        self.assertEqual(g.state.entities[self.hero(g)].health,24);self.assertEqual(len(g.state.players[1].hand),2)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.cast_history),1)

    def test_failed_real_damage_reaction_rolls_back_hand_payment_rng_and_all_partial_damage(self):
        g=self.game((native.RUNE[1],),weapon=DAMAGE_FAIL);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,native.RUNE[1],self.hero(g))
        self.assertEqual(g.snapshot(),saved)

    def test_deep_breath_counts_only_other_physical_hand_spells_then_applies_one_adjacent_damage_batch(self):
        g=self.game(('ONY_006',NOOP,NOOP,OTHER),board=(POWER,),enemy=(OTHER,OTHER,OTHER))
        ids=tuple(g.state.players[2].board);self.play(g,'ONY_006',ids[1])
        self.assertEqual([g.state.entities[i].health for i in ids],[25,25,25])
        self.assertEqual(g.state.players[1].mana,5);self.assertEqual(g.state.entities[self.hero(g)].health,30)

    def test_deep_breath_does_not_bridge_physical_location_or_dormant_neighbours(self):
        for gap in (LOCATION,DORMANT):
            g=self.game(('ONY_006',),enemy=(OTHER,gap,OTHER,OTHER));ids=tuple(g.state.players[2].board)
            self.play(g,'ONY_006',ids[0]);self.assertEqual(g.state.entities[ids[0]].health,29)
            self.assertEqual([g.state.entities[i].health for i in ids[2:]],[30,30])
            if gap==LOCATION:self.assertEqual(g.state.entities[ids[1]].durability,2)
            else:self.assertEqual(g.state.entities[ids[1]].health,30)

    def test_deep_breath_allows_friendly_minion_and_rejects_hero_or_location_without_payment(self):
        g=self.game(('ONY_006',),board=(OTHER,LOCATION));saved=g.snapshot()
        for target in (self.hero(g),self.entity(g,LOCATION,zone='board').id):
            with self.assertRaises(IllegalAction):self.play(g,'ONY_006',target)
            self.assertEqual(g.snapshot(),saved)
        self.play(g,'ONY_006',self.entity(g,OTHER,zone='board').id)
        self.assertEqual(self.entity(g,OTHER,zone='board').health,29)

    def test_held_progress_and_native_forms_remain_private_and_restore_without_new_credit(self):
        g=self.game((native.RUBY[0],EL));eid=self.entity(g,native.RUBY[0]).id;self.play(g,EL)
        own=g.observe(1)['players'][0]['hand'][0];enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['hand_progress']['value'],1);self.assertNotIn('hand_progress',enemy)
        self.assertNotIn('progress_keys',own);g=self.portable(g);self.assertEqual(self.value(g,eid),1)

    def test_real_local_host_executes_each_root_with_complete_ordinary_generation_queries(self):
        f=build_cn37_local_pool_format();r=f.registry
        candidates=resolve_candidates(r,f.context,native.POOL,native.MAGE_SPELLS,current_class=CardClass.WARRIOR)
        self.assertGreater(len(candidates),3)
        self.assertTrue(all(CardClass.MAGE in r.pool_card(v.card_id).metadata.classes for v in candidates))
        for cid in native.LEAVES:
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),mana=10,max_mana=10),
                PlayerSetup('HERO_08',board=('CORE_EX1_162',)*3,mana=10,max_mana=10)),
                seed=622,generation_context=f.context),r)
            if cid==native.FLURRY[0]:
                self.play(g,native.FLURRY[2]);self.assertEqual(sum(g.state.entities[i].frozen for i in g.state.players[2].board),3)
            elif cid==native.RUBY[0]:
                self.play(g,cid);self.assertEqual(len(g.state.players[1].hand),1)
                self.assertIn(CardClass.MAGE,r.card(g.state.entities[g.state.players[1].hand[0]].card_id).metadata.classes)
            elif cid==native.RUNE[0]:
                g.apply(UseHandAction(1,self.entity(g,cid).id,'forge'));self.play(g,native.RUNE[1],self.hero(g))
                self.assertEqual(g.state.entities[self.hero(g)].health,24);self.assertEqual(len(g.state.players[1].hand),2)
            else:
                ids=tuple(g.state.players[2].board);self.play(g,cid,ids[1])
                self.assertEqual([g.state.entities[i].health for i in ids],[1,1,1])


if __name__=='__main__':unittest.main()
