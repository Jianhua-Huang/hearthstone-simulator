"""Printed native-DR single summon and granted preselected two-entry batch."""
from contextlib import ExitStack
from dataclasses import asdict
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p45_cards import DOG,DIG,ROOTS,EVIDENCE_ONLY,QUERIES,POOL_ID,PREFIX,PAYLOAD,load_batch,register_simple_followup_p45_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

TEST='p45.test.';YETI='CORE_CS2_182';ONE='TIME_058';FOREIGN_ONE='TLC_820';SHIELD='CORE_EX1_008';FOUR_DR='AV_143';FOUR='CORE_CS2_179';FOREIGN_FOUR='TID_700'
MEMBERS=(*ROOTS,YETI,ONE,FOREIGN_ONE,SHIELD,FOUR_DR,FOUR,FOREIGN_FOUR);CONTEXT=GenerationContext('p45-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry(missing_one=False):
    with ExitStack()as stack:
        stack.enter_context(patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None))
        if missing_one:stack.enter_context(patch('hs_sim.cards.pool_entry_dormancy_cards.register_pool_entry_dormancy_cards',lambda r:None))
        r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p45_cards(r)
    elif not all(present):raise AssertionError('P45 central batch must be complete')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True,missing_one=False):
    r=batch_registry(missing_one)
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p45-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),'give':lambda c:(ChangeControl(c.target_id,2),),'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),'natural':lambda c:(Summon(c.player_id,DOG),),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P45 deliberate original continuation failure'))}
    for name,body in scripts.items():r.register_behavior(TEST+name,body);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name not in('natural','fail')else None))
    if mode:
        def eligible(c):
            if mode=='grant_fail':return dict(c.event.data).get('ability_kind')=='deathrattle'and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==DIG
            return any(root.request.cause.source.card_id in(DOG,YETI)and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.endswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        event='ability_granted'if mode=='grant_fail'else'minion_summoned';r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible);r.register_card(CardDefinition(TEST+'watch','Original actual result observer',CardType.MINION,health=12,metadata=META,limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool,missing_one):return registry(members,mode,pool,missing_one)

class SimpleFollowupP45Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,missing_one=False):
        self.config=(members,mode,pool,missing_one)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50)),seed=4545,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def grants(self,g,target):return[a for a in g.state.entities[target].abilities if a.kind=='deathrattle'and a.behavior_id==PAYLOAD]
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def actual(self,g,query,source):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[query],source_card_id=source,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','pool_summon_history','card_summon_history','deathrattle_history'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_three_complete_rows_four_faces_derived_hunter_no_school_and_no_buff_recipe(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['evidence_only']),1);self.assertEqual(tuple(x['record']['id']for x in d['evidence_only']),EVIDENCE_ONLY);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']:
            raw=row['record'];c=r.card(raw['id']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.metadata.classes,(CardClass.HUNTER,));self.assertIsNone(c.spell_school);self.assertEqual(d['derived_metadata'][c.id],{'classes':[x.value for x in c.metadata.classes],'tribes':list(c.metadata.tribes),'school':None});self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords);self.assertIsNone(c.battlecry)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==c.id):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual((f['id'],f['classId'],f['manaCost']),(raw['dbf_id'],raw['tags']['CLASS'],raw['cost']));self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual(len(d['official_observations']['observations']),4);self.assertEqual((r.card(DOG).attack,r.card(DOG).health,r.card(DOG).metadata.tribes),(3,1,('beast',)));self.assertIsNone(r.card(DOG).on_play);self.assertIsNotNone(r.card(DOG).deathrattle);self.assertIsNone(r.card(DIG).deathrattle);self.assertFalse(r.pool_card(DIG).deathrattle)
        for cid in EVIDENCE_ONLY:self.assertNotIn(cid,r.cards);self.assertNotIn(cid,r.pool_cards)

    def test_two_new_defs_all_old_metadata_default_preserved_and_p44_not_carried(self):
        with patch('hs_sim.cards.simple_followup_p45_cards.register_simple_followup_p45_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertNotIn('TIME_021',after.cards)
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_dog_independent_printed_one_cost_deathrattle_fact_anyclass_excludes_plain_and_four(self):
        g=self.game(board=(DOG,));self.assertEqual({x.card_id for x in self.actual(g,DOG,DOG)},{ONE,FOREIGN_ONE});self.assertTrue(QUERIES[DOG].deathrattle);self.assertEqual((QUERIES[DOG].min_cost,QUERIES[DOG].max_cost,QUERIES[DOG].class_mode),(1,1,'any'));self.assertFalse(g.registry.pool_card(SHIELD).deathrattle);self.assertTrue(g.registry.pool_card(FOUR_DR).deathrattle);self.assertEqual(g.registry.card(FOUR_DR).cost,4)

    def test_dog_handplay_or_natural_summon_has_no_bonus_and_silence_removes_actual_dr(self):
        for cid in(DOG,TEST+'natural'):
            with self.subTest(cid=cid):
                g=self.game((cid,),pool=False,context=None);self.play(g,cid);source=self.first(g,DOG,'board').id;self.assertFalse(self.bodies(g,source));self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.deathrattle_history)
        g=self.game((TEST+'silence',TEST+'kill'),board=(DOG,),pool=False,context=None);source=self.first(g,DOG,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source);self.assertFalse(self.bodies(g,source));self.assertFalse(g.state.deathrattle_history)

    def test_dog_natural_middle_death_summons_full_real_one_cost_native_dr_in_original_slot(self):
        g=self.game((TEST+'kill',),board=(SHIELD,DOG,SHIELD),members=(ONE,));source=self.first(g,DOG,'board').id;left,right=g.state.players[1].board[0],g.state.players[1].board[2];rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g,DOG,DOG),1,replacement=True);self.play(g,TEST+'kill',source);child,=self.bodies(g,source);self.assertEqual(g.state.players[1].board,[left,child.id,right]);self.assertEqual((child.card_id,child.attack,child.health),(ONE,1,1));self.assertIsNotNone(g.registry.card(child.card_id).deathrattle);self.assertTrue(any(a.kind=='deathrattle'for a in child.abilities));self.assertFalse(g.state.battlecry_history);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.card_summon_history[-1].request.position,1)

    def test_dog_live_dr_right_side_and_full_capacity_single_draw_skips(self):
        for fill in(0,4):
            with self.subTest(fill=fill):
                g=self.game((TEST+'trigger',),board=(SHIELD,DOG,SHIELD)+(SHIELD,)*fill,members=(ONE,));source=self.first(g,DOG,'board').id;old=g.state.players[1].board;rng=g._rng.getstate();self.play(g,TEST+'trigger',source);self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
                if fill:self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].board,old)
                else:child,=self.bodies(g,source);self.assertEqual(g.state.players[1].board,[old[0],source,child.id,old[2]]);self.assertEqual(g.state.card_summon_history[-1].request.position,2)

    def test_dig_required_friendly_target_paid_four_no_stat_buff_or_native_spell_dr(self):
        g=self.game((DIG,),board=(YETI,),enemy=(YETI,),pool=False,context=None);target=self.first(g,YETI,'board').id;source=self.first(g,DIG).id
        for bad in(None,g.state.players[1].hero_id,self.first(g,YETI,'board',2).id):
            with self.subTest(bad=bad):
                before=g.snapshot()
                with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,bad))
                self.assertEqual(g.snapshot(),before)
        source=self.play(g,DIG,target);e=g.state.entities[target];self.assertEqual((e.attack,e.health,e.max_health),(4,5,5));self.assertFalse(e.enchantments);grant,=self.grants(g,target);self.assertEqual((grant.source_id,grant.deathrattle_grant_card_id,grant.origin),(source,DIG,'granted'));self.assertEqual(g.state.players[1].mana,46);self.assertFalse(g.state.card_summon_history);self.assertEqual(len(g.state.cast_history),1)
        g=self.game((DIG,),pool=False,context=None);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,DIG)
        self.assertEqual(g.snapshot(),before)

    def test_dig_natural_middle_death_two_preselected_anyclass_full_bodies_ordered_original_slots(self):
        g=self.game((DIG,TEST+'kill'),board=(SHIELD,YETI,SHIELD),members=(FOUR,FOREIGN_FOUR));source=self.first(g,YETI,'board').id;old=g.state.players[1].board;self.play(g,DIG,source);rng=random.Random();rng.setstate(g._rng.getstate());selected=sample_candidates(rng,self.actual(g,DIG,YETI),2,replacement=True);self.play(g,TEST+'kill',source);children=self.bodies(g,source);self.assertEqual(len({e.id for e in children}),2);self.assertEqual(tuple(e.card_id for e in children),selected);self.assertEqual(g.state.players[1].board,[old[0],children[0].id,children[1].id,old[2]]);self.assertEqual(g.state.pool_summon_history[-1].selected,selected);self.assertEqual(g.state.pool_summon_history[-1].spec.position,1);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertFalse(g.state.battlecry_history)
        for e in children:self.assertEqual((e.attack,e.health),(g.registry.card(e.card_id).attack,g.registry.card(e.card_id).health));self.assertFalse(self.grants(g,e.id))

    def test_dig_live_batch_presamples_two_even_zero_or_one_delivery_current_capacity(self):
        for fill,delivered in((4,2),(5,1),(6,0)):
            with self.subTest(fill=fill):
                g=self.game((DIG,TEST+'trigger'),board=(YETI,)+(SHIELD,)*fill,members=(FOUR,));source=self.first(g,YETI,'board').id;self.play(g,DIG,source);rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g,DIG,YETI),2,replacement=True);self.play(g,TEST+'trigger',source);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(len(self.bodies(g,source)),delivered);self.assertEqual(g.state.pool_summon_history[-1].selected,(FOUR,FOUR));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.pool_summon_history[-1].spec.position,1)
                if delivered:self.assertEqual(g.state.players[1].board[1],self.bodies(g,source)[0].id)
                self.assertEqual([d.outcome for root in g.state.card_summon_history for d in root.deliveries],['delivered']*delivered+['board_full']*(2-delivered))

    def test_native_dog_and_added_two_card_dr_are_independent_not_replacement(self):
        g=self.game((DIG,TEST+'kill'),board=(DOG,),members=(ONE,FOUR));source=self.first(g,DOG,'board').id;self.play(g,DIG,source);self.assertEqual(len([a for a in g.state.entities[source].abilities if a.kind=='deathrattle']),2);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,1));self.play(g,TEST+'kill',source);self.assertEqual([e.card_id for e in self.bodies(g,source)],[ONE,FOUR,FOUR]);self.assertEqual(len(g.state.pool_summon_history),1)

    def test_duplicate_grants_and_silence_bounce_follow_existing_lifecycle_without_buff(self):
        g=self.game((DIG,DIG,TEST+'trigger'),board=(YETI,),members=(FOUR,));source=self.first(g,YETI,'board').id;self.play(g,DIG,source);self.play(g,DIG,source);self.assertEqual(len({a.id for a in self.grants(g,source)}),2);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,5));self.play(g,TEST+'trigger',source);self.assertEqual(len(self.bodies(g,source)),4);self.assertEqual(len(g.state.pool_summon_history),2)
        for action in('silence','bounce'):
            with self.subTest(action=action):
                g=self.game((DIG,TEST+action),board=(YETI,),pool=False,context=None);source=self.first(g,YETI,'board').id;self.play(g,DIG,source);self.play(g,TEST+action,source);self.assertFalse(self.grants(g,source));self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(4,5))

    def test_actual_dr_controller_after_transfer_uses_current_owner_not_original_spell(self):
        for native in(True,False):
            with self.subTest(native=native):
                card=DOG if native else YETI;hand=(TEST+'give',TEST+'kill')if native else(DIG,TEST+'give',TEST+'kill');g=self.game(hand,board=(card,),members=(ONE,FOUR));source=self.first(g,card,'board').id
                if not native:self.play(g,DIG,source)
                self.play(g,TEST+'give',source);self.play(g,TEST+'kill',source);children=self.bodies(g,source);self.assertEqual(len(children),1 if native else 2);self.assertTrue(all(e.controller==2 and e.id in g.state.players[2].board for e in children));self.assertFalse(g.state.players[1].board)

    def test_both_empty_queries_keep_rng_and_dig_retains_original_carrier_source_exclusion(self):
        for native in(True,False):
            with self.subTest(native=native):
                card=DOG if native else YETI;hand=(TEST+'trigger',)if native else(DIG,TEST+'trigger');members=(SHIELD,)if native else(YETI,);g=self.game(hand,board=(card,),members=members);source=self.first(g,card,'board').id
                if not native:self.play(g,DIG,source)
                rng=g._rng.getstate();self.play(g,TEST+'trigger',source);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng)

    def test_actual_dr_missing_context_pool_and_complete_unknowns_before_rng_even_fullboard(self):
        for native,members,missing in((True,(ONE,),True),(False,(FOUR,'CATA_483'),False)):
            for fill in(0,6):
                with self.subTest(native=native,fill=fill):
                    card=DOG if native else YETI;g=self.game((DIG,TEST+'trigger'),board=(card,)+(SHIELD,)*fill,members=members,missing_one=missing);source=self.first(g,card,'board').id
                    if native:self.assertNotIn(ONE,g.registry.cards);self.assertTrue(g.registry.pool_card(ONE).deathrattle)
                    else:self.play(g,DIG,source)
                    before=g.snapshot();calls=[];original=random.Random.randrange
                    def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
                    with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                        with self.assertRaises(ResolutionError):self.play(g,TEST+'trigger',source)
                    self.assertFalse(calls);self.assertEqual(g.snapshot(),before)
        for native in(True,False):
            for pool,context in((True,None),(False,CONTEXT)):
                with self.subTest(native=native,pool=pool):
                    card=DOG if native else YETI;g=self.game((DIG,TEST+'trigger'),board=(card,),pool=pool,context=context);source=self.first(g,card,'board').id
                    if not native:self.play(g,DIG,source)
                    before=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'trigger',source)
                    self.assertEqual(g.snapshot(),before)

    def test_single_and_first_of_two_actual_entries_wait_restore_replay_bad_resume_without_reroll(self):
        for native in(True,False):
            with self.subTest(native=native):
                card=DOG if native else YETI;hand=(TEST+'kill',)if native else(DIG,TEST+'kill');g=self.game(hand,board=(SHIELD,card,SHIELD),members=(ONE,)if native else(FOUR,FOREIGN_FOUR),mode='wait');source=self.first(g,card,'board').id
                if not native:self.play(g,DIG,source)
                self.play(g,TEST+'kill',source);self.assertEqual(len(self.bodies(g,source)),1);self.assertEqual(g.state.players[1].board[1],self.bodies(g,source)[0].id);rng=g._rng.getstate();selected=None if native else g.state.pool_summon_history[-1].selected;other=self.portable(g);before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),before)
                for x in(g,other):self.choose(x)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.bodies(g,source)),1 if native else 2)
                if not native:self.assertEqual(tuple(e.card_id for e in self.bodies(g,source)),selected)

    def test_late_actual_entry_and_grant_reactions_roll_back_their_whole_original_actions(self):
        for native in(True,False):
            with self.subTest(native=native):
                card=DOG if native else YETI;g=self.game((DIG,TEST+'kill'),board=(card,),members=(ONE,FOUR),mode='entry_fail');source=self.first(g,card,'board').id
                if not native:self.play(g,DIG,source)
                before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,TEST+'kill',source)
                self.assertEqual(g.snapshot(),before)
        g=self.game((DIG,),board=(YETI,),mode='grant_fail',pool=False,context=None);source=self.first(g,YETI,'board').id;before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,DIG,source)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__':unittest.main()
