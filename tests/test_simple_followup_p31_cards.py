"""Targeted first effects and ordinary private pool continuations."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
from types import SimpleNamespace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p31_cards import ORB,ADVANCE,SNAP,PHOTO,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p31_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,DamageKind,Game,HealingKind,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetMode,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,Damage,Freeze,Heal,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p31.test.';YETI='CORE_CS2_182';WHELP='CATA_484';MAGE='CS2_029';FROST='CORE_CS2_024';DK_FROST='RLK_709';DRUID='CS2_009';DUAL='END_007';NEUTRAL='TIME_EVENT_999';BONUS='EX1_012'
MEMBERS=(*ROOTS,MAGE,FROST,DK_FROST,DRUID,DUAL,NEUTRAL);CONTEXT=GenerationContext('p31-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p31_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p31-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_behavior(TEST+'wound',lambda c:(Damage(c.target_id,10,c.source_id),));r.register_card(CardDefinition(TEST+'wound','Actual wound fixture',CardType.SPELL,on_play=TEST+'wound',metadata=META,targeting=TargetSpec()))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P31 deliberate continuation failure')))
    if mode:
        def eligible(c):
            if mode=='wait':return c.health_result is not None and c.health_result.source_card_id==ORB and c.health_result.damage_kind==DamageKind.SPELL.value
            return c.event.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual first-effect or arrival reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('health_resolved'if mode=='wait'else'card_added_to_hand',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP31Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8)),seed=3131,generation_context=context),registry(members,mode,pool))
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def first(self,g,cid,p=1,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key=None):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id if key is None else key,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def results(self,g,source):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','freeze_summoned','heal_hero_by_printed_cost','candidate_root_ids'):self.assertNotIn('"'+key+'"',public)
        return other
    def candidates(self,r,cid):return resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[cid],source_card_id=cid,exclude_source_by_rule=True,current_class=CardClass.MAGE,player_id=1)

    def test_five_complete_rows_eight_faces_scoped_display_normalization_and_full_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),8);self.assertEqual(d['reviewed_display_normalizations'],{PHOTO:{'#6':'6'}});self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s,cid):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s.replace('#6','6')if cid==PHOTO else s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,raw['cost']);self.assertEqual(c.targeting.mode,TargetMode.REQUIRED);self.assertEqual(c.targeting.relation,'enemy'if cid==SNAP else'any');self.assertFalse(c.keywords)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text'],cid),norm(raw['text_en'if en else'text'],cid));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],c.cost))
            first,second=r.behavior(c.on_play)(SimpleNamespace(player_id=1,source_id=42,target_id=99));self.assertEqual(first.target_id,99);self.assertEqual(second.source_id,42)
            if cid in(ORB,ADVANCE):self.assertIsInstance(second,DiscoverFromPool);self.assertEqual((second.count,second.destination),(3,'hand'));self.assertFalse(second.freeze_summoned);self.assertFalse(second.heal_hero_by_printed_cost);self.assertIsNone(second.gift_pool)
        self.assertEqual(r.card(ADVANCE).metadata.runes.frost,2);self.assertEqual(r.card(ADVANCE).metadata.runes.total,2);self.assertEqual([r.card(c).spell_school for c in ROOTS],[SpellSchool.ARCANE,SpellSchool.FROST,SpellSchool.FROST,SpellSchool.NATURE]);self.assertIn('#6',d['cards'][3]['record']['text'])

    def test_four_new_defs_old_definitions_alias_catalog_and_families_preserved(self):
        with patch('hs_sim.cards.simple_followup_p31_cards.register_simple_followup_p31_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else row,after.pool_card(cid))
        self.assertEqual('BAR_541'in before.cards,'BAR_541'in after.cards);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_exact_current_hero_neutral_frost_anyclass_and_fixed_druid_dual_queries(self):
        r=registry();self.assertEqual({m.card_id for m in self.candidates(r,ORB)},{SNAP,MAGE,FROST,NEUTRAL});self.assertEqual({m.card_id for m in self.candidates(r,ADVANCE)},{ORB,SNAP,MAGE,FROST,NEUTRAL});self.assertEqual({m.card_id for m in self.candidates(r,SNAP)},{ADVANCE,FROST,DK_FROST});self.assertEqual({m.card_id for m in self.candidates(r,PHOTO)},{DRUID,DUAL});self.assertFalse(QUERIES[PHOTO].include_neutral);self.assertEqual(QUERIES[PHOTO].classes,(CardClass.DRUID,))

    def test_orb_paid_spell_damage_bonus_then_private_discovery_and_new_card(self):
        g=self.game((ORB,),board=(BONUS,),members=(MAGE,));target=self.hero(g,2);source=self.play(g,ORB,target);result,=self.results(g,source);self.assertEqual((result.damage_kind,result.base_amount,result.damage_dealt),(DamageKind.SPELL.value,2,3));self.assertEqual(g.state.entities[target].health,27);self.assertEqual(g.state.players[1].mana,48);self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.created(g,source));other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,MAGE);self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'],None);self.portable(g)

    def test_orb_original_minion_dies_before_discovery_without_retarget(self):
        g=self.game((ORB,),enemy=(WHELP,),members=(MAGE,));target=self.first(g,WHELP,2,'board').id;source=self.play(g,ORB,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.results(g,source)[0].target_id,target);self.choose(g);self.assertEqual(len(self.created(g,source)),1)

    def test_advance_friendly_hero_freezes_before_ordinary_current_class_hand_discovery(self):
        g=self.game((ADVANCE,),members=(MAGE,));target=self.hero(g);source=self.play(g,ADVANCE,target);self.assertTrue(g.state.entities[target].frozen);self.assertEqual(g.state.players[1].mana,48);self.assertEqual([o.card_id for o in g.state.pending_choice.options],[MAGE]);self.choose(g);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].zone,Zone.HAND);self.assertFalse(g.state.entities[event.target_id].frozen);self.assertEqual(g.state.entities[target].health,30)

    def test_snap_enemy_hero_freezes_then_gets_different_class_frost_spell(self):
        g=self.game((SNAP,),members=(DK_FROST,));target=self.hero(g,2);source=self.play(g,SNAP,target);self.assertTrue(g.state.entities[target].frozen);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,DK_FROST);self.assertEqual(g.state.players[1].mana,49);self.assertIsNone(g.state.pending_choice)

    def test_required_targets_and_snap_friendly_hero_or_minion_are_rejected_atomically(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)
        for minion in(False,True):
            with self.subTest(minion=minion):
                g=self.game((SNAP,),board=(YETI,));target=self.first(g,YETI,zone='board').id if minion else self.hero(g);saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,SNAP,target)
                self.assertEqual(g.snapshot(),saved)

    def test_photo_spell_healing_then_three_druid_and_dual_instances_exact_rng(self):
        g=self.game((TEST+'wound',PHOTO));target=self.hero(g);self.play(g,TEST+'wound',target);rng=random.Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,self.candidates(g.registry,PHOTO),3,replacement=True);source=self.play(g,PHOTO,target);result,=self.results(g,source);self.assertEqual((result.healing_kind,result.base_amount,result.healed),(HealingKind.SPELL.value,6,6));self.assertEqual(g.state.entities[target].health,26);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],list(expected));self.assertEqual(len({e.target_id for e in events}),3);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,47);self.assertTrue(all(CardClass.DRUID in g.registry.card(g.state.entities[e.target_id].card_id).metadata.classes for e in events))

    def test_photo_can_heal_enemy_hero_and_generates_three_despite_current_mage(self):
        g=self.game((TEST+'wound',PHOTO),members=(DUAL,));target=self.hero(g,2);self.play(g,TEST+'wound',target);source=self.play(g,PHOTO,target);self.assertEqual(g.state.entities[target].health,26);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],[DUAL]*3)

    def test_photo_full_hand_one_arrival_two_burns_after_native_heal(self):
        g=self.game((PHOTO,)+(YETI,)*9,members=(DRUID,));source=self.play(g,PHOTO,self.hero(g));events=self.created(g,source);burns=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(len(events),3);self.assertEqual(len(burns),2);self.assertTrue({e.target_id for e in burns}<={e.target_id for e in events});self.assertEqual(len(g.state.players[1].hand),10)

    def test_missing_context_and_pool_roll_back_original_damage_freeze_or_heal(self):
        for cid,context,pool in tuple((cid,None,True)for cid in ROOTS)+((ORB,CONTEXT,False),):
            with self.subTest(cid=cid,context=context,pool=pool):
                g=self.game((TEST+'wound',cid),context=context,pool=pool);target=self.hero(g,2);self.play(g,TEST+'wound',target);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid,target)
                self.assertEqual(g.snapshot(),saved)

    def test_real_unknown_eligible_contents_fail_before_rng_and_undo_first_effect(self):
        for cid,unknown in((ORB,'DINO_414'),(ADVANCE,'DINO_414'),(SNAP,'RLK_025'),(PHOTO,'CATA_136')):
            with self.subTest(cid=cid):
                g=self.game((TEST+'wound',cid),members=(*MEMBERS,unknown));target=self.hero(g,2);self.play(g,TEST+'wound',target);saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligibility validation'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,cid,target)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_first_spell_damage_wait_restore_clone_replay_bad_resume_then_discovery(self):
        g=self.game((ORB,),members=(MAGE,),mode='wait');target=self.hero(g,2);source=self.play(g,ORB,target);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].health,28);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.choose(other,'ok');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([o.card_id for o in g.state.pending_choice.options],[MAGE]);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.created(g,source)),1);self.portable(g)

    def test_late_random_acquisition_failure_undoes_healing_or_freeze_and_payment(self):
        for cid,members in((SNAP,(DK_FROST,)),(PHOTO,(DRUID,))):
            with self.subTest(cid=cid):
                g=self.game((TEST+'wound',cid),members=members,mode='fail');target=self.hero(g,2);self.play(g,TEST+'wound',target);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid,target)
                self.assertEqual(g.snapshot(),saved)

    def test_failed_discovery_selection_preserves_committed_first_damage_and_private_offer(self):
        g=self.game((ORB,),members=(MAGE,),mode='fail');target=self.hero(g,2);self.play(g,ORB,target);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.entities[target].health,28);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})

if __name__=='__main__':unittest.main()
