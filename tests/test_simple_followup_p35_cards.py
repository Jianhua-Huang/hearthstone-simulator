"""Actual granted/discarded sources, original slots and two nested discoveries."""
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p35_cards import STAND,ACOLYTES,IDOL,SPARK,MINION,SPELL,MAGE,DRUID,ROOTS,DEPENDENCIES,CHOICE_ONLY,IDENTITIES,QUERIES,POOL_ID,PREFIX,load_batch,register_simple_followup_p35_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,CopyMinion,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.targets import canonical_digest

TEST='p35.test.';YETI='CORE_CS2_182';FOUR='CORE_CS2_179';ONE='JAIL_460';TWO='CORE_GVG_085';FIRE='CORE_CS2_029';NATURE='EX1_164';DUAL='END_025';NEUTRAL='TIME_EVENT_999';DORMANT='BT_156'
MEMBERS=(*ROOTS,YETI,FOUR,ONE,TWO,FIRE,NATURE,DUAL,NEUTRAL)
CONTEXT=GenerationContext('p35-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p35_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p35-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def discard(c):
        eid=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ACOLYTES)
        return(DiscardCard(CardReference.capture(c.state.entities[eid]),c.source_id),)
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id,to_owner=True),),'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),'base_copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),'discard':discard,'later':lambda c:(Summon(c.player_id,YETI),),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P35 deliberate continuation failure'))}
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','silence','bounce','trigger','copy','base_copy')else None))
    r.register_card(CardDefinition(TEST+'both','Existing ordinary Choose Both',CardType.MINION,health=9,choose_both=True,metadata=META))
    if mode:
        def eligible(c):return any(root.request.cause.source.card_id==ACOLYTES and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','First original batch entry reaction',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP35Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08'):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=3535,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,branch=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None,branch_id=branch));return eid
    def choose(self,g,cid=None,key=None):
        q=g.state.pending_choice;selected=key if key is not None else next(o.id for o in q.options if cid is None or o.card_id==cid);g.apply(SelectChoice(q.player_id,q.id,(selected,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def grants(self,g,eid):return[a for a in g.state.entities[eid].abilities if a.kind=='deathrattle'and a.behavior_id==PREFIX+'rattle']
    def actual(self,g,branch,source):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[branch],current_class=g.state.players[1].hero_class,source_card_id=source,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','card_summon_history','pool_summon_history','deathrattle_history','discard_history','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_ten_complete_rows_eight_faces_exact_runes_schools_case_and_choice_only_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['dependencies']+d['evidence_only']),10);self.assertEqual(len(d['official_observations']['observations']),8);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertTrue(d['required_generation_context']);self.assertEqual(IDOL,'Core_LOE_115');self.assertEqual((MAGE,DRUID),('EDR_872A','EDR_872B'))
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,0 if cid in CHOICE_ONLY else raw['cost']);self.assertEqual(c.choice_only,cid in CHOICE_ONLY);self.assertFalse(c.keywords);self.assertIsNone(c.deathrattle)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
        self.assertEqual(r.card(STAND).metadata.classes,(CardClass.DEATH_KNIGHT,));self.assertEqual(r.card(STAND).metadata.runes.unholy,2);self.assertIsNone(r.card(STAND).spell_school);self.assertEqual(r.card(ACOLYTES).spell_school,SpellSchool.SHADOW)
        for cid in(SPARK,MAGE,DRUID):self.assertEqual(r.card(cid).metadata.classes,(CardClass.MAGE,))
        self.assertIsNotNone(r.card(ACOLYTES).on_discard)
        for cid in CHOICE_ONLY:self.assertIsNone(r.card(cid).on_play);self.assertNotIn(cid,r.pool_cards)

    def test_eight_new_definitions_preserve_all_old_catalog_families_and_aliases(self):
        with patch('hs_sim.cards.simple_followup_p35_cards.register_simple_followup_p35_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,c in before.pool_cards.items():self.assertEqual(replace(c,metadata=replace(c.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else c,after.pool_card(cid))
        for cid in('LOE_115','CATA_471e'):self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default311_fingerprint_and_production_formal_pools_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_stand_grants_current_active_friends_not_dormant_enemy_hand_or_future(self):
        g=self.game((STAND,YETI,TEST+'later'),board=(YETI,DORMANT),enemy=(YETI,),pool=False,context=None);source=self.play(g,STAND);friend,dormant=g.state.players[1].board;grant,=self.grants(g,friend);self.assertEqual((grant.source_id,grant.deathrattle_grant_card_id,grant.origin),(source,STAND,'granted'));self.assertFalse(self.grants(g,dormant));self.assertFalse(self.grants(g,self.first(g,YETI).id));self.assertFalse(self.grants(g,g.state.players[2].board[0]));self.play(g,TEST+'later');self.assertFalse(self.grants(g,g.state.players[1].board[-1]));self.assertEqual(g.state.players[1].mana,45);self.portable(g)

    def test_stand_middle_natural_death_uses_original_slot_and_carrier_cause(self):
        g=self.game((STAND,TEST+'kill'),board=(YETI,FOUR,YETI),members=(YETI,));left,carrier,right=g.state.players[1].board;source=self.play(g,STAND);self.play(g,TEST+'kill',carrier);body,=self.bodies(g,carrier);self.assertEqual(g.state.players[1].board,[left,body.id,right]);self.assertEqual(body.card_id,YETI);self.assertFalse(self.grants(g,body.id));root=g.state.card_summon_history[-1];self.assertEqual(root.request.position,1);self.assertEqual((root.request.cause.source.entity_id,root.request.cause.origin,root.request.cause.cast_id),(carrier,'card_effect',None));self.assertNotEqual(carrier,source);self.assertEqual(g.state.deathrattle_history[-1].capture.ability.deathrattle_grant_card_id,STAND);self.portable(g)

    def test_stand_live_trigger_keeps_carrier_and_summons_to_its_right(self):
        g=self.game((STAND,TEST+'trigger'),board=(YETI,FOUR,YETI),members=(YETI,));left,carrier,right=g.state.players[1].board;self.play(g,STAND);self.play(g,TEST+'trigger',carrier);body,=self.bodies(g,carrier);self.assertEqual(g.state.players[1].board,[left,carrier,body.id,right]);self.assertEqual(g.state.card_summon_history[-1].request.position,2);self.assertFalse(g.state.death_history);self.portable(g)

    def test_stand_silence_and_bounce_remove_grant(self):
        for action in('silence','bounce'):
            with self.subTest(action=action):
                g=self.game((STAND,TEST+action),board=(YETI,));carrier=g.state.players[1].board[0];self.play(g,STAND);self.assertEqual(len(self.grants(g,carrier)),1);self.play(g,TEST+action,carrier);self.assertFalse(self.grants(g,carrier))

    def test_stand_current_copy_retains_distinct_grant_base_copy_does_not(self):
        g=self.game((STAND,TEST+'copy',TEST+'base_copy'),board=(YETI,),members=(YETI,));carrier=g.state.players[1].board[0];self.play(g,STAND);self.play(g,TEST+'copy',carrier);copied=g.state.players[1].board[-1];self.assertEqual(len(self.grants(g,copied)),1);self.assertNotEqual(self.grants(g,copied)[0].id,self.grants(g,carrier)[0].id);self.play(g,TEST+'base_copy',carrier);self.assertFalse(self.grants(g,g.state.players[1].board[-1]))

    def test_stand_empty_grant_is_not_persistent_and_needs_no_pool(self):
        g=self.game((STAND,TEST+'later'),pool=False,context=None);self.play(g,STAND);self.play(g,TEST+'later');self.assertFalse(self.grants(g,g.state.players[1].board[0]));self.assertFalse(g.state.deathrattle_history)

    def test_acolytes_paid_cast_presamples_two_then_summons_distinct_instances(self):
        g=self.game((ACOLYTES,),members=(ONE,TWO));rng=random.Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,self.actual(g,ACOLYTES,ACOLYTES),2,replacement=True);source=self.play(g,ACOLYTES);bodies=self.bodies(g,source);self.assertEqual([e.card_id for e in bodies],list(expected));self.assertEqual(len({e.id for e in bodies}),2);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,48);self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.discard_history);self.assertTrue(all(x.request.cause.origin=='spell_cast'and x.request.cause.cast_card_id==ACOLYTES for x in g.state.card_summon_history));self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_acolytes_native_discard_uses_card_effect_not_outer_spell_or_extra_payment(self):
        g=self.game((TEST+'discard',ACOLYTES),members=(ONE,));source=self.first(g,ACOLYTES).id;outer=self.play(g,TEST+'discard');self.assertEqual(len(self.bodies(g,source)),2);self.assertEqual(g.state.players[1].mana,50);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual([x.card_id for x in g.state.cast_history],[TEST+'discard']);record,=g.state.discard_history;self.assertEqual((record.card.entity_id,record.source.entity_id),(source,outer));self.assertTrue(all((x.request.cause.source.entity_id,x.request.cause.origin,x.request.cause.cast_id)==(source,'card_effect',None)for x in g.state.card_summon_history));self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_acolytes_full_board_still_presamples_two_but_delivers_none(self):
        g=self.game((ACOLYTES,),board=(YETI,)*7,members=(ONE,));rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g,ACOLYTES,ACOLYTES),2,replacement=True);source=self.play(g,ACOLYTES);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.pool_summon_history[-1].selected,(ONE,ONE));self.assertEqual([x.status for x in g.state.card_summon_history],['completed','completed']);self.assertEqual([d.outcome for x in g.state.card_summon_history for d in x.deliveries],['board_full','board_full'])

    def test_acolytes_one_space_delivers_first_and_retains_second_original_selection(self):
        g=self.game((ACOLYTES,),board=(YETI,)*6,members=(ONE,));source=self.play(g,ACOLYTES);self.assertEqual(len(self.bodies(g,source)),1);self.assertEqual(g.state.pool_summon_history[-1].selected,(ONE,ONE));self.assertEqual([x.status for x in g.state.card_summon_history],['completed','completed']);self.assertEqual([d.outcome for x in g.state.card_summon_history for d in x.deliveries],['delivered','board_full'])

    def test_acolytes_empty_pool_skips_without_rng_or_battlecry(self):
        g=self.game((ACOLYTES,),members=(YETI,));rng=g._rng.getstate();source=self.play(g,ACOLYTES);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.battlecry_history)

    def test_acolytes_first_entry_wait_restore_clone_replay_bad_resume_and_no_resample(self):
        for discarded in(False,True):
            with self.subTest(discarded=discarded):
                g=self.game((TEST+'discard',ACOLYTES)if discarded else(ACOLYTES,),members=(ONE,),mode='wait');source=self.first(g,ACOLYTES).id;self.play(g,TEST+'discard'if discarded else ACOLYTES);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.bodies(g,source)),1);self.assertEqual(g.state.pool_summon_history[-1].selected,(ONE,ONE));other=self.portable(g);saved=g.snapshot();rng=g._rng.getstate()
                with self.assertRaises(ResolutionError):self.choose(g,key='bad')
                self.assertEqual(g.snapshot(),saved)
                for game in(g,other):
                    while game.state.pending_choice:self.choose(game,key='ok')
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.bodies(g,source)),2);self.portable(g)

    def test_acolytes_late_entry_failure_rolls_back_cast_or_discard_and_rng(self):
        for discarded in(False,True):
            with self.subTest(discarded=discarded):
                g=self.game((TEST+'discard',ACOLYTES)if discarded else(ACOLYTES,),members=(ONE,),mode='fail');saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,TEST+'discard'if discarded else ACOLYTES)
                self.assertEqual(g.snapshot(),saved)

    def test_idol_current_hero_and_neutral_kind_filtered_pools(self):
        g=self.game(members=(YETI,NATURE,FIRE,DUAL,NEUTRAL),hero='HERO_06');self.assertEqual({m.card_id for m in self.actual(g,MINION,IDOL)},{YETI});self.assertEqual({m.card_id for m in self.actual(g,SPELL,IDOL)},{NATURE,NEUTRAL});g=self.game(members=(YETI,NATURE,FIRE,DUAL,NEUTRAL),hero='HERO_08');self.assertEqual({m.card_id for m in self.actual(g,SPELL,IDOL)},{FIRE,DUAL,NEUTRAL})

    def test_idol_each_native_branch_discovers_only_selected_kind_and_pays_once(self):
        for branch,card in((MINION,YETI),(SPELL,NATURE)):
            with self.subTest(branch=branch):
                g=self.game((IDOL,),members=(YETI,NATURE),hero='HERO_06');source=self.play(g,IDOL,branch=branch);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{card});self.choose(g);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,card);self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,49);self.assertEqual((len(g.state.cast_history),g.state.cast_history[0].branch_id),(1,branch));self.portable(g)

    def test_spark_fixed_class_queries_ignore_current_hero_include_matching_dual_not_neutral(self):
        for hero in('HERO_01','HERO_06','HERO_08'):
            with self.subTest(hero=hero):
                g=self.game(members=(FIRE,NATURE,DUAL,NEUTRAL),hero=hero);self.assertEqual({m.card_id for m in self.actual(g,MAGE,SPARK)},{FIRE,DUAL});self.assertEqual({m.card_id for m in self.actual(g,DRUID,SPARK)},{NATURE});self.assertEqual(QUERIES[MAGE].class_mode,'specified');self.assertFalse(QUERIES[MAGE].include_neutral)

    def test_spark_both_native_branches_discover_printed_class_from_warrior(self):
        for branch,card in((MAGE,FIRE),(DRUID,NATURE)):
            with self.subTest(branch=branch):
                g=self.game((SPARK,),members=(FIRE,NATURE,NEUTRAL),hero='HERO_01');source=self.play(g,SPARK,branch=branch);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{card});self.choose(g);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,card);self.assertEqual(g.state.players[1].mana,49);self.assertEqual(len(g.state.cast_history),1)

    def test_both_roots_combined_execute_two_ordered_discoveries_with_one_payment(self):
        for cid,members,cards,hero in((IDOL,(YETI,NATURE),(YETI,NATURE),'HERO_06'),(SPARK,(FIRE,NATURE),(FIRE,NATURE),'HERO_01')):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(TEST+'both',),members=members,hero=hero);source=self.play(g,cid,branch=cid+':combined');self.assertEqual({o.card_id for o in g.state.pending_choice.options},{cards[0]});self.choose(g);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],[cards[0]]);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{cards[1]});self.choose(g);self.assertIsNone(g.state.pending_choice);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],list(cards));self.assertEqual(g.state.players[1].mana,49);self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1));self.portable(g)

    def test_discovery_first_and_second_wait_private_restore_clone_and_independent_replay(self):
        g=self.game((SPARK,),board=(TEST+'both',),members=(FIRE,NATURE),hero='HERO_01');source=self.play(g,SPARK,branch=SPARK+':combined');self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});other=self.portable(g)
        for game in(g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());other=self.portable(g)
        for game in(g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.created(g,source)),2);self.portable(g)

    def test_missing_unknown_and_other_root_branches_rejected_before_payment(self):
        for cid,bad in((IDOL,None),(IDOL,MAGE),(SPARK,MINION),(SPARK,'EDR_872a'),(SPARK,SPARK+':combined')):
            with self.subTest(cid=cid,bad=bad):
                g=self.game((cid,));saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,cid,branch=bad)
                self.assertEqual(g.snapshot(),saved)

    def test_unknown_eligible_minions_reject_before_own_rng_for_death_paid_and_discard(self):
        for path,unknown in(('death','CATA_132'),('cast','DINO_412'),('discard','DINO_412')):
            with self.subTest(path=path):
                g=self.game((STAND,TEST+'kill')if path=='death'else(TEST+'discard',ACOLYTES)if path=='discard'else(ACOLYTES,),board=(YETI,)if path=='death'else(),members=(YETI,ONE,unknown));carrier=g.state.players[1].board[0]if path=='death'else None
                if path=='death':self.play(g,STAND)
                saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',carrier)if path=='death'else self.play(g,TEST+'discard'if path=='discard'else ACOLYTES)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_unknown_discovery_candidate_rejects_before_rng_and_paid_branch_rolls_back(self):
        for cid,branch,unknown,hero in((IDOL,MINION,'CORE_EDR_004_2026','HERO_08'),(IDOL,SPELL,'DINO_414','HERO_08'),(SPARK,MAGE,'DINO_414','HERO_01'),(SPARK,DRUID,'EDR_273','HERO_01')):
            with self.subTest(cid=cid,branch=branch):
                g=self.game((cid,),members=(YETI,FIRE,NATURE,unknown),hero=hero);saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,cid,branch=branch)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_combined_second_unknown_rejects_selection_without_repayment_or_first_reward_commit(self):
        g=self.game((IDOL,),board=(TEST+'both',),members=(YETI,'JAIL_319'),hero='HERO_08');source=self.play(g,IDOL,branch=IDOL+':combined');saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown second sampled'))as calls:
            with self.assertRaises(ResolutionError):self.choose(g)
            calls.assert_not_called()
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].mana,49);self.assertFalse(self.created(g,source));self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_missing_context_and_pool_roll_back_discard_and_discovery_entries(self):
        for path in('discard','discover','death'):
            for missing in('context','pool'):
                with self.subTest(path=path,missing=missing):
                    g=self.game((TEST+'discard',ACOLYTES)if path=='discard'else(IDOL,)if path=='discover'else(STAND,TEST+'kill'),board=(YETI,)if path=='death'else(),context=None if missing=='context'else CONTEXT,pool=missing!='pool');carrier=g.state.players[1].board[0]if path=='death'else None
                    if path=='death':self.play(g,STAND)
                    saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'discard')if path=='discard'else self.play(g,IDOL,branch=MINION)if path=='discover'else self.play(g,TEST+'kill',carrier)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
