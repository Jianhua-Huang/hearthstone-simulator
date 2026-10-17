"""Real Webspinner dependency and independently accepted native Kindred summons."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p38_cards import SPIDERS,BULB,SPINNER,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,PREFIX,load_batch,register_simple_followup_p38_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

TEST='p38.test.';YETI='CORE_CS2_182';FOREIGN='FIR_952';BEAST='DINO_431';CHALLENGER='TLC_251'
MEMBERS=(*ROOTS,SPINNER,YETI,FOREIGN,BEAST);CONTEXT=GenerationContext('p38-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p38_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p38-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),'full_kill':lambda c:(AddToHand(c.player_id,YETI,c.source_id),Destroy(c.target_id,c.source_id)),'shadow':lambda c:(),'fire':lambda c:(),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P38 deliberate entry continuation failure'))}
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,spell_school=SpellSchool.SHADOW if name=='shadow'else SpellSchool.FIRE if name=='fire'else None,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','full_kill')else None))
    if mode:
        def roots(c):return tuple(root for root in c.state.card_summon_history if root.request.cause.source.card_id in ROOTS and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries))
        def watch(c):
            root=roots(c)[0]
            if root.request.cause.source.card_id==BULB and Keyword.TAUNT not in c.state.entities[c.event.target_id].keywords:raise ResolutionError('Voidbulb entry observer missed preinstalled Taunt')
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            tail=(Summon(1,YETI),)if mode=='fill'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',lambda c:bool(roots(c)))
        r.register_card(CardDefinition(TEST+'watch','Actual original entry reaction',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP38Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=3838,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def qualified(self,hand=(BULB,),**kw):
        g=self.game((TEST+'shadow',*hand),**kw);self.play(g,TEST+'shadow');g.apply(EndTurn(1));g.apply(EndTurn(2));return g
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def actual(self,g,cid):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','entry_keywords','kindred_history','KindredActivation','card_summon_history','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_five_complete_rows_six_faces_original_link_identity_and_native_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['dependencies']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),6);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
        self.assertEqual(r.card(SPIDERS).cost,3);self.assertIsNone(r.card(SPIDERS).spell_school);self.assertIsNone(r.card(SPIDERS).deathrattle);self.assertEqual(r.card(SPIDERS).metadata.classes,(CardClass.HUNTER,));self.assertEqual(r.card(SPINNER).metadata.tribes,('beast',));self.assertTrue(r.card(SPINNER).metadata.collectible);self.assertEqual((r.card(SPINNER).cost,r.card(SPINNER).attack,r.card(SPINNER).health),(1,1,1));self.assertEqual(r.card(BULB).spell_school,SpellSchool.SHADOW);self.assertEqual(r.card(BULB).metadata.classes,(CardClass.PRIEST,));self.assertEqual(d['cards'][0]['record']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],d['dependencies'][0]['record']['dbf_id'])

    def test_three_new_defs_preserve_old_with_only_real_dependency_and_core_identity(self):
        with patch('hs_sim.cards.simple_followup_p38_cards.register_simple_followup_p38_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(set(after.pool_cards)-set(before.pool_cards),{SPINNER});self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        for cid,c in before.pool_cards.items():self.assertEqual(replace(c,metadata=replace(c.metadata,deck_identity=IDENTITIES[cid]))if cid==SPIDERS else c,after.pool_card(cid))
        self.assertEqual(set(after.kindred_profiles)-set(before.kindred_profiles),{BULB})
        for cid in('AT_062','TLC_815e'):self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default311_full_fingerprint_and_no_formal_production_pool(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_spiders_three_actual_named_webspinners_share_original_cast_without_pool_or_rng(self):
        g=self.game((SPIDERS,),pool=False,context=None);rng=g._rng.getstate();source=self.play(g,SPIDERS);bodies=self.bodies(g,source);self.assertEqual(len(bodies),3);self.assertEqual(len({e.id for e in bodies}),3);self.assertTrue(all((e.card_id,e.attack,e.health)==(SPINNER,1,1)for e in bodies));self.assertTrue(all(any(a.kind=='deathrattle'and a.behavior_id==PREFIX+SPINNER for a in e.abilities)for e in bodies));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,47);self.assertEqual(len(g.state.cast_history),1);self.assertFalse(g.state.battlecry_history);self.assertTrue(all((x.request.cause.source.entity_id,x.request.cause.origin,x.request.cause.cast_card_id)==(source,'spell_cast',SPIDERS)for x in g.state.card_summon_history));self.portable(g)

    def test_spiders_fixed_capacity_two_slots_or_full_keeps_one_payment(self):
        for count,expected in((5,2),(7,0)):
            with self.subTest(board=count):
                g=self.game((SPIDERS,),board=(YETI,)*count,pool=False,context=None);rng=g._rng.getstate();source=self.play(g,SPIDERS);self.assertEqual(len(self.bodies(g,source)),expected);self.assertEqual(len(g.state.card_summon_history),3);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,47)

    def test_three_naturally_dead_named_spinners_each_get_new_anyclass_beast_not_draw_or_summon(self):
        g=self.game((SPIDERS,TEST+'kill',TEST+'kill',TEST+'kill'),members=(BEAST,YETI));source=self.play(g,SPIDERS);bodies=self.bodies(g,source);deck=list(g.state.players[1].deck)
        for body in bodies:
            self.play(g,TEST+'kill',body.id);new,=self.created(g,body.id);self.assertEqual(new.card_id,BEAST);self.assertEqual(new.zone,Zone.HAND);self.assertNotEqual(new.id,body.id)
        self.assertFalse(g.state.players[1].board);self.assertEqual(g.state.players[1].deck,deck);self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.deathrattle_history),3);self.assertEqual(len(g.state.card_summon_history),3);self.portable(g)

    def test_spinner_is_real_playable_collectible_dependency_with_native_deathrattle(self):
        g=self.game((SPINNER,TEST+'kill'),members=(BEAST,));source=self.play(g,SPINNER);self.assertEqual(g.state.players[1].mana,49);self.assertFalse(g.state.battlecry_history);self.play(g,TEST+'kill',source);new,=self.created(g,source);self.assertEqual(new.card_id,BEAST);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_spinner_source_only_pool_empty_before_rng(self):
        g=self.game((TEST+'kill',),board=(SPINNER,),members=(SPINNER,));source=self.first(g,SPINNER,'board').id;rng=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Source beast sampled'))as calls:self.play(g,TEST+'kill',source);calls.assert_not_called()
        self.assertFalse(self.created(g,source));self.assertEqual(g._rng.getstate(),rng)

    def test_spinner_full_hand_burns_get_reward_using_native_generation_delivery(self):
        g=self.game((TEST+'full_kill',)+(YETI,)*9,board=(SPINNER,),members=(BEAST,));source=self.first(g,SPINNER,'board').id;self.play(g,TEST+'full_kill',source);new,=self.created(g,source);self.assertEqual((new.card_id,new.zone),(BEAST,Zone.GRAVEYARD));self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.portable(g)

    def test_bulb_exact_printed_four_anyclass_unfiltered_taunt_and_native_profile(self):
        g=self.game();self.assertEqual({m.card_id for m in self.actual(g,BULB)},{YETI,FOREIGN});self.assertFalse(QUERIES[BULB].keywords_all);self.assertEqual(QUERIES[BULB].class_mode,'any');p=g.registry.kindred_profiles[BULB];self.assertEqual((p.wrapper,p.prepare,p.active),(PREFIX+'wrapper',PREFIX+'prepare',PREFIX+'active'));self.assertEqual(g.registry.card(BULB).on_play,p.wrapper)

    def test_bulb_kindred_false_still_one_non_taunt_summon_with_original_preentry_grant(self):
        g=self.game((BULB,),members=(FOREIGN,));source=self.play(g,BULB);body,=self.bodies(g,source);self.assertEqual(body.card_id,FOREIGN);self.assertNotIn(Keyword.TAUNT,g.registry.card(FOREIGN).keywords);self.assertIn(Keyword.TAUNT,body.keywords);self.assertTrue(any(a.keyword==Keyword.TAUNT and a.source_id==source for a in body.abilities));self.assertEqual(g.state.kindred_history[-1].plan,('prepare',));self.assertFalse(g.state.kindred_history[-1].condition.matched);self.assertFalse(g.state.battlecry_history);self.assertEqual((g.state.players[1].mana,len(g.state.cast_history)),(46,1));self.assertEqual(g.state.card_summon_history[-1].request.pool_basis.entry_keywords,(Keyword.TAUNT,));self.portable(g)

    def test_bulb_previous_own_shadow_true_two_independent_draws_one_paid_spell(self):
        g=self.qualified(members=(YETI,FOREIGN));rng=random.Random();rng.setstate(g._rng.getstate());rows=self.actual(g,BULB);expected=tuple(sample_candidates(rng,rows,1,replacement=True)[0]for _ in range(2));source=self.play(g,BULB);bodies=self.bodies(g,source);self.assertEqual(tuple(e.card_id for e in bodies),expected);self.assertEqual(len({e.id for e in bodies}),2);self.assertTrue(all(Keyword.TAUNT in e.keywords for e in bodies));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active'));self.assertTrue(g.state.kindred_history[-1].condition.matched);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(sum(x.card_id==BULB for x in g.state.cast_history),1);self.assertTrue(all((x.request.cause.origin,x.request.cause.cast_card_id)==('spell_cast',BULB)for x in g.state.card_summon_history));self.portable(g)

    def test_bulb_current_turn_shadow_is_not_previous_own_turn_condition(self):
        g=self.game((TEST+'shadow',BULB),members=(YETI,));self.play(g,TEST+'shadow');source=self.play(g,BULB);self.assertEqual(len(self.bodies(g,source)),1);self.assertFalse(g.state.kindred_history[-1].condition.matched)

    def test_real_challenger_max_two_repeats_only_extra_component_total_three_and_consumes(self):
        g=self.qualified((CHALLENGER,BULB),members=(YETI,));self.play(g,CHALLENGER);self.assertEqual(len(g.state.players[1].player_effects),1);source=self.play(g,BULB);self.assertEqual(len(self.bodies(g,source)),3);self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active','active'));self.assertEqual(g.state.kindred_history[-1].repetitions,2);self.assertFalse(g.state.players[1].player_effects);self.assertEqual(g.state.players[1].mana,43);self.assertEqual(sum(x.card_id==BULB for x in g.state.cast_history),1);self.portable(g)

    def test_bulb_first_entry_wait_has_taunt_then_new_full_board_skips_extra_rng(self):
        g=self.qualified(board=(YETI,)*4,members=(YETI,),mode='fill');source=self.play(g,BULB);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.bodies(g,source)),1);self.assertIn(Keyword.TAUNT,self.bodies(g,source)[0].keywords);rng=g._rng.getstate();other=self.portable(g)
        for game in(g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.bodies(g,source)),1);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active'));self.portable(g)

    def test_first_named_or_kindred_entry_wait_restore_clone_replay_and_bad_resume(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((SPIDERS,),mode='wait')if cid==SPIDERS else self.qualified(mode='wait');source=self.play(g,cid);self.assertEqual(len(self.bodies(g,source)),1);other=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),saved)
                for game in(g,other):
                    while game.state.pending_choice:self.choose(game)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.bodies(g,source)),3 if cid==SPIDERS else 2);self.portable(g)

    def test_late_original_entry_failure_rolls_back_payment_allocation_and_kindred_sources(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,),members=(YETI,),mode='fail');saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_bulb_full_board_or_empty_pool_has_no_rng_even_when_kindred_qualified(self):
        for board,members in(((YETI,)*7,(YETI,)),((),(BEAST,))):
            with self.subTest(full=bool(board)):
                g=self.qualified(board=board,members=members);rng=g._rng.getstate();source=self.play(g,BULB);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active'));self.portable(g)

    def test_complete_unknown_beast_or_four_cost_minion_errors_before_rng_and_rolls_back(self):
        for cid,unknown in((SPINNER,'CATA_550'),(BULB,'CATA_186')):
            with self.subTest(cid=cid):
                g=self.game((TEST+'kill',)if cid==SPINNER else(BULB,),board=(SPINNER,)if cid==SPINNER else(),members=(*MEMBERS,unknown));saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,SPINNER,'board').id)if cid==SPINNER else self.play(g,BULB)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_death_reward_and_bulb_missing_context_or_pool_fail_but_fixed_spiders_do_not(self):
        for cid in(SPINNER,BULB):
            for missing in('context','pool'):
                with self.subTest(cid=cid,missing=missing):
                    g=self.game((TEST+'kill',)if cid==SPINNER else(BULB,),board=(SPINNER,)if cid==SPINNER else(),pool=missing!='pool',context=None if missing=='context'else CONTEXT);saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,SPINNER,'board').id)if cid==SPINNER else self.play(g,BULB)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
