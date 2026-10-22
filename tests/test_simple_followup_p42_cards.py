"""Original Fire cast acquisition and actual own-turn hero-damage retaliation."""
from dataclasses import asdict
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p42_cards import HERALD,DESTROYER,ROOTS,QUERY,POOL_ID,PREFIX,load_batch,register_simple_followup_p42_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,DamageKind,EndTurn,Game,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellRepeatSpec,SpellSchool,TargetSpec,TriggerSpec,UseHeroPower,Zone
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GainArmor,GrantKeyword,Heal,InvokeBehavior,LoseArmor,RequestChoice,ReturnToHand,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

TEST='p42.test.';YETI='CORE_CS2_182';FIRE='CORE_CS2_029';CHEAP='LOOT_517';EXPENSIVE='CORE_CS2_042';DUAL='CORE_UNG_084';DORMANT='BT_156';SHIELD='CORE_GVG_085'
MEMBERS=(*ROOTS,YETI,FIRE,CHEAP,EXPENSIVE,DUAL);CONTEXT=GenerationContext('p42-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p42_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p42-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def root(c,cid):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==cid)
    def hero(c,p=None):return c.state.players[p or c.player_id].hero_id
    scripts={
        'auto':lambda c:(CastSpell(c.player_id,FIRE,c.source_id,hero(c,3-c.player_id),targeting='explicit'),),
        'foreign_fire':lambda c:(CastSpell(2,FIRE,c.source_id,hero(c,2),targeting='explicit'),),
        'fire_kill':lambda c:(Destroy(root(c,HERALD),c.source_id),),
        'fire_return':lambda c:(ReturnToHand(root(c,HERALD)),),
        'fire_silence':lambda c:(Silence(root(c,HERALD)),),
        'fire_lethal':lambda c:(Damage(hero(c,2),99,c.source_id,DamageKind.SPELL),),
        'counter':lambda c:(SetSecret(2,'EX1_287'),),
        'hurt':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'enemy_source':lambda c:(CastSpell(2,TEST+'hurt',c.source_id,hero(c,1),targeting='explicit'),),
        'self':lambda c:(Damage(hero(c),1,c.source_id,DamageKind.SPELL),),
        'zero':lambda c:(Damage(hero(c),0,c.source_id,DamageKind.SPELL),),
        'heal':lambda c:(Heal(hero(c),2,c.source_id),),
        'armor':lambda c:(GainArmor(c.player_id,8),),
        'lose_armor':lambda c:(LoseArmor(c.player_id,3),),
        'immune':lambda c:(GrantKeyword(hero(c),Keyword.IMMUNE,c.source_id),),
        'batch':lambda c:(DamageBatch((Damage(hero(c),1,c.source_id),Damage(hero(c),1,c.source_id))),),
        'batch_kill_source':lambda c:(DamageBatch((Damage(hero(c),1,c.source_id),Damage(root(c,DESTROYER),3,c.source_id))),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'return':lambda c:(ReturnToHand(c.target_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'fill':lambda c:tuple(AddToHand(c.player_id,YETI,c.source_id)for _ in range(10-len(c.state.players[c.player_id].hand))),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P42 deliberate native continuation failure')),
    }
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,spell_school=SpellSchool.FIRE if name.startswith('fire_')else None,targeting=TargetSpec()if name=='hurt'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','return','silence','give')else None))
    r.register_card(CardDefinition(TEST+'repeat','Three successful casts, one paid play',CardType.MINION,health=12,metadata=META,spell_repeats=(SpellRepeatSpec(3,class_mode='any'),)))
    r.register_card(CardDefinition(TEST+'power','Ordinary spellpower',CardType.MINION,health=12,metadata=META,spell_damage=8))
    r.register_card(CardDefinition(TEST+'invert','Damage converted to healing',CardType.MINION,health=12,metadata=META,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly'),)))
    r.register_card(CardDefinition(TEST+'prevent','Ordinary target prevention',CardType.MINION,health=12,metadata=META,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,layer=HealthLayer.TARGET,target_relation='self'),)))
    if mode:
        def eligible(c):
            if mode in('get_wait','get_fail'):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==HERALD
            if mode=='damage_wait':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==DESTROYER
            result=c.health_result;return result is not None and result.source_card_id==DESTROYER and result.flow==HealthFlow.DAMAGE.value
        def watch(c):
            if mode.endswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            opts=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode=='damage_wait':opts.append(ChoiceOption('return_target','Return already selected target',(ReturnToHand(c.event.target_id),)))
            return(RequestChoice(1,tuple(opts),c.source_id),)
        event='card_created'if mode.startswith('get')else'random_choice'if mode=='damage_wait'else'health_resolved'
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible);r.register_card(CardDefinition(TEST+'watch','Original native result reaction',CardType.MINION,health=12,metadata=META,limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP42Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,active=1,hero='HERO_08'):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hero_power_card_id='HERO_07bp'if hero=='HERO_07'else None,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=(TEST+'hurt',TEST+'self'),board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),active_player=active,seed=4242,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p=p).id;g.apply(PlayCard(p,eid,target,position=len(g.state.players[p].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def shots(self,g,source):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
    def actual(self,g):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERY,source_card_id=HERALD,exclude_source_by_rule=True,current_class=g.state.players[1].hero_class,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','health_result'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_full_two_rows_four_faces_actual_metadata_native_events_without_battlecry(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['official_observations']['observations']),4);norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];card=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']));self.assertFalse(card.keywords);self.assertIsNone(card.on_play);self.assertIsNone(card.battlecry);self.assertIsNone(card.deathrattle);self.assertEqual(card.triggers,(TriggerSpec('spell_cast_finished'if cid==HERALD else'health_resolved',PREFIX+cid),))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],raw['cost'],raw['attack'],raw['health']))
        self.assertEqual((r.card(HERALD).metadata.classes,r.card(HERALD).metadata.tribes),((CardClass.MAGE,),('elemental',)));self.assertEqual((r.card(DESTROYER).metadata.classes,r.card(DESTROYER).metadata.tribes,r.card(DESTROYER).metadata.factions),((CardClass.WARLOCK,),(),()));self.assertEqual(d['cards'][1]['record']['tags']['FACTION'],3);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_only_two_new_defs_preservation_explicitly_suppresses_own_central_registrar(self):
        with patch('hs_sim.cards.simple_followup_p42_cards.register_simple_followup_p42_cards',lambda r:None), \
                patch('hs_sim.cards.assemble_damage_health_followups.register_assemble_damage_health_followups',lambda r:None), \
                patch('hs_sim.cards.assemble_turn_draw_spell_followups.register_assemble_turn_draw_spell_followups',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.kindred_profiles),dict(after.kindred_profiles))
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_herald_real_paid_fire_gets_anyclass_elemental_permanent_minus_three_new_instance(self):
        g=self.game((FIRE,EXPENSIVE),board=(HERALD,),members=(EXPENSIVE,));source=self.first(g,HERALD,'board').id;old=self.first(g,EXPENSIVE).id;deck=g.state.players[1].deck;rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g),1,replacement=True);spell=self.play(g,FIRE,self.hero(g,2));new,=self.created(g,source);self.assertNotEqual(new.id,old);self.assertEqual((new.card_id,new.zone,g.quote_cost(new.id).amount,g.quote_cost(old).amount),(EXPENSIVE,Zone.HAND,3,6));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.players[1].deck,deck);self.assertFalse(g.state.draw_history);self.assertFalse(g.state.battlecry_history);self.assertIsNone(g.state.pending_choice);cast,=g.state.cast_history;self.assertEqual((cast.source_id,cast.card_id,cast.completed,cast.failure),(spell,FIRE,True,None));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,3)

    def test_herald_effect_and_each_successful_repeated_fire_get_once_zero_floor(self):
        g=self.game((TEST+'auto',),board=(HERALD,),members=(CHEAP,));source=self.first(g,HERALD,'board').id;self.play(g,TEST+'auto');new,=self.created(g,source);self.assertEqual((new.card_id,g.quote_cost(new.id).amount),(CHEAP,0));self.assertEqual([c.origin for c in g.state.cast_history],['hand','effect']);self.assertEqual(len(g.state.play_history),1)
        g=self.game((FIRE,),board=(HERALD,TEST+'repeat'),members=(CHEAP,));source=self.first(g,HERALD,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g),3,replacement=True);self.play(g,FIRE,self.hero(g,2));cards=self.created(g,source);self.assertEqual(len({e.id for e in cards}),3);self.assertTrue(all(g.quote_cost(e.id).amount==0 for e in cards));self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat','repeat']);self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g._rng.getstate(),rng.getstate())

    def test_herald_query_uses_complete_elemental_fact_anyclass_dual_tribe_and_source_exclusion(self):
        g=self.game(board=(HERALD,));self.assertEqual({m.card_id for m in self.actual(g)},{CHEAP,EXPENSIVE,DUAL});self.assertEqual(QUERY.kinds,(CardType.MINION,));self.assertTrue(QUERY.collectible);self.assertEqual(QUERY.tribes_any,('elemental',));self.assertEqual(QUERY.class_mode,'any')

    def test_herald_non_fire_foreign_and_countered_casts_do_not_require_context(self):
        for cid in(TEST+'heal',TEST+'foreign_fire'):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(HERALD,),pool=False,context=None);source=self.first(g,HERALD,'board').id;self.play(g,cid);self.assertFalse(self.created(g,source))
        g=self.game((TEST+'counter',FIRE),board=(HERALD,),pool=False,context=None);source=self.first(g,HERALD,'board').id;self.play(g,TEST+'counter');self.play(g,FIRE,self.hero(g,2));self.assertFalse(self.created(g,source));self.assertEqual(g.state.cast_history[-1].failure,'countered')

    def test_herald_source_dies_returns_silences_during_fire_and_terminal_cast_never_gets(self):
        for cid in('fire_kill','fire_return','fire_silence','fire_lethal'):
            with self.subTest(cid=cid):
                g=self.game((TEST+cid,),board=(HERALD,),pool=False,context=None);source=self.first(g,HERALD,'board').id;self.play(g,TEST+cid);self.assertFalse(self.created(g,source))
                if cid=='fire_lethal':self.assertTrue(g.state.cast_history[-1].interrupted);self.assertFalse(g.state.cast_history[-1].completed)

    def test_herald_fullhand_burn_and_empty_pool_preserve_real_delivery_and_rng_policy(self):
        g=self.game((TEST+'fill',FIRE),board=(HERALD,),members=(CHEAP,));source=self.first(g,HERALD,'board').id;self.play(g,TEST+'fill');self.assertEqual(len(g.state.players[1].hand),10);self.play(g,FIRE,self.hero(g,2));self.assertEqual(len(g.state.players[1].hand),10)
        # Fire itself frees one slot; two native sources produce one hand card and one complete burned card.
        g=self.game((TEST+'fill',FIRE),board=(HERALD,HERALD),members=(CHEAP,));sources=g.state.players[1].board;self.play(g,TEST+'fill');self.play(g,FIRE,self.hero(g,2));cards=[e for i in sources for e in self.created(g,i)];self.assertEqual(len(cards),2);self.assertEqual({e.zone for e in cards},{Zone.HAND,Zone.GRAVEYARD});self.assertTrue(all(e.cost==0 for e in cards))
        g=self.game((FIRE,),board=(HERALD,),members=(HERALD,YETI));source=self.first(g,HERALD,'board').id;rng=g._rng.getstate();self.play(g,FIRE,self.hero(g,2));self.assertFalse(self.created(g,source));self.assertEqual(g._rng.getstate(),rng)

    def test_herald_acquisition_wait_bad_resume_independent_restore_replay_and_privacy(self):
        g=self.game((FIRE,),board=(HERALD,),members=(CHEAP,EXPENSIVE),mode='get_wait');source=self.first(g,HERALD,'board').id;self.play(g,FIRE,self.hero(g,2));new,=self.created(g,source);self.assertEqual(new.cost,max(0,g.registry.card(new.card_id).cost-3));self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id']);other=self.portable(g);before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng)

    def test_herald_missing_host_unknown_eligible_and_late_failure_rollback_original_fire_rng(self):
        for members,mode,pool,context in((MEMBERS,None,True,None),(MEMBERS,None,False,CONTEXT),((CHEAP,'CATA_483'),None,True,CONTEXT),((CHEAP,),'get_fail',True,CONTEXT)):
            with self.subTest(members=members,mode=mode,pool=pool,context=context):
                g=self.game((FIRE,),board=(HERALD,),members=members,mode=mode,pool=pool,context=context);before=g.snapshot();calls=[];original=random.Random.randrange
                def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):self.play(g,FIRE,self.hero(g,2))
                self.assertEqual(g.snapshot(),before)
                if mode is None:self.assertFalse(calls)

    def test_destroyer_own_or_enemy_source_hero_damage_on_owner_turn_targets_enemy_minion_only(self):
        for cid in('self','enemy_source'):
            with self.subTest(cid=cid):
                g=self.game((TEST+cid,),board=(DESTROYER,YETI),enemy=(YETI,DORMANT),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;target=self.first(g,YETI,'board',2).id;rng=random.Random();rng.setstate(g._rng.getstate());self.assertEqual(rng.choice([target]),target);self.play(g,TEST+cid);shot,=self.shots(g,source);self.assertEqual((shot.target_id,shot.base_amount,shot.damage_dealt,shot.damage_kind,shot.spell_bonus),(target,3,3,DamageKind.MINION_ABILITY.value,0));self.assertEqual(g.state.entities[self.hero(g,2)].health,30);self.assertEqual(g.state.entities[self.first(g,YETI,'board').id].health,5);self.assertEqual(g._rng.getstate(),rng.getstate())

    def test_destroyer_armor_absorbed_damage_qualifies_but_plain_armor_loss_does_not(self):
        g=self.game((TEST+'armor',TEST+'lose_armor',TEST+'self'),board=(DESTROYER,),enemy=(YETI,),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'armor');self.play(g,TEST+'lose_armor');self.assertFalse(self.shots(g,source));self.play(g,TEST+'self');result=next(r.health_result for r in g.state.damage_history if r.health_result.target_id==self.hero(g));self.assertEqual((result.damage_dealt,result.armor_absorbed,result.health_lost),(1,1,0));self.assertEqual(len(self.shots(g,source)),1);self.assertEqual(g.state.entities[self.hero(g)].health,30)

    def test_destroyer_wrong_turn_other_hero_minion_zero_heal_conversion_and_immunity_negative(self):
        for cid,target,active,extra in(('hurt','own',2,()),('hurt','enemy',1,()),('hurt','minion',1,()),('zero',None,1,()),('heal',None,1,()),('self',None,1,(TEST+'invert',)),('immune',None,1,())):
            with self.subTest(cid=cid,target=target,active=active):
                hand=(TEST+cid,TEST+'self')if cid=='immune'else(TEST+cid,);g=self.game(hand,board=(DESTROYER,YETI,*extra),enemy=(YETI,),active=active,pool=False,context=None);source=self.first(g,DESTROYER,'board').id;rng=g._rng.getstate();victim=self.hero(g)if target=='own'else self.hero(g,2)if target=='enemy'else self.first(g,YETI,'board').id if target=='minion'else None;self.play(g,TEST+cid,victim,p=active)
                if cid=='immune':self.play(g,TEST+'self')
                self.assertFalse(self.shots(g,source));self.assertEqual(g._rng.getstate(),rng)

    def test_destroyer_fixed_three_minion_ability_ignores_spellpower_and_uses_shared_shield_rules(self):
        for enemy,expected in((YETI,3),(SHIELD,0),(TEST+'prevent',0)):
            with self.subTest(enemy=enemy):
                g=self.game((TEST+'self',),board=(DESTROYER,TEST+'power'),enemy=(enemy,),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'self');shot,=self.shots(g,source);self.assertEqual((shot.base_amount,shot.damage_dealt,shot.spell_bonus,shot.damage_kind),(3,expected,0,DamageKind.MINION_ABILITY.value))
                if enemy==YETI:self.assertEqual(shot.modified_amount,3)

    def test_destroyer_empty_or_only_dormant_enemy_board_skips_rng(self):
        for enemy in((),(DORMANT,)):
            with self.subTest(enemy=enemy):
                g=self.game((TEST+'self',),board=(DESTROYER,),enemy=enemy,pool=False,context=None);source=self.first(g,DESTROYER,'board').id;rng=g._rng.getstate();self.play(g,TEST+'self');self.assertFalse(self.shots(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertTrue(any(e.kind=='random_choice_skipped'and e.source_id==source for e in g.events))

    def test_destroyer_actual_two_packets_each_trigger_and_dead_source_batch_suppresses(self):
        g=self.game((TEST+'batch',),board=(DESTROYER,),enemy=(YETI,),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;target=self.first(g,YETI,'board',2).id;rng=random.Random();rng.setstate(g._rng.getstate());rng.choice([target]);rng.choice([target]);self.play(g,TEST+'batch');self.assertEqual([s.damage_dealt for s in self.shots(g,source)],[3,3]);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng.getstate())
        g=self.game((TEST+'batch_kill_source',),board=(DESTROYER,),enemy=(YETI,),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'batch_kill_source');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(self.shots(g,source))

    def test_destroyer_real_warlock_life_tap_and_control_transfer_use_original_controller(self):
        g=self.game(board=(DESTROYER,),enemy=(YETI,),hero='HERO_07',pool=False,context=None);source=self.first(g,DESTROYER,'board').id;g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(len(self.shots(g,source)),1);self.assertEqual(g.state.entities[self.hero(g)].health,28);self.assertEqual(len(g.state.draw_history),1)
        g=self.game((TEST+'give',),board=(DESTROYER,YETI),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'give',source);g.apply(EndTurn(1));self.play(g,TEST+'self',p=2);shot,=self.shots(g,source);self.assertEqual(shot.target_controller,1);self.assertEqual(shot.source_controller,2)

    def test_destroyer_silenced_dead_or_returned_source_does_not_react(self):
        for operation in('silence','kill','return'):
            with self.subTest(operation=operation):
                g=self.game((TEST+operation,TEST+'self'),board=(DESTROYER,),enemy=(YETI,),pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+operation,source);self.play(g,TEST+'self');self.assertFalse(self.shots(g,source))

    def test_destroyer_sampled_before_damage_wait_fresh_restore_bad_resume_and_no_reroll(self):
        g=self.game((TEST+'self',),board=(DESTROYER,),enemy=(YETI,YETI),mode='damage_wait',pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'self');self.assertFalse(self.shots(g,source));choice=next(e for e in g.events if e.kind=='random_choice'and e.source_id==source);rng=g._rng.getstate();other=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);shot,=self.shots(g,source);self.assertEqual(shot.target_id,choice.target_id)

    def test_destroyer_selected_target_leaves_without_reroll_and_late_damage_failure_rolls_back(self):
        g=self.game((TEST+'self',),board=(DESTROYER,),enemy=(YETI,YETI),mode='damage_wait',pool=False,context=None);source=self.first(g,DESTROYER,'board').id;self.play(g,TEST+'self');rng=g._rng.getstate();self.choose(g,'return_target');self.assertFalse(self.shots(g,source));self.assertEqual(g._rng.getstate(),rng)
        g=self.game((TEST+'self',),board=(DESTROYER,),enemy=(YETI,),mode='damage_fail',pool=False,context=None);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,TEST+'self')
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__':unittest.main()
