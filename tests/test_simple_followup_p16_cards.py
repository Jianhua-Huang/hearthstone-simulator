"""Known noncombat emote Deathrattle retains actual native invocation facts."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p16_cards import GUARD,ROOTS,DEPENDENCIES,SKIPPED_DEPENDENCIES,PARENT,PREFIX,load_batch,register_simple_followup_p16_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Resource,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.targets import canonical_digest
TEST='p16.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry()
    if GUARD not in r.cards:register_simple_followup_p16_cards(r)
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'form':lambda c:(Transform(c.target_id,YETI),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'reborn':lambda c:(GrantKeyword(c.target_id,Keyword.REBORN,c.source_id),),
    }
    for name,body in scripts.items():
        key=TEST+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P16 deliberate waiting failure')))
    def watch(c):return(RequestChoice(1,(
        ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),)),
    ),c.source_id),)
    r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'guard_death',lambda c:c.state.entities[c.event.target_id].card_id==GUARD)
    r.register_card(CardDefinition(TEST+'watch','Prior death reaction',CardType.MINION,health=8,metadata=META,
        limited_triggers=(LimitedTriggerSpec('minion_died',TEST+'watch',condition_id=TEST+'guard_death'),)))
    r.validate();return r

class SimpleFollowupP16Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=1616),self.r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,1,'hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def records(self,g):return[r for r in g.state.deathrattle_history if r.capture.card_id==GUARD]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','deathrattle_history','behavior_id','deathrattle_capture'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_all_original_rows_ten_full_primary_faces_and_guard_metadata(self):
        d=load_batch();rows=d['cards']+d['skipped_dependencies']+d['evidence_only'];self.assertEqual(len(rows),5)
        self.assertEqual(len(d['official_observations']['observations']),10);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in rows+d['noncombat_text_review']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['tags']['CARDTYPE'],raw['card_set_id']))
                if raw['cost']is not None:self.assertEqual(f['manaCost'],raw['cost'])
        raw=d['cards'][0]['record'];self.assertEqual(self.r.card(GUARD).metadata,replace(metadata_from_record(raw),deck_identity=GUARD))

    def test_missing_dream_cost_and_class11_evidence_are_not_coerced_or_partially_registered(self):
        d=load_batch();self.assertEqual(DEPENDENCIES,());self.assertEqual(tuple(x['record']['id']for x in d['skipped_dependencies']),SKIPPED_DEPENDENCIES)
        for row in d['skipped_dependencies']:self.assertEqual(row['record']['tags']['CLASS'],11)
        dream=next(x['record']for x in d['skipped_dependencies']if x['record']['id']=='DREAM_04')
        self.assertIsNone(dream['cost']);self.assertNotIn('COST',dream['tags']);self.assertEqual(dream['tags']['SPELL_SCHOOL'],4)
        for o in d['official_observations']['observations']:
            if o['card_id']=='DREAM_04':self.assertEqual(o['face']['manaCost'],0)
            if o['card_id']==PARENT:self.assertEqual(sorted(o['face']['childIds']),[217,301,340,489,808])

    def test_only_guard_added_to_explicit_baseline_other_pending_presence_is_preserved(self):
        with patch('hs_sim.cards.simple_followup_p16_cards.register_simple_followup_p16_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if GUARD not in after.cards:register_simple_followup_p16_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards))
        for cid in(*SKIPPED_DEPENDENCIES,PARENT,'DREAM_02','DREAM_05','VAN_DREAM_01','CRED_23','CRED_35','ICCA08_029'):
            self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default_311_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_guard_paid_native_one_one_three_has_named_actual_deathrattle(self):
        g=self.game((GUARD,));source=self.play(g,GUARD);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health,g.state.players[1].mana),(1,3,39));self.assertEqual(self.r.card(GUARD).deathrattle,PREFIX+'noncombat_sorry_permission')
        self.assertTrue(any(a.kind=='deathrattle'and a.behavior_id==PREFIX+'noncombat_sorry_permission'for a in e.abilities));self.assertFalse(self.records(g));self.portable(g)

    def test_guard_natural_noop_deathrattle_records_identity_execution_and_completion(self):
        g=self.game((TEST+'kill',),(GUARD,));source=self.first(g,GUARD).id;rng=g._rng.getstate();self.play(g,TEST+'kill',source);row,=self.records(g)
        self.assertEqual((row.capture.origin,row.capture.carrier_id,row.capture.player_id,row.capture.ability.deathrattle_card_id),('death',source,1,GUARD))
        self.assertTrue(row.completed);self.assertFalse(row.interrupted);self.assertIsNotNone(row.execution_order);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.assertEqual(len(g.state.death_history),1);self.assertTrue(all(not p.player_effects for p in g.state.players.values()))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30);self.portable(g)

    def test_guard_control_at_death_governs_real_native_invocation(self):
        g=self.game((TEST+'give',TEST+'kill'),(GUARD,));source=self.first(g,GUARD).id;self.play(g,TEST+'give',source);self.play(g,TEST+'kill',source);row,=self.records(g)
        self.assertEqual((row.capture.player_id,g.state.death_history[0].owner,g.state.death_history[0].controller),(2,1,2));self.assertTrue(row.completed);self.portable(g)

    def test_guard_silence_or_transform_removes_original_activation(self):
        for key in('silence','form'):
            with self.subTest(key=key):
                g=self.game((TEST+key,TEST+'kill'),(GUARD,));source=self.first(g,GUARD).id;self.play(g,TEST+key,source);self.play(g,TEST+'kill',source)
                self.assertFalse(self.records(g));self.portable(g)

    def test_guard_native_death_query_distinguishes_silenced_actual_and_printed_rattle(self):
        g=self.game((TEST+'silence',TEST+'kill'),(GUARD,));source=self.first(g,GUARD).id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source)
        self.assertFalse(death_candidates(g.state,self.r,1,DeathQuery(has_deathrattle=True)))
        self.assertEqual([d.card_id for d in death_candidates(g.state,self.r,1,DeathQuery(has_deathrattle=True,deathrattle_basis='printed'))],[GUARD])

    def test_guard_native_effect_trigger_preserves_original_ability_without_fake_death(self):
        g=self.game((TEST+'trigger',),(GUARD,));source=self.first(g,GUARD).id;trigger=self.play(g,TEST+'trigger',source);row,=self.records(g)
        self.assertEqual((row.capture.origin,row.capture.death_id,row.capture.trigger_source_id),('effect',None,trigger));self.assertTrue(row.completed)
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_guard_native_repeated_empty_bodies_both_finish_with_independent_records(self):
        g=self.game((TEST+'kill',),('TIME_064',GUARD));source=self.first(g,GUARD).id;self.play(g,TEST+'kill',source);rows=self.records(g)
        self.assertEqual(len(rows),2);self.assertTrue(all(r.completed for r in rows));self.assertEqual([r.capture.repeat_index for r in rows],[1,2]);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_guard_reborn_reinstalls_printed_rattle_in_new_lifetime(self):
        g=self.game((TEST+'reborn',TEST+'kill',TEST+'kill'),(GUARD,));source=self.first(g,GUARD).id;self.play(g,TEST+'reborn',source);self.play(g,TEST+'kill',source)
        child=self.first(g,GUARD);self.assertNotEqual(child.id,source);self.assertEqual(child.health,1);self.assertEqual(len(self.records(g)),1)
        self.play(g,TEST+'kill',child.id);self.assertEqual(len(self.records(g)),2);self.assertTrue(all(r.completed for r in self.records(g)));self.portable(g)

    def test_guard_return_and_paid_reentry_retains_real_printed_rattle(self):
        g=self.game((TEST+'bounce',TEST+'kill'),(GUARD,));source=self.first(g,GUARD).id;self.play(g,TEST+'bounce',source);self.assertFalse(self.records(g));self.play(g,GUARD)
        self.play(g,TEST+'kill',source);self.assertEqual(len(self.records(g)),1);self.assertTrue(self.records(g)[0].completed);self.portable(g)

    def test_guard_pending_natural_rattle_restores_then_completes_once_after_failure(self):
        g=self.game((TEST+'kill',),(TEST+'watch',GUARD));source=self.first(g,GUARD).id;self.play(g,TEST+'kill',source)
        row,=self.records(g);self.assertFalse(row.completed);self.assertIsNone(row.execution_order);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(self.records(g)[0].completed);self.assertEqual(len(self.records(g)),1);self.portable(g)

if __name__=='__main__':unittest.main()
