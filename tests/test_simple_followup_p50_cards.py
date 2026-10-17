"""Reachability evidence and grouped native child/power execution boundaries."""
from dataclasses import asdict
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p50_cards import (GHOST,POWER,BLOOD,PLUME,BODY,STRIKER,GOLD,STORM,
    JUVENILE,IMP,INFERNAL,ROOTS,DEPENDENCIES,PARENTS,POOL_ID,FIRE_QUERY,load_batch,register_simple_followup_p50_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,Ruleset,Scenario,SelectChoice,EndTurn,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,GrantKeyword,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,SpellSchool
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p50.test.';YETI='CORE_CS2_182';FIRE='CORE_CS2_029';OTHER_FIRE='CATA_581';NATURE='CORE_CS2_009';SHIELD='CORE_GVG_085'
MEMBERS=(FIRE,OTHER_FIRE,NATURE);CONTEXT=GenerationContext('p50-explicit-complete-fixture','experimental')
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(i in r.cards for i in ROOTS+DEPENDENCIES)
    if not any(present):register_simple_followup_p50_cards(r)
    elif not all(present):raise AssertionError('P50 central assembly must contain the complete child family')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p50-complete-explicit-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(i)for i in members),complete=True))
    scripts={name:(lambda c,n=n:(Damage(c.target_id,n,c.source_id,DamageKind.SPELL),))for name,n in(('hit0',0),('hit1',1),('hit5',5))}
    scripts.update(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        shield=lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        hit_full=lambda c:(AddToHand(1,YETI,c.source_id),Damage(c.target_id,1,c.source_id,DamageKind.SPELL)),
        reenter=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller,cause=SummonCause.capture(c)),),
        wound_hero=lambda c:(Damage(c.state.players[1].hero_id,10,c.source_id),),
        natural_gold=lambda c:(Summon(1,GOLD),),natural_storm=lambda c:(Summon(1,STORM),),
        fail=lambda c:(_ for _ in()).throw(ResolutionError('P50 deliberate continuation failure')))
    for name,body in scripts.items():
        r.register_behavior(TEST+name,body);targeted=name in('hit0','hit1','hit5','kill','silence','shield','hit_full')
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,
            **({'targeting':TargetSpec()}if targeted else{})))
    r.register_card(CardDefinition(TEST+'dormant','Physical dormant occupancy',CardType.MINION,attack=1,health=9,
        dormant_turns=2,metadata=META))
    if mode:
        def eligible(c):
            if mode=='plume':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==PLUME and c.event.amount>0
            if mode=='power':return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id==INFERNAL
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==(BLOOD if mode=='blood'else BODY)
        def watch(c):
            options=[ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode in('blood','body'):
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==YETI)
                options.append(ChoiceOption('reenter','Return and reenter original minion',(
                    ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))))
            return(RequestChoice(1,tuple(options),c.source_id),)
        event={'plume':'health_resolved','power':'minion_summoned'}.get(mode,'choice_skipped')
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Native continuation witness',CardType.WEAPON if mode=='body'else CardType.MINION,
            **({'durability':5}if mode=='body'else{'health':20}),metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP50Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,
            power=False,mana=50,rules=None):
        self.config=(members,mode,pool)
        if mode and mode!='body':board=(TEST+'watch',*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09'if power else'HERO_08',hand=hand,board=board,
            deck=(YETI,)*8,mana=mana,max_mana=50,mana_cap=50,hero_power_card_id=POWER if power else None,
            weapon_card_id=TEST+'watch'if mode=='body'else None),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,
            mana=50,max_mana=50,mana_cap=50)),seed=5050,generation_context=context),shared_registry(*self.config),rules)
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for k in('rng_state','resolution_frame','pool_id','behavior_id','source_json','health_result'):
                self.assertNotIn('"'+k+'"',public)
        return other

    def test_twenty_one_full_raw_rows_twenty_two_child_faces_and_typed_printed_definitions(self):
        d=load_batch();r=batch_registry();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(10,1,10,22))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$#&_]','',s)
        for row in d['cards']+d['dependencies']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']+d['dependencies']:
            raw=row['record'];c=r.card(raw['id']);self.assertFalse(c.metadata.collectible);self.assertEqual(c.metadata,metadata_from_record(raw))
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack']or 0,raw['health']or 0));self.assertIsNone(c.spell_school)
            obs=[o for o in d['official_observations']if o['card_id']==raw['id']];self.assertEqual(len(obs),2)
            for o in obs:
                f=o['face'];en=o['locale']=='en_US';self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertFalse(re.match(r'^[A-Za-z]:',o['response_file']))
        self.assertEqual(d['scope']['collectible_root_progress'],0);self.assertEqual(d['scope']['parent_implementations_added'],0)

    def test_twenty_full_parent_faces_and_primary_links_not_parent_rule_implementation(self):
        d=load_batch();pr=d['parent_reachability_review'];rows={x['record']['id']:x['record']for x in d['cards']+d['dependencies']+d['evidence_only']}
        self.assertEqual((len(pr['observations']),len(pr['links'])),(20,20));self.assertFalse(pr['parent_implementations_verified'])
        self.assertTrue(pr['parent_rules_text_equality_not_claimed'])
        for link in pr['links']:
            o=next(o for o in pr['observations']if(o['card_id'],o['locale'])==(link['parent'],link['locale']))
            self.assertEqual(o['face']['id'],rows[link['parent']]['dbf_id']);self.assertIn(rows[link['child']]['dbf_id'],o['face']['childIds'])
            self.assertEqual(d['standard_parent_map'][link['child']],link['parent']);self.assertRegex(o['response_sha256'],r'^[a-f0-9]{64}$')
        self.assertEqual(rows['CORE_EX1_323']['tags']['HERO_POWER'],1178)
        for o in(o for o in pr['observations']if o['card_id']=='CORE_EX1_323'):
            self.assertTrue({1178,1143}.issubset(o['face']['childIds']))
        il=d['infernal_native_link_review'];self.assertTrue(il['power_face_has_no_childIds']);self.assertEqual(len(il['primary_links']),2)
        self.assertEqual((rows[INFERNAL]['attack'],rows[INFERNAL]['health']),(6,6));self.assertEqual(rows[POWER]['text_en'],il['power_native_text'])

    def test_only_eleven_child_definitions_old_full_definitions_pools_defaults_and_main_fix_preserved(self):
        with patch('hs_sim.cards.simple_followup_p50_cards.register_simple_followup_p50_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES))
        for i,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(i)))
        for i,c in before.pool_cards.items():self.assertEqual(c,after.pool_card(i))
        self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        for p in PARENTS:self.assertEqual(p in before.cards,p in after.cards)
        self.assertEqual(before.card('CATA_581'),after.card('CATA_581'))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_fixed_printed_bodies_native_keywords_and_no_parent_specific_summon_payload(self):
        expected={GHOST:(2,2,1,(Keyword.REBORN,)),STRIKER:(3,6,6,(Keyword.TAUNT,)),JUVENILE:(3,3,3,()),IMP:(2,3,2,()),INFERNAL:(6,6,6,())}
        r=batch_registry()
        for cid,(cost,attack,health,keys)in expected.items():
            with self.subTest(cid=cid):
                c=r.card(cid);self.assertEqual((c.cost,c.attack,c.health,c.keywords),(cost,attack,health,keys))
                self.assertIsNone(c.on_play);self.assertIsNone(c.battlecry);self.assertIsNone(c.deathrattle);self.assertFalse(c.triggers)
        g=self.game((JUVENILE,),enemy=(YETI,),pool=False,context=None);self.play(g,JUVENILE)
        self.assertEqual((self.first(g,JUVENILE,'board').health,self.first(g,YETI,'board',2).health),(3,5))

    def test_ghost_native_reborn_once_and_silence_removes_only_printed_keyword(self):
        g=self.game((TEST+'kill',TEST+'kill'),board=(GHOST,),pool=False,context=None);old=self.first(g,GHOST,'board').id
        self.play(g,TEST+'kill',old);new=self.first(g,GHOST,'board');self.assertNotEqual(old,new.id)
        self.assertEqual((new.attack,new.health),(2,1));self.assertNotIn(Keyword.REBORN,new.keywords)
        self.play(g,TEST+'kill',new.id);self.assertFalse(g.state.players[1].board)
        g=self.game((TEST+'silence',TEST+'kill'),board=(GHOST,),pool=False,context=None)
        source=self.first(g,GHOST,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source)
        self.assertFalse(g.state.players[1].board)

    def test_blood_only_damaged_friendly_characters_and_empty_pool_consumes_no_rng(self):
        g=self.game(board=(BLOOD,YETI),pool=False,context=None);rng=g._rng.getstate();g.apply(EndTurn(1));self.assertEqual(g._rng.getstate(),rng)
        g=self.game((TEST+'hit1',),board=(BLOOD,),enemy=(YETI,),pool=False,context=None)
        self.play(g,TEST+'hit1',self.first(g,YETI,'board',2).id);rng=g._rng.getstate();g.apply(EndTurn(1))
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.first(g,YETI,'board',2).health,4)
        g=self.game((TEST+'wound_hero',),board=(BLOOD,YETI),pool=False,context=None);self.play(g,TEST+'wound_hero')
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23)
        result=g.state.healing_history[-1].health_result;self.assertEqual((result.base_amount,result.healed),(3,3))

    def test_blood_owner_end_and_original_injured_minion_clamps_overheal(self):
        g=self.game((TEST+'hit1',),board=(BLOOD,YETI),pool=False,context=None);target=self.first(g,YETI,'board').id
        self.play(g,TEST+'hit1',target);g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].health,5)
        result=g.state.healing_history[-1].health_result;self.assertEqual((result.healed,result.overheal),(1,2))
        count=len(g.state.healing_history);g.apply(EndTurn(2));self.assertEqual(len(g.state.healing_history),count)

    def test_blood_selected_original_wait_restore_replay_and_same_id_reentry_is_not_healed(self):
        g=self.game((TEST+'hit1',),board=(BLOOD,YETI),mode='blood',pool=False,context=None);target=self.first(g,YETI,'board').id
        self.play(g,TEST+'hit1',target);g.apply(EndTurn(1));other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x,'reenter')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].health,5);self.assertFalse(g.state.healing_history)

    def test_plume_actual_nonlethal_damage_gets_any_class_collectible_fire_discounted_three(self):
        for cid in(FIRE,OTHER_FIRE):
            with self.subTest(cid=cid):
                g=self.game((TEST+'hit1',),board=(PLUME,),members=(cid,NATURE));source=self.first(g,PLUME,'board').id
                self.play(g,TEST+'hit1',source);card,=self.created(g,source);self.assertEqual(card.card_id,cid)
                self.assertEqual(quote_unselected_cost(g.state,g.registry,card).amount,max(0,g.registry.card(cid).cost-3))
                self.assertEqual(g.state.entities[source].health,4)

    def test_plume_lethal_accepted_damage_reward_survives_wait_restore_replay_and_bad_resume(self):
        g=self.game((TEST+'hit5',),board=(PLUME,),members=(FIRE,),mode='plume');source=self.first(g,PLUME,'board').id
        self.play(g,TEST+'hit5',source);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        card,=self.created(g,source);self.assertEqual((card.card_id,card.zone),(FIRE,Zone.HAND))

    def test_plume_zero_shield_silence_do_not_reward_and_full_hand_burns_real_generated_card(self):
        for prefix in('hit0','shield','silence'):
            with self.subTest(prefix=prefix):
                hand=(TEST+prefix,)if prefix=='hit0'else(TEST+prefix,TEST+'hit1')
                g=self.game(hand,board=(PLUME,),members=(FIRE,));source=self.first(g,PLUME,'board').id
                self.play(g,TEST+prefix,source)
                if prefix!='hit0':self.play(g,TEST+'hit1',source)
                self.assertFalse(self.created(g,source))
        g=self.game((TEST+'hit_full',)+(YETI,)*9,board=(PLUME,),members=(FIRE,));source=self.first(g,PLUME,'board').id
        self.play(g,TEST+'hit_full',source);card,=self.created(g,source);self.assertEqual(card.zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),10)

    def test_plume_unknown_complete_eligible_fire_spell_errors_before_rng_and_rolls_back_lethal_damage(self):
        r=batch_registry();unknown=next(c.card_id for c in r.pool_cards.values()if c.card_id not in r.cards
            and c.kind==CardType.SPELL and c.spell_school==SpellSchool.FIRE and c.metadata.collectible)
        g=self.game((TEST+'hit5',),board=(PLUME,),members=(FIRE,unknown));source=self.first(g,PLUME,'board').id
        saved=g.snapshot();calls=[];original=random.Random.randrange
        def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
        with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
            with self.assertRaises(ResolutionError):self.play(g,TEST+'hit5',source)
        self.assertFalse(calls);self.assertEqual(g.snapshot(),saved)

    def test_magmaw_real_death_buff_only_attack_current_death_controller_and_empty_pool_no_rng(self):
        for p in(1,2):
            with self.subTest(p=p):
                g=self.game((TEST+'kill',),board=(BODY,YETI)if p==1 else(YETI,),enemy=(BODY,YETI)if p==2 else(),pool=False,context=None)
                self.play(g,TEST+'kill',self.first(g,BODY,'board',p).id);e=self.first(g,YETI,'board',p)
                self.assertEqual((e.attack,e.health),(6,5))
        g=self.game((TEST+'kill',),board=(BODY,),pool=False,context=None);rng=g._rng.getstate()
        self.play(g,TEST+'kill',self.first(g,BODY,'board').id);self.assertEqual(g._rng.getstate(),rng)

    def test_magmaw_original_selected_target_same_id_reentry_does_not_receive_old_buff(self):
        g=self.game((TEST+'kill',),board=(BODY,YETI),mode='body',pool=False,context=None)
        target=self.first(g,YETI,'board');self.play(g,TEST+'kill',self.first(g,BODY,'board').id);self.choose(g,'reenter')
        current=g.state.entities[target.id];self.assertNotEqual(current.board_presence_id,target.board_presence_id)
        self.assertEqual((current.attack,current.health),(4,5))

    def test_gold_native_available_character_target_deals_four_minion_ability_without_spell_bonus(self):
        for target_kind in('hero','minion'):
            with self.subTest(target_kind=target_kind):
                g=self.game((GOLD,),board=('CORE_EX1_012',),enemy=(YETI,),pool=False,context=None)
                target=g.state.players[2].hero_id if target_kind=='hero'else self.first(g,YETI,'board',2).id
                before=g.state.entities[target].health;self.play(g,GOLD,target);self.assertEqual(g.state.entities[target].health,before-4)
                result=g.state.damage_history[-1].health_result;self.assertEqual((result.damage_kind,result.base_amount,result.spell_bonus),(DamageKind.MINION_ABILITY.value,4,0))

    def test_storm_native_enemy_minion_batch_and_actual_lifesteal_not_spell_damage(self):
        g=self.game((TEST+'wound_hero',STORM),board=('CORE_EX1_012',),enemy=(YETI,YETI,SHIELD),pool=False,context=None)
        self.play(g,TEST+'wound_hero');source=self.play(g,STORM);hero=g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].health,24);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        rows=[r.health_result for r in g.state.damage_history if r.health_result.source_id==source]
        self.assertEqual(len(rows),3);self.assertTrue(all((r.damage_kind,r.base_amount,r.spell_bonus)==(DamageKind.MINION_ABILITY.value,2,0)for r in rows))
        self.assertEqual(sum(r.damage_dealt for r in rows),4);self.assertEqual(self.first(g,SHIELD,'board',2).health,2)

    def test_ordinary_summons_of_damage_children_do_not_invoke_battlecries(self):
        for script in('natural_gold','natural_storm'):
            g=self.game((TEST+script,),enemy=(YETI,),pool=False,context=None);self.play(g,TEST+script)
            self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.damage_history)

    def test_inferno_native_cost_one_use_per_turn_fixed_six_six_and_original_power_summon_cause(self):
        g=self.game(power=True,pool=False,context=None);pid=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.state.players[1].mana,48);e=self.first(g,INFERNAL,'board');self.assertEqual((e.attack,e.health),(6,6))
        self.assertFalse(g.state.battlecry_history);self.assertEqual(len(g.state.hero_power_history),1)
        root,=g.state.card_summon_history;self.assertEqual(root.request.cause.source.entity_id,pid);self.assertEqual(root.request.cause.origin,'hero_power')
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id==INFERNAL]),2)

    def test_inferno_insufficient_mana_and_actual_full_capacity_including_dormant_do_not_pay_or_use(self):
        cases=(((),1,None),((YETI,)*7,50,None),((YETI,)*7+(TEST+'dormant',),50,Ruleset(max_board=8)))
        for board,mana,rules in cases:
            with self.subTest(board=len(board),mana=mana):
                g=self.game(board=board,mana=mana,rules=rules,power=True,pool=False,context=None);saved=g.snapshot()
                with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
                self.assertEqual(g.snapshot(),saved);self.assertFalse(g.state.hero_power_history)

    def test_inferno_actual_summon_wait_restore_replay_and_failed_resume_keep_one_payment_and_use(self):
        g=self.game(power=True,mode='power',pool=False,context=None);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,48)
        self.assertEqual(len(g.state.hero_power_history),1);self.assertEqual(len(g.state.card_summon_history),1)

if __name__=='__main__':unittest.main()
