"""Current post-death Fel burst and ordinary physical granted Deathrattle."""
from dataclasses import asdict
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.health_cards import SCHOOLS
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p43_cards import BLAZE,BLESSING,ROOTS,EVIDENCE_ONLY,QUERY,POOL_ID,PREFIX,PAYLOAD,load_batch,register_simple_followup_p43_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellRepeatSpec,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GrantDeathrattle,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

TEST='p43.test.';YETI='CORE_CS2_182';FEL='CORE_BT_035';FIRE='CORE_CS2_029';PRIMER='FP1_011';FOUR='TID_700';STEGO='UNG_810';SHIELD='CORE_EX1_008';DORMANT='BT_156'
MEMBERS=(*ROOTS,YETI,PRIMER,FOUR,STEGO);CONTEXT=GenerationContext('p43-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p43_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p43-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def root(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BLAZE)
    def rebuild(c):return(ReturnToHand(c.state.players[2].board[0]),Summon(2,YETI))
    scripts={
        'auto':lambda c:(CastSpell(c.player_id,FEL,c.source_id),),
        'foreign':lambda c:(CastSpell(2,FEL,c.source_id),),
        'fel_kill':lambda c:(Destroy(root(c),c.source_id),),
        'fel_return':lambda c:(ReturnToHand(root(c)),),
        'fel_silence':lambda c:(Silence(root(c)),),
        'fel_lethal':lambda c:(Damage(c.state.players[2].hero_id,99,c.source_id,DamageKind.SPELL),),
        'counter':lambda c:(SetSecret(2,'EX1_287'),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base_copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'rebuild':rebuild,
        'grant_blaze':lambda c:(GrantDeathrattle(root(c),TEST+'rebuild',c.source_id),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P43 deliberate continuation failure')),
    }
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn)
        if name=='rebuild':continue
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,spell_school=SpellSchool.FEL if name.startswith('fel_')else None,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','silence','bounce','give','trigger','copy','base_copy')else None))
    r.register_card(CardDefinition(TEST+'repeat','Three successful Fel casts',CardType.MINION,health=12,metadata=META,spell_repeats=(SpellRepeatSpec(3,class_mode='any'),)))
    r.register_card(CardDefinition(TEST+'power','Spellpower does not scale minion burst',CardType.MINION,health=12,metadata=META,spell_damage=8))
    if mode:
        def eligible(c):
            if mode=='blaze_wait':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==BLAZE
            if mode=='blaze_fail':return c.health_result is not None and c.health_result.source_card_id==BLAZE
            if mode.startswith('grant'):return dict(c.event.data).get('ability_kind')=='deathrattle'and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==BLESSING
            return any(root.request.cause.source.entity_id!=c.event.target_id and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.endswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            tail=(Summon(2,YETI),)if mode=='blaze_wait'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        event='minion_died'if mode=='blaze_wait'else'health_resolved'if mode=='blaze_fail'else'ability_granted'if mode.startswith('grant')else'minion_summoned'
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible);r.register_card(CardDefinition(TEST+'watch','Original actual effect reaction',CardType.MINION,health=12,metadata=META,limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP43Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=4343,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def grants(self,g,target):return[a for a in g.state.entities[target].abilities if a.kind=='deathrattle'and a.behavior_id==PAYLOAD]
    def shots(self,g,source):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def actual(self,g,cid):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERY,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','deathrattle_history','card_summon_history'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_three_complete_rows_four_faces_shared_school5_is_holy_not_task_nature_typo(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['evidence_only']),1);self.assertEqual(tuple(x['record']['id']for x in d['evidence_only']),EVIDENCE_ONLY);self.assertEqual(len(d['official_observations']['observations']),4);norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];card=r.card(cid);self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(card.cost,raw['cost']);self.assertFalse(card.keywords);self.assertIsNone(card.battlecry);self.assertIsNone(card.deathrattle)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                if cid==BLESSING:self.assertEqual((f['classId'],f['spellSchoolId']),(5,5))
        b=r.card(BLAZE);self.assertEqual((b.cost,b.attack,b.health,b.metadata.classes,b.metadata.tribes),(2,2,3,(CardClass.DEMON_HUNTER,),('elemental',)));self.assertEqual(b.triggers,(TriggerSpec('spell_cast_finished',PREFIX+BLAZE),));self.assertIsNone(b.on_play);self.assertEqual(r.card(BLESSING).spell_school,SCHOOLS[5]);self.assertEqual(SCHOOLS[5],SpellSchool.HOLY);self.assertEqual(r.card(BLESSING).metadata.classes,(CardClass.PALADIN,));self.assertEqual(r.card(BLESSING).targeting.relation,'friendly');self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        for cid in EVIDENCE_ONLY:self.assertNotIn(cid,r.cards);self.assertNotIn(cid,r.pool_cards)

    def test_two_new_defs_and_all_old_facts_default_preserved_with_own_registration_suppressed(self):
        with patch('hs_sim.cards.simple_followup_p43_cards.register_simple_followup_p43_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.kindred_profiles),dict(after.kindred_profiles))
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_blaze_real_paid_fel_destroys_original_before_one_batch_two_to_actual_enemies(self):
        g=self.game((FEL,),board=(BLAZE,YETI,TEST+'power'),enemy=(YETI,SHIELD,DORMANT),pool=False,context=None);source=self.first(g,BLAZE,'board').id;enemy=self.first(g,YETI,'board',2).id;shield=self.first(g,SHIELD,'board',2).id;spell=self.play(g,FEL);rows=self.shots(g,source);self.assertEqual({r.target_id for r in rows},{g.state.players[2].hero_id,enemy,shield});self.assertEqual({r.batch_id for r in rows},{rows[0].batch_id});self.assertTrue(all(r.base_amount==2 and r.spell_bonus==0 and r.damage_kind==DamageKind.MINION_ABILITY.value for r in rows));self.assertEqual(g.state.entities[enemy].health,3);self.assertEqual(g.state.entities[shield].health,1);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertEqual(g.state.entities[self.first(g,YETI,'board').id].health,5);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,48);self.assertFalse(g.state.battlecry_history);cast,=g.state.cast_history;self.assertEqual((cast.source_id,cast.card_id,cast.completed),(spell,FEL,True));death=next(e.sequence for e in g.events if e.kind=='minion_died'and e.source_id==source);self.assertTrue(all(e.sequence>death for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source))

    def test_blaze_effect_cast_and_first_of_repeated_fel_only_existing_source_triggers(self):
        for driver,extra,origins in((TEST+'auto',(),['hand','effect']),(FEL,(TEST+'repeat',),['hand','repeat','repeat'])):
            with self.subTest(driver=driver):
                g=self.game((driver,),board=(BLAZE,*extra),enemy=(YETI,),pool=False,context=None);source=self.first(g,BLAZE,'board').id;self.play(g,driver);self.assertEqual([c.origin for c in g.state.cast_history],origins);self.assertEqual(len(self.shots(g,source)),2);self.assertEqual(len(g.state.play_history),1);self.assertEqual(len([e for e in g.events if e.kind=='minion_died'and e.source_id==source]),1)

    def test_blaze_fire_foreign_countered_and_departed_silenced_interrupted_fel_negative(self):
        for cid in(FIRE,TEST+'foreign',TEST+'fel_kill',TEST+'fel_return',TEST+'fel_silence',TEST+'fel_lethal'):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(BLAZE,),enemy=(YETI,),pool=False,context=None);source=self.first(g,BLAZE,'board').id;self.play(g,cid,g.state.players[2].hero_id if cid==FIRE else None);self.assertFalse(self.shots(g,source))
                if cid==TEST+'fel_lethal':self.assertTrue(g.state.cast_history[-1].interrupted)
        g=self.game((TEST+'counter',FEL),board=(BLAZE,),pool=False,context=None);source=self.first(g,BLAZE,'board').id;self.play(g,TEST+'counter');self.play(g,FEL);self.assertFalse(self.shots(g,source));self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_blaze_deathrattle_reaction_replaces_enemy_before_current_burst_acceptance(self):
        g=self.game((TEST+'grant_blaze',FEL),board=(BLAZE,),enemy=(YETI,),pool=False,context=None);source=self.first(g,BLAZE,'board').id;old=self.first(g,YETI,'board',2).id;self.play(g,TEST+'grant_blaze');self.play(g,FEL);new=self.first(g,YETI,'board',2).id;self.assertNotEqual(new,old);self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertEqual(g.state.entities[old].health,5);self.assertEqual(g.state.entities[new].health,3);self.assertEqual({r.target_id for r in self.shots(g,source)},{new,g.state.players[2].hero_id})

    def test_blaze_dead_source_wait_fresh_restore_replay_bad_resume_then_new_enemy_is_hit(self):
        g=self.game((FEL,),board=(BLAZE,),mode='blaze_wait',pool=False,context=None);source=self.first(g,BLAZE,'board').id;self.play(g,FEL);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(self.shots(g,source));other=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());new=self.first(g,YETI,'board',2);self.assertEqual(new.health,3);self.assertEqual({r.target_id for r in self.shots(g,source)},{new.id,g.state.players[2].hero_id})

    def test_blaze_late_burst_failure_rolls_back_original_spell_self_death_health_and_rng(self):
        g=self.game((FEL,),board=(BLAZE,),enemy=(YETI,),mode='blaze_fail',pool=False,context=None);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,FEL)
        self.assertEqual(g.snapshot(),before)

    def test_blessing_required_friendly_minion_target_and_paid_buff_granted_dr_no_context(self):
        g=self.game((BLESSING,),board=(YETI,DORMANT),enemy=(YETI,),pool=False,context=None);target=self.first(g,YETI,'board').id;spell=self.first(g,BLESSING).id
        for invalid in(None,g.state.players[1].hero_id,g.state.players[2].hero_id,self.first(g,YETI,'board',2).id,self.first(g,DORMANT,'board').id):
            with self.subTest(invalid=invalid):
                before=g.snapshot()
                with self.assertRaises(IllegalAction):g.apply(PlayCard(1,spell,invalid))
                self.assertEqual(g.snapshot(),before)
        source=self.play(g,BLESSING,target);e=g.state.entities[target];grant,=self.grants(g,target);self.assertEqual((e.attack,e.health,e.max_health),(8,9,9));self.assertEqual((grant.source_id,grant.deathrattle_grant_card_id,grant.origin),(source,BLESSING,'granted'));self.assertEqual(g.state.players[1].mana,45);self.assertFalse(g.state.card_summon_history);self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.registry.card(BLESSING).spell_school,SpellSchool.HOLY)
        g=self.game((BLESSING,),pool=False,context=None);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BLESSING)
        self.assertEqual(g.snapshot(),before)

    def test_blessing_natural_death_original_middle_slot_anyclass_full_new_body_no_battlecry(self):
        g=self.game((BLESSING,TEST+'kill'),board=(SHIELD,YETI,SHIELD),members=(FOUR,));target=self.first(g,YETI,'board').id;left,right=g.state.players[1].board[0],g.state.players[1].board[2];self.play(g,BLESSING,target);rng=random.Random();rng.setstate(g._rng.getstate());self.assertEqual(sample_candidates(rng,self.actual(g,YETI),1,replacement=True),(FOUR,));self.play(g,TEST+'kill',target);child,=self.bodies(g,target);self.assertEqual(g.state.players[1].board,[left,child.id,right]);self.assertEqual((child.card_id,child.attack,child.health),(FOUR,g.registry.card(FOUR).attack,g.registry.card(FOUR).health));self.assertFalse(self.grants(g,child.id));self.assertFalse(g.state.battlecry_history);self.assertEqual(g._rng.getstate(),rng.getstate());root,=g.state.card_summon_history;self.assertEqual(root.request.position,1);self.assertEqual(root.request.cause.source.entity_id,target)

    def test_blessing_live_dr_rightside_and_capacity_skip_keep_original_carrier(self):
        for fill in(0,4):
            with self.subTest(fill=fill):
                g=self.game((BLESSING,TEST+'trigger'),board=(SHIELD,YETI,SHIELD)+(YETI,)*fill,members=(FOUR,));target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);rng=g._rng.getstate();old=list(g.state.players[1].board);self.play(g,TEST+'trigger',target);self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertEqual(g.state.entities[target].health,9)
                if fill:self.assertFalse(self.bodies(g,target));self.assertEqual(g.state.players[1].board,old);self.assertEqual(g._rng.getstate(),rng)
                else:child,=self.bodies(g,target);self.assertEqual(g.state.players[1].board,[old[0],target,child.id,old[2]]);self.assertEqual(g.state.card_summon_history[-1].request.position,2)

    def test_blessing_native_and_granted_dr_independent_and_original_spell_not_native_dr(self):
        g=self.game((BLESSING,TEST+'kill'),board=(PRIMER,),members=(STEGO,));target=self.first(g,PRIMER,'board').id;self.play(g,BLESSING,target);self.assertEqual(len([a for a in g.state.entities[target].abilities if a.kind=='deathrattle']),2);self.play(g,TEST+'kill',target);created=[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==target];self.assertEqual(len(created),1);self.assertEqual(created[0].zone,Zone.HAND);child,=self.bodies(g,target);self.assertEqual((child.card_id,child.attack,child.health),(STEGO,2,6));self.assertIsNone(g.registry.card(BLESSING).deathrattle);self.assertFalse(g.registry.pool_card(BLESSING).deathrattle)

    def test_blessing_silence_bounce_and_current_vs_base_copy_follow_original_attachments(self):
        for operation in('silence','bounce'):
            with self.subTest(operation=operation):
                g=self.game((BLESSING,TEST+operation),board=(YETI,),pool=False,context=None);target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.play(g,TEST+operation,target);self.assertFalse(self.grants(g,target));self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(4,5))
        g=self.game((BLESSING,TEST+'copy',TEST+'base_copy'),board=(YETI,),pool=False,context=None);target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.play(g,TEST+'copy',target);copied=g.state.players[1].board[-1];self.play(g,TEST+'base_copy',target);base=g.state.players[1].board[-1];self.assertEqual((g.state.entities[copied].attack,g.state.entities[copied].max_health),(8,9));self.assertEqual(len(self.grants(g,copied)),1);self.assertNotEqual(self.grants(g,target)[0].id,self.grants(g,copied)[0].id);self.assertFalse(self.grants(g,base));self.assertEqual((g.state.entities[base].attack,g.state.entities[base].max_health),(4,5))

    def test_blessing_current_carrier_controller_receives_summon_after_real_transfer(self):
        g=self.game((BLESSING,TEST+'give',TEST+'kill'),board=(YETI,),members=(FOUR,));target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.play(g,TEST+'give',target);self.play(g,TEST+'kill',target);child,=self.bodies(g,target);self.assertEqual(child.controller,2);self.assertIn(child.id,g.state.players[2].board);self.assertFalse(g.state.players[1].board)

    def test_blessing_source_excluded_empty_four_tier_no_rng_and_no_dormant_filter(self):
        g=self.game((BLESSING,TEST+'trigger'),board=(YETI,),members=(YETI,));target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.assertFalse(self.actual(g,YETI));rng=g._rng.getstate();self.play(g,TEST+'trigger',target);self.assertFalse(self.bodies(g,target));self.assertEqual(g._rng.getstate(),rng)
        g=self.game((BLESSING,TEST+'trigger'),board=(YETI,),members=(DORMANT,FOUR));target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.assertEqual(g.registry.card(DORMANT).cost,2);self.assertEqual({x.card_id for x in self.actual(g,YETI)},{FOUR});self.play(g,TEST+'trigger',target);child,=self.bodies(g,target);self.assertEqual(child.card_id,FOUR);self.assertIsNone(child.dormancy);self.assertFalse(QUERY.keywords_all)

    def test_blessing_actual_dr_missing_context_pool_unknown_even_fullboard_before_rng(self):
        for members,pool,context,fill in(((FOUR,),True,None,0),((FOUR,),False,CONTEXT,0),((FOUR,'CATA_483'),True,CONTEXT,0),((FOUR,'CATA_483'),True,CONTEXT,6)):
            with self.subTest(members=members,pool=pool,fill=fill):
                g=self.game((BLESSING,TEST+'trigger'),board=(YETI,)+(SHIELD,)*fill,members=members,pool=pool,context=context);target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);before=g.snapshot();calls=[];original=random.Random.randrange
                def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'trigger',target)
                self.assertFalse(calls);self.assertEqual(g.snapshot(),before)

    def test_blessing_grant_wait_fresh_restore_replay_bad_resume_and_late_grant_failure(self):
        g=self.game((BLESSING,),board=(YETI,),mode='grant_wait',pool=False,context=None);target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.assertEqual(len(self.grants(g,target)),1);self.assertEqual(g.state.entities[target].attack,8);other=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot())
        g=self.game((BLESSING,),board=(YETI,),mode='grant_fail',pool=False,context=None);target=self.first(g,YETI,'board').id;before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,BLESSING,target)
        self.assertEqual(g.snapshot(),before)

    def test_blessing_natural_dr_entry_wait_fresh_restore_replay_original_slot_and_rollback(self):
        g=self.game((BLESSING,TEST+'kill'),board=(SHIELD,YETI,SHIELD),members=(FOUR,STEGO),mode='summon_wait');target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);self.play(g,TEST+'kill',target);child,=self.bodies(g,target);self.assertEqual(g.state.players[1].board[1],child.id);rng=g._rng.getstate();other=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng)
        g=self.game((BLESSING,TEST+'kill'),board=(YETI,),members=(FOUR,),mode='summon_fail');target=self.first(g,YETI,'board').id;self.play(g,BLESSING,target);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,TEST+'kill',target)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__':unittest.main()
