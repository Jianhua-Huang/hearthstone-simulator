"""Complete Mage teacher discovery beside the unchanged Druid source view."""
from dataclasses import asdict
from functools import lru_cache
from random import Random
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_teacher_mage_source as native
from hs_sim.cards.highborne_student_cards import PUPIL
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import build_cn37_local_pool_format,load_bindings,ROOT
from hs_sim.targets import TargetValidationError,canonical_digest

CARD=native.SOURCE;WATCH='k654.watch';FAIL='k654.fail'


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ValueError('K654 deliberate waiting failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        if mode!='wait'or c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=PUPIL:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
            c.source_id,prompt='Original Mage pupil before the spell menu'),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),)))
    return f


def seed_for(card):
    rows=tuple(PoolMember(**v)for v in native.load_batch()['mage_actual'])
    return next(seed for seed in range(10000)if card in sample_candidates(Random(seed),rows,3,replacement=False))


class MageTeacherSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,*,card=CARD,hero='HERO_08',seed=1,mode='normal'):
        self.mode=mode;f=fixture(mode)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=(card,),board=(WATCH,)if mode=='wait'else(),
            deck=('CORE_CS2_182',)*6,mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*6)),
            seed=seed,generation_context=f.context),f.registry)

    def pick(self,g,cid):self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))

    def test_complete_original_rows_pins_and_ordered_44_member_prefix(self):
        d=native.load_batch();f=fixture();p=f.registry.pool(native.POOL,f.context)
        self.assertEqual([v.card_id for v in p.members[:44]],d['merged_member_ids']);self.assertEqual(len(p.members),206)
        self.assertEqual([v.card_id for v in p.members[:21]],d['original_member_ids']);self.assertTrue(all(v.weight==1 for v in p.members))
        native.validate_native(f.registry,d);self.assertFalse(p.excluded_card_ids);self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_both_exact_actual_class_views_keep_their_full_original_weights(self):
        f=fixture();d=native.load_batch()
        for hero,key in((CardClass.DRUID,'druid_actual'),(CardClass.MAGE,'mage_actual')):
            with self.subTest(hero=hero):
                rows=resolve_candidates(f.registry,f.context,native.POOL,native.QUERY,current_class=hero,source_card_id=CARD,exclude_source_by_rule=True)
                self.assertEqual([asdict(v)for v in rows],d[key])
        self.assertIn('RLK_590',d['mage_member_ids']);self.assertNotIn('WON_113',d['mage_member_ids'])

    def test_other_classes_and_unreviewed_toki_class_stay_explicitly_closed(self):
        f=fixture()
        for hero in(CardClass.WARRIOR,):
            with self.subTest(hero=hero),self.assertRaises(UnsupportedDefinitionError):
                resolve_candidates(f.registry,f.context,native.POOL,native.QUERY,current_class=hero,source_card_id=CARD,exclude_source_by_rule=True)
        g=self.game(card='TIME_861',hero='HERO_03');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'TIME_861')
        self.assertEqual(g.snapshot(),before)

    def test_real_mage_mentor_and_original_pupil_cast_full_past_pyroblast(self):
        g=self.game(seed=seed_for('EX1_279'));self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(self.entity(g,PUPIL).card_id,PUPIL)
        self.assertTrue(all(o.card_id in native.load_batch()['mage_member_ids']for o in g.state.pending_choice.options))
        self.pick(g,'EX1_279');self.portable(g);sid=self.play(g,PUPIL,g.state.players[2].hero_id)
        casts=[v for v in g.state.cast_history if v.card_id=='EX1_279'];self.assertEqual(len(casts),1)
        self.assertEqual((casts[0].caster_id,casts[0].origin),(sid,'effect'));self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage,10)
        self.assertEqual(g.state.players[1].mana,30-g.registry.card(CARD).cost-g.registry.card(PUPIL).cost);self.portable(g)

    def test_neutral_sunwell_is_taught_and_uses_real_fill_hand_effect(self):
        g=self.game(seed=seed_for('RLK_590'));self.play(g,CARD);self.pick(g,'RLK_590');self.play(g,PUPIL)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertTrue(all(g.state.entities[i].kind==CardType.SPELL for i in g.state.players[1].hand))
        self.assertTrue(any(v.card_id=='RLK_590'and v.origin=='effect'for v in g.state.cast_history));self.portable(g)

    def test_student_creation_wait_restores_original_menu_and_random_failure(self):
        g=self.game(seed=seed_for('EX1_279'),mode='wait');self.play(g,CARD);self.assertEqual(g.state.pending_choice.prompt,'Original Mage pupil before the spell menu')
        r=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(r);self.assertEqual(g.snapshot(),r.snapshot())
        self.pick(g,'EX1_279');self.pick(r,'EX1_279');self.assertEqual(g.snapshot(),r.snapshot());self.portable(g)

    def test_manifest_preserves_every_v14_predecessor_declaration(self):
        current=load_bindings();old=json.loads((ROOT/current['previous_manifest']['path']).read_text(encoding='utf8'))
        self.assertEqual(canonical_digest(old),current['previous_manifest']['canonical_sha256'])
        for key,value in old.items():
            if key not in('policy_id','accepted_on','previous_manifest'):self.assertEqual(current[key],value,key)
        self.assertEqual(current['teacher_mage_binding']['mage_member_count'],24)

    def test_missing_real_member_is_rejected_without_cropping_the_view(self):
        f=fixture()
        with patch.dict(f.registry._cards):
            f.registry._cards.pop('EX1_279')
            with self.assertRaises((UnsupportedDefinitionError,TargetValidationError)):native.validate_native(f.registry,native.load_batch())

    def test_private_learner_material_and_complete_inventory_are_not_in_opponent_dto(self):
        g=self.game(seed=seed_for('EX1_279'));self.play(g,CARD);self.pick(g,'EX1_279')
        other=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for key in('EX1_279','carved_spell_id','inventory_sha256','native_pins',native.POOL,'rng_state'):self.assertNotIn(key,other)
        self.portable(g)
