"""Native start/survived-damage transforms with original presence and public pools."""
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p41_cards import VARIANT,VOYAGER,ROOTS,QUERY,POOL_ID,PREFIX,load_batch,register_simple_followup_p41_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,CostSpec,DamageKind,EndTurn,Game,HealthFlow,HealthOp,HealthRule,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.effects import Buff,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GrantKeyword,Heal,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Silence,Summon,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest

TEST='p41.test.';YETI='CORE_CS2_182';FIVE='CORE_EX1_250';FIVE_BC='CORE_REV_946';SEVEN='CORE_CS2_088';SEVEN_OTHER='CORE_UNG_813'
MISSING_POOL_COSTS={TEST+'unknown_five':5,TEST+'unknown_seven':7}
MEMBERS=(*ROOTS,YETI,FIVE,FIVE_BC,SEVEN,SEVEN_OTHER);CONTEXT=GenerationContext('p41-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p41_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid in MISSING_POOL_COSTS:
            missing=CardDefinition(cid,cid,CardType.MINION,cost=MISSING_POOL_COSTS[cid],health=1,
                metadata=replace(META,collectible=True,rarity=Rarity.COMMON,deck_identity=cid))
            r.register_pool_card(PoolCard.from_definition(missing))
        elif cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p41-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={
        'hit':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'zero':lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),
        'heal':lambda c:(Heal(c.target_id,2,c.source_id),),
        'lethal':lambda c:(Damage(c.target_id,99,c.source_id,DamageKind.SPELL),),
        'batch':lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id),Damage(c.target_id,1,c.source_id))),),
        'batch_lethal':lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id),Damage(c.target_id,4,c.source_id))),),
        'combat':lambda c:(CombatDamage(c.state.players[2].board[0],c.target_id,forced=True),),
        'buff':lambda c:(Buff(c.target_id,4,3,c.source_id),ModifyCost(c.target_id,CostSpec(delta=-9)),GrantKeyword(c.target_id,Keyword.WINDFURY,c.source_id)),
        'shield':lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        'immune':lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'silence':lambda c:(Silence(c.target_id),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P41 deliberate continuation failure')),
    }
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name!='fail'else None))
    r.register_card(CardDefinition(TEST+'invert','Convert original damage',CardType.MINION,health=12,metadata=META,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly'),)))
    if mode:
        event='transformed'if mode in('after_wait','after_fail')else'health_resolved'if mode.startswith('health')else'turn_started'
        def watch(c):
            if event=='turn_started':
                if c.event.player_id!=1:return()
                ids=[i for i in c.state.players[1].board if c.state.entities[i].card_id==VARIANT]
                if not ids:return()
                target=ids[0]
            elif event=='health_resolved':
                if c.health_result.target_card_id!=VOYAGER or c.health_result.damage_dealt<=0:return()
                target=c.health_result.target_id
            else:
                if dict(c.event.data)['old_card_id']not in ROOTS:return()
                target=c.event.target_id
            if mode=='after_fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            opts=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if event!='transformed':
                original=c.state.entities[target].card_id
                opts.extend((ChoiceOption('return','Return',(ReturnToHand(target),)),ChoiceOption('reenter','Return and reenter',(ReturnToHand(target),SummonFromZone(1,zone=Zone.HAND,selection='first',query=replace(QUERY,exclude_card_ids=(YETI,))))),ChoiceOption('same','Replace same face',(Transform(target,original),)),ChoiceOption('face','Replace face',(Transform(target,YETI),)),ChoiceOption('kill','Destroy',(Destroy(target),)),ChoiceOption('control','Change control twice',(ChangeControl(target,2),ChangeControl(target,1)))))
            return(RequestChoice(1,tuple(opts),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_card(CardDefinition(TEST+'watch','Actual outcome reaction before original trigger',CardType.MINION,health=12,metadata=META,triggers=(TriggerSpec(event,TEST+'watch'),)))
    r.validate();return r

class SimpleFollowupP41Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.config=(members,mode,pool)
        if mode:board=(TEST+'watch',*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=(TEST+'hit',),board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=4141,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p=p).id;g.apply(PlayCard(p,eid,target,position=len(g.state.players[p].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def own_start(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def changed(self,g):return[e for e in g.events if e.kind=='transformed']
    def actual(self,g,cid):return resolve_candidates(g.registry,CONTEXT,POOL_ID,replace(QUERY,min_cost=5 if cid==VARIANT else 7,max_cost=5 if cid==VARIANT else 7),source_card_id=cid,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','health_result','TransformMinionFromPool'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_full_two_rows_four_faces_native_triggers_no_invented_enraged_keyword(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['official_observations']['observations']),4);norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];card=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']));self.assertEqual(card.metadata.classes,(CardClass.NEUTRAL,));self.assertFalse(card.keywords);self.assertIsNone(card.on_play);self.assertIsNone(card.battlecry);self.assertIsNone(card.deathrattle);self.assertEqual(card.triggers,(TriggerSpec('turn_started'if cid==VARIANT else'health_resolved',PREFIX+cid),))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(d['cards'][1]['record']['tags']['ENRAGED'],1);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_only_two_new_definitions_all_old_facts_default_and_pools_preserved(self):
        with patch('hs_sim.cards.simple_followup_p41_cards.register_simple_followup_p41_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.kindred_profiles),dict(after.kindred_profiles))
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_variant_only_own_start_one_transformation_no_new_native_trigger_or_battlecry(self):
        g=self.game(board=(VARIANT,),members=(FIVE_BC,));eid=self.first(g,VARIANT,'board').id;rng=g._rng.getstate();g.apply(EndTurn(1));self.assertFalse(self.changed(g));self.assertEqual(g._rng.getstate(),rng);g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].card_id,FIVE_BC);self.assertEqual(len(self.changed(g)),1);self.assertFalse(g.state.battlecry_history);self.own_start(g);self.assertEqual(len(self.changed(g)),1);self.portable(g)

    def test_variant_printed_five_anyclass_full_board_same_slot_new_body_clears_modifiers(self):
        g=self.game((TEST+'buff',),board=(YETI,VARIANT,YETI,YETI,YETI,YETI,YETI),members=(FIVE,SEVEN,YETI));eid=self.first(g,VARIANT,'board').id;ids=g.state.players[1].board;old=g.state.entities[eid];self.play(g,TEST+'buff',eid);self.assertEqual(g.state.entities[eid].cost,0);rng=random.Random();rng.setstate(g._rng.getstate());self.assertEqual(sample_candidates(rng,self.actual(g,VARIANT),1,replacement=True),(FIVE,));before=len([e for e in g.events if e.kind=='minion_summoned']);self.own_start(g);e=g.state.entities[eid];self.assertEqual(g.state.players[1].board,ids);self.assertEqual((e.card_id,e.attack,e.health,e.cost),(FIVE,7,9,5));self.assertEqual(e.keywords,{Keyword.TAUNT});self.assertFalse(e.enchantments);self.assertEqual(e.entered_order,old.entered_order);self.assertGreater(e.zone_epoch,old.zone_epoch);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(len([e for e in g.events if e.kind=='minion_summoned']),before);self.assertFalse(g.state.death_history);self.portable(g)

    def test_variant_pending_original_reference_survives_wait_and_failed_resume(self):
        g=self.game(board=(VARIANT,),members=(FIVE,),mode='start_wait');eid=self.first(g,VARIANT,'board').id;self.own_start(g);self.assertEqual(g.state.entities[eid].card_id,VARIANT);self.assertFalse(self.changed(g));other=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[eid].card_id,FIVE);self.portable(g)

    def test_variant_old_trigger_cannot_follow_departure_reentry_same_face_control_or_death(self):
        for key in('return','reenter','same','face','kill','control'):
            with self.subTest(key=key):
                g=self.game(board=(VARIANT,),members=(FIVE,),mode='start_wait');eid=self.first(g,VARIANT,'board').id;self.own_start(g);rng=g._rng.getstate();self.choose(g,key);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(any(dict(e.data).get('card_id')==FIVE for e in self.changed(g)));self.assertNotEqual(g.state.entities[eid].card_id,FIVE);self.portable(g)

    def test_voyager_positive_spell_damage_to_self_survives_and_resets_new_body(self):
        g=self.game((TEST+'buff',TEST+'hit',TEST+'hit'),board=(YETI,VOYAGER,YETI),members=(FIVE,SEVEN));eid=self.first(g,VOYAGER,'board').id;ids=g.state.players[1].board;self.play(g,TEST+'buff',eid);self.assertEqual(g.state.entities[eid].cost,0);rng=random.Random();rng.setstate(g._rng.getstate());self.assertEqual(sample_candidates(rng,self.actual(g,VOYAGER),1,replacement=True),(SEVEN,));self.play(g,TEST+'hit',eid);e=g.state.entities[eid];self.assertEqual((e.card_id,e.attack,e.health,e.cost),(SEVEN,5,7,7));self.assertEqual(e.keywords,{Keyword.TAUNT});self.assertFalse(e.enchantments);self.assertEqual(g.state.players[1].board,ids);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertFalse(g.state.battlecry_history);self.assertFalse([e for e in g.events if e.kind=='minion_summoned']);self.play(g,TEST+'hit',eid);self.assertEqual(len(self.changed(g)),1);self.assertEqual(g.state.entities[eid].health,6);self.portable(g)

    def test_voyager_enemy_spell_and_actual_combat_damage_both_qualify(self):
        g=self.game(board=(VOYAGER,),members=(SEVEN_OTHER,));eid=self.first(g,VOYAGER,'board').id;g.apply(EndTurn(1));self.play(g,TEST+'hit',eid,p=2);self.assertEqual(g.state.entities[eid].card_id,SEVEN_OTHER);self.portable(g)
        g=self.game((TEST+'combat',),board=(VOYAGER,),enemy=(YETI,),members=(SEVEN_OTHER,));eid=self.first(g,VOYAGER,'board').id;self.play(g,TEST+'combat',eid);self.assertEqual(g.state.entities[eid].card_id,SEVEN_OTHER);self.assertTrue(any(x.health_result.damage_kind==DamageKind.COMBAT.value for x in g.state.damage_history));self.portable(g)

    def test_voyager_zero_heal_foreign_target_no_transform_or_host_required(self):
        for action,target_card in((TEST+'zero',VOYAGER),(TEST+'heal',VOYAGER),(TEST+'hit',YETI)):
            with self.subTest(action=action,target_card=target_card):
                g=self.game((action,),board=(VOYAGER,YETI),pool=False,context=None);rng=g._rng.getstate();self.play(g,action,self.first(g,target_card,'board').id);self.assertFalse(self.changed(g));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_voyager_shield_immune_and_converted_healing_are_not_real_damage(self):
        for protection in('shield','immune','invert'):
            with self.subTest(protection=protection):
                board=(VOYAGER,TEST+'invert')if protection=='invert'else(VOYAGER,);hand=(TEST+'hit',)if protection=='invert'else(TEST+protection,TEST+'hit');g=self.game(hand,board=board,pool=False,context=None);eid=self.first(g,VOYAGER,'board').id
                if protection!='invert':self.play(g,TEST+protection,eid)
                self.play(g,TEST+'hit',eid);self.assertFalse(self.changed(g));self.assertEqual(g.state.entities[eid].health,5);self.portable(g)

    def test_voyager_single_lethal_and_later_lethal_batch_do_not_transform(self):
        for action in('lethal','batch_lethal'):
            with self.subTest(action=action):
                g=self.game((TEST+action,),board=(VOYAGER,),pool=False,context=None);eid=self.first(g,VOYAGER,'board').id;rng=g._rng.getstate();self.play(g,TEST+action,eid);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(self.changed(g));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_voyager_two_positive_packets_old_second_trigger_does_not_transform_new_face(self):
        g=self.game((TEST+'batch',),board=(VOYAGER,),members=(SEVEN,SEVEN_OTHER));eid=self.first(g,VOYAGER,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());selected=sample_candidates(rng,self.actual(g,VOYAGER),1,replacement=True)[0];self.play(g,TEST+'batch',eid);self.assertEqual(g.state.entities[eid].card_id,selected);self.assertEqual(len(self.changed(g)),1);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(len(g.state.damage_history),2);self.portable(g)

    def test_voyager_pending_original_damage_wait_restore_replay_and_stale_carriers(self):
        for key in('ok','return','reenter','same','face','kill','control'):
            with self.subTest(key=key):
                g=self.game((TEST+'hit',),board=(VOYAGER,),members=(SEVEN,),mode='health_wait');eid=self.first(g,VOYAGER,'board').id;self.play(g,TEST+'hit',eid);self.assertEqual(g.state.entities[eid].health,4);other=self.portable(g);rng=g._rng.getstate()
                for x in(g,other):self.choose(x,key)
                self.assertEqual(g.snapshot(),other.snapshot())
                if key=='ok':self.assertEqual(g.state.entities[eid].card_id,SEVEN)
                else:self.assertEqual(g._rng.getstate(),rng);self.assertNotEqual(g.state.entities[eid].card_id,SEVEN)
                self.portable(g)

    def test_transformed_reaction_wait_restores_completed_rng_and_failed_selection(self):
        g=self.game((TEST+'hit',),board=(VOYAGER,),members=(SEVEN,SEVEN_OTHER),mode='after_wait');eid=self.first(g,VOYAGER,'board').id;self.play(g,TEST+'hit',eid);self.assertIn(g.state.entities[eid].card_id,(SEVEN,SEVEN_OTHER));other=self.portable(g);before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_later_transformed_reaction_failure_rolls_back_original_damage_turn_rng_and_body(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((TEST+'hit',),board=(cid,),mode='after_fail');eid=self.first(g,cid,'board').id
                if cid==VARIANT:g.apply(EndTurn(1))
                before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'deliberate'):
                    if cid==VARIANT:g.apply(EndTurn(2))
                    else:self.play(g,TEST+'hit',eid)
                self.assertEqual(g.snapshot(),before)

    def test_empty_eligible_tiers_keep_original_body_damage_and_do_not_consume_rng(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((TEST+'hit',),board=(cid,),members=(YETI,));eid=self.first(g,cid,'board').id;rng=g._rng.getstate()
                if cid==VARIANT:self.own_start(g)
                else:self.play(g,TEST+'hit',eid)
                self.assertEqual(g.state.entities[eid].card_id,cid);self.assertEqual(g.state.entities[eid].health,1 if cid==VARIANT else 4);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.changed(g));self.portable(g)

    def test_missing_host_context_and_pool_error_only_when_actual_native_trigger_runs(self):
        for cid in ROOTS:
            for pool,context in((True,None),(False,CONTEXT)):
                with self.subTest(cid=cid,pool=pool):
                    g=self.game((TEST+'hit',),board=(cid,),pool=pool,context=context);eid=self.first(g,cid,'board').id
                    if cid==VARIANT:g.apply(EndTurn(1))
                    before=g.snapshot()
                    with self.assertRaises(ResolutionError):
                        if cid==VARIANT:g.apply(EndTurn(2))
                        else:self.play(g,TEST+'hit',eid)
                    self.assertEqual(g.snapshot(),before)

    def test_complete_unknown_eligible_candidates_fail_before_rng_without_cropping(self):
        for cid,unknown,known in((VARIANT,TEST+'unknown_five',FIVE),(VOYAGER,TEST+'unknown_seven',SEVEN)):
            with self.subTest(cid=cid):
                g=self.game((TEST+'hit',),board=(cid,),members=(known,unknown));self.assertNotIn(unknown,g.registry.cards);self.assertEqual(g.registry.pool_card(unknown).cost,5 if cid==VARIANT else 7);eid=self.first(g,cid,'board').id
                if cid==VARIANT:g.apply(EndTurn(1))
                before=g.snapshot();original=random.Random.randrange;calls=[]
                def spy(r,*args,**kw):calls.append(args);return original(r,*args,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):
                        if cid==VARIANT:g.apply(EndTurn(2))
                        else:self.play(g,TEST+'hit',eid)
                self.assertFalse(calls);self.assertEqual(g.snapshot(),before)

    def test_current_controller_turn_and_damage_policy_after_actual_transfer(self):
        g=self.game((TEST+'give',),board=(VARIANT,),members=(FIVE,));eid=self.first(g,VARIANT,'board').id;self.play(g,TEST+'give',eid);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].card_id,FIVE);self.assertEqual(g.state.entities[eid].controller,2);self.portable(g)
        g=self.game((TEST+'give',),board=(VOYAGER,),members=(SEVEN,));eid=self.first(g,VOYAGER,'board').id;self.play(g,TEST+'give',eid);g.apply(EndTurn(1));self.play(g,TEST+'hit',eid,p=2);self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].controller),(SEVEN,2));self.portable(g)

    def test_silence_removes_native_callbacks_before_actual_events(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((TEST+'silence',TEST+'hit'),board=(cid,),pool=False,context=None);eid=self.first(g,cid,'board').id;self.play(g,TEST+'silence',eid)
                if cid==VARIANT:self.own_start(g)
                else:self.play(g,TEST+'hit',eid)
                self.assertFalse(self.changed(g));self.portable(g)

    def test_ordinary_hand_play_pays_once_without_immediate_transform_battlecry_or_pool(self):
        for cid,cost in((VARIANT,2),(VOYAGER,5)):
            with self.subTest(cid=cid):
                g=self.game((cid,),pool=False,context=None);eid=self.play(g,cid);self.assertEqual(g.state.entities[eid].card_id,cid);self.assertEqual(g.state.players[1].mana,50-cost);self.assertFalse(self.changed(g));self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.cast_history);self.portable(g)

if __name__=='__main__':unittest.main()
