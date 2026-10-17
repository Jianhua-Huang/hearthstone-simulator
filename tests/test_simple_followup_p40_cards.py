"""Native non-Battlecry Kindred/DR and original healing before independent draws."""
from dataclasses import asdict
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p40_cards import REX,BLOOM,ROOTS,QUERIES,POOL_ID,load_batch,register_simple_followup_p40_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Summon,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import HealingKind,HealthFlow,HealthOp,HealthRule,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

TEST='p40.test.';YETI='CORE_CS2_182';PRIMER='FP1_011';TIRION='CORE_EX1_383';ATLAS='DINO_431';EIGHT='CORE_RLK_506';DORMANT='BT_156';CHALLENGER='TLC_251'
MEMBERS=(*ROOTS,YETI,PRIMER,TIRION,ATLAS,EIGHT);CONTEXT=GenerationContext('p40-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p40_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p40-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def wound(c):return(Damage(c.state.players[1].hero_id,12,c.source_id),*(Damage(i,4,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id==YETI),Damage(c.state.players[2].hero_id,5,c.source_id),*(Damage(i,2,c.source_id)for i in c.state.players[2].board if c.state.entities[i].card_id==YETI))
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),'full_kill':lambda c:(AddToHand(c.player_id,YETI,c.source_id),Destroy(c.target_id,c.source_id)),'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),'give':lambda c:(ChangeControl(c.target_id,2),),'natural':lambda c:(Summon(c.player_id,REX),),'wound':wound,'low':lambda c:(Damage(c.state.players[1].hero_id,28,c.source_id),),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P40 deliberate native continuation failure'))}
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','full_kill','trigger','give')else None))
    for name,rule in(('double',HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly',healing_kinds=(HealingKind.SPELL,))),('invert',HealthRule(HealthFlow.HEALING,HealthOp.CONVERT,source_relation='friendly',healing_kinds=(HealingKind.SPELL,)))):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,health=12,metadata=META,health_rules=(rule,)))
    if mode:
        def eligible(c):
            if mode in('heal_wait','fill_heal','fail_heal'):
                result=health_result(c.event);return result is not None and result.source_card_id==BLOOM
            if mode in('get_wait','fail_get'):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==REX
            return any(root.request.cause.source.card_id==BLOOM and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.startswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            tail=(Summon(1,YETI),)if mode=='fill_heal'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        event='health_resolved'if mode in('heal_wait','fill_heal','fail_heal')else'card_created'if mode in('get_wait','fail_get')else'minion_summoned'
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible);r.register_card(CardDefinition(TEST+'watch','Actual native outcome reaction',CardType.MINION,health=12,metadata=META,limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP40Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=4040,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def qualified(self,hand=(REX,),**kw):
        g=self.game((PRIMER,*hand),**kw);self.play(g,PRIMER);g.apply(EndTurn(1));g.apply(EndTurn(2));return g
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def actual(self,g,cid):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def heals(self,g,source):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','kindred_history','KindredActivation','behavior_id','card_summon_history'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_two_complete_rows_four_faces_native_kindred_not_battlecry_and_reviewed_heal_macro(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['official_observations']['observations']),4);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';text=raw['text_en'if en else'text']
                if cid==BLOOM:self.assertEqual(text.count('#8'),1);text=text.replace('#8','8')
                self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(text));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
        rex=r.card(REX);self.assertEqual((rex.cost,rex.attack,rex.health),(5,5,5));self.assertEqual(rex.metadata.classes,(CardClass.HUNTER,));self.assertEqual(rex.metadata.tribes,('beast',));self.assertIsNone(rex.battlecry);self.assertIsNotNone(rex.on_play);self.assertIsNotNone(rex.deathrattle);self.assertEqual(r.kindred_profiles[REX].wrapper,rex.on_play);self.assertEqual(r.card(BLOOM).spell_school,SpellSchool.NATURE);self.assertEqual(d['reviewed_display_normalizations'],{BLOOM:{'#8':'8'}})

    def test_only_two_new_defs_all_old_complete_metadata_profiles_and_current_default_preserved(self):
        with patch('hs_sim.cards.simple_followup_p40_cards.register_simple_followup_p40_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(set(after.kindred_profiles)-set(before.kindred_profiles),{REX})
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_rex_inactive_kindred_no_get_no_battlecry_and_no_pool_or_context_required(self):
        g=self.game((REX,),pool=False,context=None);source=self.play(g,REX);self.assertFalse(self.created(g,source));self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.kindred_history[-1].plan,());self.assertEqual(g.state.players[1].mana,45);self.portable(g)

    def test_rex_printed_native_deathrattle_anyclass_query_excludes_plain_and_source(self):
        g=self.game(members=(PRIMER,TIRION,EIGHT,YETI,REX));self.assertEqual({m.card_id for m in self.actual(g,REX)},{PRIMER,TIRION});self.assertTrue(QUERIES[REX].deathrattle);self.assertFalse(g.registry.pool_card(EIGHT).deathrattle);self.assertIsNone(g.registry.card(REX).battlecry)

    def test_rex_true_previous_own_beast_gets_one_new_discounted_instance_only_permanently(self):
        g=self.qualified((REX,TIRION),members=(TIRION,));old=self.first(g,TIRION).id;source=self.play(g,REX);new,=self.created(g,source);self.assertNotEqual(new.id,old);self.assertEqual(g.quote_cost(new.id).amount,6);self.assertEqual(g.quote_cost(old).amount,8);self.assertEqual(g.state.kindred_history[-1].plan,('active',));self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.players[1].mana,45);self.assertFalse(g.state.cast_history);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,6);self.portable(g)

    def test_rex_real_next_kindred_max_two_gets_independent_cards_with_zero_floor_one_payment(self):
        g=self.qualified((CHALLENGER,REX),members=(PRIMER,));self.play(g,CHALLENGER);rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g,REX),2,replacement=True);source=self.play(g,REX);cards=self.created(g,source);self.assertEqual(len({e.id for e in cards}),2);self.assertTrue(all(e.card_id==PRIMER and g.quote_cost(e.id).amount==0 for e in cards));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.kindred_history[-1].plan,('active','active'));self.assertFalse(g.state.players[1].player_effects);self.assertEqual(g.state.players[1].mana,42);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_rex_natural_summon_does_not_run_kindred_even_with_qualified_history(self):
        g=self.qualified((TEST+'natural',),pool=False,context=None);self.play(g,TEST+'natural');self.assertFalse(g.state.kindred_history);self.assertFalse(g.state.battlecry_history);self.assertIsNone(g.state.pending_choice)

    def test_rex_natural_and_live_deathrattle_get_once_without_kindred_or_next_source_consumption(self):
        for action in('kill','trigger'):
            with self.subTest(action=action):
                g=self.game((CHALLENGER,TEST+action),board=(REX,),members=(TIRION,));source=self.first(g,REX,'board').id;self.play(g,CHALLENGER);self.play(g,TEST+action,source);new,=self.created(g,source);self.assertEqual(new.card_id,TIRION);self.assertEqual(g.quote_cost(new.id).amount,6);self.assertFalse(g.state.kindred_history);self.assertEqual(len(g.state.players[1].player_effects),1);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD if action=='kill'else Zone.BOARD);self.portable(g)

    def test_rex_death_get_belongs_to_actual_current_carrier_controller(self):
        g=self.game((TEST+'give',TEST+'kill'),board=(REX,),members=(PRIMER,));source=self.first(g,REX,'board').id;self.play(g,TEST+'give',source);self.play(g,TEST+'kill',source);new,=self.created(g,source);self.assertEqual((new.controller,new.zone),(2,Zone.HAND));self.assertIn(new.id,g.state.players[2].hand);self.assertEqual(new.cost,0);self.assertFalse(g.state.kindred_history)

    def test_rex_full_hand_burn_and_source_only_empty_keep_native_get_policies(self):
        g=self.game((TEST+'full_kill',)+(YETI,)*9,board=(REX,),members=(PRIMER,));source=self.first(g,REX,'board').id;self.play(g,TEST+'full_kill',source);new,=self.created(g,source);self.assertEqual((new.card_id,new.zone),(PRIMER,Zone.GRAVEYARD));self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)
        g=self.game((TEST+'kill',),board=(REX,),members=(REX,));source=self.first(g,REX,'board').id;rng=g._rng.getstate();self.play(g,TEST+'kill',source);self.assertFalse(self.created(g,source));self.assertEqual(g._rng.getstate(),rng)

    def test_rex_first_of_two_gets_wait_restore_clone_replay_bad_resume_and_single_payment(self):
        g=self.qualified((CHALLENGER,REX),members=(PRIMER,),mode='get_wait');self.play(g,CHALLENGER);source=self.play(g,REX);self.assertEqual(len(self.created(g,source)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):
            while game.state.pending_choice:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.created(g,source)),2);self.assertEqual(g.state.players[1].mana,42);self.portable(g)

    def test_bloom_exact_printed_eight_anyclass_minions_then_two_independent_samples(self):
        g=self.game((BLOOM,),members=(TIRION,ATLAS,YETI));self.assertEqual({m.card_id for m in self.actual(g,BLOOM)},{TIRION,ATLAS});rng=random.Random();rng.setstate(g._rng.getstate());expected=tuple(sample_candidates(rng,self.actual(g,BLOOM),1,replacement=True)[0]for _ in range(2));source=self.play(g,BLOOM);bodies=self.bodies(g,source);self.assertEqual(tuple(e.card_id for e in bodies),expected);self.assertEqual(len({e.id for e in bodies}),2);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertTrue(all((r.request.cause.source.entity_id,r.request.cause.origin,r.request.cause.cast_card_id)==(source,'spell_cast',BLOOM)for r in g.state.card_summon_history));self.assertEqual((g.state.players[1].mana,len(g.state.cast_history)),(41,1));self.portable(g)

    def test_bloom_spell_heal_batch_caps_friendly_only_excludes_dormant_and_precedes_summons(self):
        g=self.game((TEST+'wound',BLOOM),board=(YETI,DORMANT),enemy=(YETI,),members=(EIGHT,));own=g.state.players[1].hero_id;friend=g.state.players[1].board[0];dormant=g.state.players[1].board[1];enemy=g.state.players[2].hero_id;enemy_body=g.state.players[2].board[0];self.play(g,TEST+'wound');source=self.play(g,BLOOM);self.assertEqual((g.state.entities[own].health,g.state.entities[friend].health),(26,5));self.assertEqual((g.state.entities[enemy].health,g.state.entities[enemy_body].health),(25,3));results=self.heals(g,source);self.assertEqual({r.target_id for r in results},{own,friend});self.assertNotIn(dormant,{r.target_id for r in results});self.assertTrue(all(r.healing_kind==HealingKind.SPELL.value for r in results));self.assertEqual(sorted(r.healed for r in results),[4,8]);self.assertEqual(len(self.bodies(g,source)),2);self.portable(g)

    def test_bloom_shared_spell_healing_multiplier_and_conversion_before_summons(self):
        g=self.game((TEST+'wound',BLOOM),board=(TEST+'double',),members=(EIGHT,));hero=g.state.players[1].hero_id;self.play(g,TEST+'wound');source=self.play(g,BLOOM);self.assertEqual(g.state.entities[hero].health,30);self.assertEqual(len(self.bodies(g,source)),2)
        g=self.game((BLOOM,),board=(TEST+'invert',),members=(EIGHT,));hero=g.state.players[1].hero_id;source=self.play(g,BLOOM);self.assertEqual(g.state.entities[hero].health,22);self.assertEqual(len(self.bodies(g,source)),2);self.portable(g)

    def test_bloom_converted_lethal_heal_ends_game_before_pool_requests(self):
        g=self.game((TEST+'low',BLOOM),board=(TEST+'invert',),pool=False,context=None);self.play(g,TEST+'low');source=self.play(g,BLOOM);self.assertEqual((g.state.status,g.state.winner),('finished',2));self.assertFalse(self.bodies(g,source));self.assertIsNone(g.state.pending_choice)

    def test_bloom_full_one_or_two_slots_and_empty_pool_recheck_each_request_rng(self):
        for count,expected in((7,0),(6,1),(5,2)):
            with self.subTest(board=count):
                g=self.game((BLOOM,),board=(YETI,)*count,members=(EIGHT,));rng=random.Random();rng.setstate(g._rng.getstate())
                for _ in range(expected):sample_candidates(rng,self.actual(g,BLOOM),1,replacement=True)
                source=self.play(g,BLOOM);self.assertEqual(len(self.bodies(g,source)),expected);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,41)
        g=self.game((TEST+'wound',BLOOM),members=(YETI,));self.play(g,TEST+'wound');rng=g._rng.getstate();source=self.play(g,BLOOM);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,26)

    def test_bloom_healing_wait_commits_original_batch_before_future_capacity_and_rng(self):
        g=self.game((TEST+'wound',BLOOM),board=(YETI,)*5,members=(EIGHT,),mode='fill_heal');self.play(g,TEST+'wound');source=self.play(g,BLOOM);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,26);self.assertFalse(self.bodies(g,source));other=self.portable(g);saved=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):
            while game.state.pending_choice:self.choose(game)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_bloom_first_summon_wait_restores_second_independent_request_without_repayment(self):
        g=self.game((BLOOM,),members=(TIRION,ATLAS),mode='sum_wait');source=self.play(g,BLOOM);self.assertEqual(len(self.bodies(g,source)),1);other=self.portable(g)
        for game in(g,other):
            while game.state.pending_choice:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.bodies(g,source)),2);self.assertEqual(g.state.players[1].mana,41);self.portable(g)

    def test_late_get_heal_or_summon_failures_roll_back_original_action(self):
        g=self.qualified(members=(PRIMER,),mode='fail_get');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,REX)
        self.assertEqual(g.snapshot(),saved)
        for mode in('fail_heal','fail_sum'):
            with self.subTest(mode=mode):
                g=self.game((TEST+'wound',BLOOM),board=(YETI,),members=(EIGHT,),mode=mode);self.play(g,TEST+'wound');saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,BLOOM)
                self.assertEqual(g.snapshot(),saved)

    def test_complete_unknown_printed_dr_or_eight_minions_fail_before_rng_and_rollback_healing(self):
        for path,unknown in(('kindred','CATA_481'),('death','CATA_481'),('bloom','CATA_140')):
            with self.subTest(path=path):
                g=self.qualified(members=(*MEMBERS,unknown))if path=='kindred'else self.game((TEST+'kill',)if path=='death'else(TEST+'wound',BLOOM),board=(REX,)if path=='death'else(),members=(*MEMBERS,unknown))
                if path=='bloom':self.play(g,TEST+'wound')
                saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,REX)if path=='kindred'else self.play(g,TEST+'kill',self.first(g,REX,'board').id)if path=='death'else self.play(g,BLOOM)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_actual_get_or_summon_requests_require_host_context_and_pool(self):
        for path in('death','bloom'):
            for missing in('context','pool'):
                with self.subTest(path=path,missing=missing):
                    g=self.game((TEST+'kill',)if path=='death'else(BLOOM,),board=(REX,)if path=='death'else(),pool=missing!='pool',context=None if missing=='context'else CONTEXT);saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,REX,'board').id)if path=='death'else self.play(g,BLOOM)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
