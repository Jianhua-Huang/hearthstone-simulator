"""Complete original source inventories and the ordinary real producer entries."""
from dataclasses import asdict
from functools import lru_cache
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_mage_arcane_source_cards as native
from hs_sim.cards.simple_followup_p89_cards import register_simple_followup_p89_cards,ALTER,ARCANE_PAST_POOL
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,SpellSchool,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.costs import local_cost
from hs_sim.local_pool_format import build_cn37_local_pool_format,load_bindings,ROOT
from hs_sim.targets import canonical_digest

CARD=native.CARD;P='k653.'
A,B,FIRE,OTHER,WATCH,FAIL,AUTO,UNKNOWN=(P+x for x in('one','three','fire','other','watch','fail','auto','unknown'))
CTX=GenerationContext('k653-real-producer-fixture','experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original two-card source delivery')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();register_simple_followup_p89_cards(r);native.register_tear_reality(r)
    for cid,cost,hero,school in((A,1,CardClass.MAGE,SpellSchool.ARCANE),(B,3,CardClass.MAGE,SpellSchool.ARCANE),
            (FIRE,5,CardClass.MAGE,SpellSchool.FIRE),(OTHER,2,CardClass.WARLOCK,SpellSchool.ARCANE)):
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),))
        card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,spell_school=school,on_play=cid,metadata=metadata(hero))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(PoolMember(A,2),PoolMember(B,5),PoolMember(FIRE),PoolMember(OTHER))
    if mode in('single','wait','burn'):members=(PoolMember(B),)
    if mode=='empty':members=(PoolMember(OTHER),)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,2,metadata(CardClass.MAGE),spell_school=SpellSchool.ARCANE));members=(*members,PoolMember(UNKNOWN))
    for identity in(native.MAGE_POOL,ARCANE_PAST_POOL):
        r.register_pool(PoolDefinition(identity,'k653-explicit-fixture',CTX.target_id,CTX.mode,members,complete=True))
    def fail(c):raise ValueError('K653 deliberate failure')
    r.register_behavior(FAIL,fail)
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,ALTER if mode=='automatic_alter'else CARD,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,on_play=AUTO,metadata=metadata()))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(CARD,ALTER):return ()
        if mode=='burn'and c.event.kind=='spell_cast_started':return(AddToHand(c.player_id,'card.1',c.source_id),)
        if mode=='wait'and c.event.kind=='card_added_to_hand':return(prompt(c),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=metadata(),
        triggers=(TriggerSpec('spell_cast_started',WATCH),TriggerSpec('card_added_to_hand',WATCH))))
    return r


@lru_cache(maxsize=None)
def host(role='writer'):return build_cn37_local_pool_format()


class PastMageArcaneSourceTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,card=CARD,mode='normal',watch=False,hero='mage.hero',hand=None,context=CTX):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand or(card,),board=(WATCH,)if watch else(),deck=('card.40',)*6,mana=10,max_mana=10),
            PlayerSetup('mage.hero',deck=('card.40',)*6,mana=10,max_mana=10)),seed=653,generation_context=context),registry(mode))

    def full_game(self,card=CARD,*,mana=10):
        f=host();return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(card,),deck=('CORE_CS2_182',)*6,mana=mana,max_mana=mana),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*6)),seed=653,generation_context=f.context),f.registry)

    def host_portable(self,g):
        saved=g.snapshot();reader=host('independent-reader').registry
        restored=Game.from_snapshot(json.loads(json.dumps(saved)),reader)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        return restored

    def test_three_complete_rows_six_primary_faces_and_206_original_pins(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),6);self.assertEqual(len(d['native_pins']),206)
        self.assertEqual([len(x['member_ids'])for x in d['domains']],[179,84]);self.assertFalse(d['new_standard_roots']or d['formal_pool_complete']or d['cn_calibrated'])
        native.validate_native(host().registry,d)

    def test_full_mage_inventory_keeps_source_and_three_quests_but_normal_policy_filters_them(self):
        f=host();d=native.load_batch()['domains'][0];p=f.registry.pool(native.MAGE_POOL,f.context)
        self.assertEqual([m.card_id for m in p.members],d['member_ids']);self.assertTrue(all(m.weight==1 for m in p.members));self.assertFalse(p.excluded_card_ids)
        actual=resolve_candidates(f.registry,f.context,p.id,native.MAGE_QUERY,source_card_id=CARD,exclude_source_by_rule=True)
        self.assertEqual([m.card_id for m in actual],d['views'][0]['actual_ids']);self.assertEqual(len(actual),175)
        self.assertEqual(set(d['member_ids'])-{m.card_id for m in actual},{CARD,'SW_450','ULD_433','UNG_028'})

    def test_all_11_current_class_arcane_views_and_real_empty_views_match_full_original_inventory(self):
        f=host();d=native.load_batch()['domains'][1];p=f.registry.pool(ARCANE_PAST_POOL,f.context)
        self.assertEqual([m.card_id for m in p.members],d['member_ids']);self.assertEqual(len(p.members),84)
        for view in d['views']:
            with self.subTest(hero=view['current_class']):
                actual=resolve_candidates(f.registry,f.context,p.id,native.SOURCE_QUERIES[ALTER],current_class=CardClass(view['current_class']),source_card_id=ALTER,exclude_source_by_rule=True)
                self.assertEqual([m.card_id for m in actual],view['actual_ids']);self.assertEqual([m.weight for m in actual],view['actual_weights'])

    def test_exact_source_scopes_reject_unreviewed_sources_and_queries(self):
        f=host()
        for source,query in(('YOG_507',native.MAGE_QUERY),(CARD,native.SOURCE_QUERIES[ALTER])):
            with self.subTest(source=source),self.assertRaises((UnsupportedDefinitionError,ValueError)):
                resolve_candidates(f.registry,f.context,native.MAGE_POOL,query,source_card_id=source,current_class=CardClass.MAGE,exclude_source_by_rule=True)

    def test_manifest_preserves_complete_v12_predecessor_and_explicit_arcane_mapping(self):
        d=load_bindings();previous=json.loads((ROOT/d['previous_manifest']['path']).read_text(encoding='utf8'))
        self.assertEqual(canonical_digest(previous),d['previous_manifest']['canonical_sha256'])
        for key,value in previous.items():
            if key not in('policy_id','accepted_on','previous_manifest'):self.assertEqual(d[key],value,key)
        self.assertEqual(d['mage_arcane_spell_bindings'][1]['original_reference_pool_id'],'constructed.past.cards')
        self.assertEqual(d['mage_arcane_spell_bindings'][1]['pool_id'],ARCANE_PAST_POOL)

    def test_missing_original_native_member_rejected_instead_of_cropped(self):
        f=host()
        with patch.dict(f.registry._cards):
            f.registry._cards.pop('YOG_507')
            with self.assertRaises((UnsupportedDefinitionError,ValueError)):native.local_pools(f.registry,f.context)

    def test_real_host_tear_generates_two_original_candidates_with_minus_two_before_delivery(self):
        g=self.full_game();self.play(g,CARD);ids=g.state.players[1].hand
        self.assertEqual(len(ids),2);eligible=set(native.load_batch()['domains'][0]['views'][0]['actual_ids'])
        for eid in ids:
            e=g.state.entities[eid];self.assertIn(e.card_id,eligible);self.assertEqual(local_cost(e)[0],max(0,g.registry.card(e.card_id).cost-2))
        self.assertEqual(g.state.players[1].mana,6);self.host_portable(g)

    def test_real_host_alter_two_actual_discoveries_restore_and_keep_independent_discounted_cards(self):
        g=self.full_game(ALTER);self.play(g,ALTER)
        for index in range(2):
            self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.pending_choice.source_id,g.state.cast_history[0].source_id)
            self.assertTrue(all(g.registry.card(o.card_id).spell_school==SpellSchool.ARCANE for o in g.state.pending_choice.options))
            if index==0:self.host_portable(g)
            self.choose(g,g.state.pending_choice.options[0].id);self.assertEqual(len(g.state.players[1].hand),index+1)
        self.assertEqual(g.state.players[1].mana,6)
        for eid in g.state.players[1].hand:
            e=g.state.entities[eid];self.assertEqual(local_cost(e)[0],max(0,g.registry.card(e.card_id).cost-2))
        self.host_portable(g)

    def test_fixed_mage_random_source_when_stolen_and_duplicate_physical_deliveries(self):
        g=self.game(mode='single',hero='warrior.hero');self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand},{B})
        self.assertTrue(all(local_cost(g.state.entities[i])[0]==1 for i in g.state.players[1].hand));self.portable(g)

    def test_discounted_generated_card_is_actually_playable_with_correct_payment_and_effect(self):
        g=self.game(mode='single');self.play(g,CARD);self.play(g,B)
        self.assertEqual(g.state.players[1].mana,5);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)

    def test_first_original_delivery_wait_and_random_failure_restore_without_duplication(self):
        g=self.game(mode='wait',watch=True);self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice);r=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.choose(r);self.assertEqual(g.snapshot(),r.snapshot());self.assertIsNotNone(g.state.pending_choice)
        self.choose(g);self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)

    def test_full_hand_burns_both_accepted_results_without_replacing_candidates(self):
        for card in(CARD,ALTER):
            with self.subTest(card=card):
                g=self.game(card=card,mode='burn',watch=True,hand=(card,)+('card.1',)*9);self.play(g,card)
                while g.state.pending_choice is not None:self.choose(g,g.state.pending_choice.options[0].id)
                self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),2)
                self.assertEqual(g.state.players[1].mana,6);self.portable(g)

    def test_unknown_eligible_candidate_or_missing_context_rolls_back_payment_and_rng(self):
        for card in(CARD,ALTER):
            for mode,ctx in(('unknown',CTX),('normal',None)):
                with self.subTest(card=card,mode=mode):
                    g=self.game(card=card,mode=mode,context=ctx);before=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,card)
                    self.assertEqual(g.snapshot(),before)

    def test_true_empty_views_do_not_invent_a_selection_or_consume_rng(self):
        for card in(CARD,ALTER):
            with self.subTest(card=card):
                g=self.game(card=card,mode='empty');before=g.snapshot()['rng_state'];self.play(g,card)
                self.assertFalse(g.state.pending_choice);self.assertEqual(len(g.state.players[1].hand),0);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_automatic_roots_use_the_same_two_free_deliveries_and_random_choices(self):
        for mode in('normal','automatic_alter'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,hand=(AUTO,));self.play(g,AUTO)
                self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_two_metadata_additions_preserve_real_frozen_touch_and_manathirst_effects(self):
        f=host()
        for mana,damage in((7,5),(10,6)):
            with self.subTest(mana=mana):
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('REV_601','RLK_843'),mana=mana,max_mana=mana),PlayerSetup('HERO_08')),generation_context=f.context),f.registry)
                target=g.state.players[2].hero_id;self.play(g,'REV_601',target);self.play(g,'RLK_843',target)
                self.assertEqual(g.state.entities[target].damage,damage);self.assertEqual(g.state.players[1].mana,mana-3)

    def test_opponent_events_and_views_hide_generated_faces_and_complete_private_domains(self):
        g=self.game(mode='single');self.play(g,CARD);other=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for key in(B,native.MAGE_POOL,ARCANE_PAST_POOL,'native_pins','inventory_sha256','rng_state'):self.assertNotIn(key,other)
        self.portable(g)
