"""Printed death queries and Reborn on every original successful body."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from random import Random
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p15_cards import MANIFEST,RESUSCITATE,ROOTS,load_batch,register_simple_followup_p15_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,CostSpec,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,Freeze,GrantKeyword,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Silence,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
TEST='p15.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('undead',))

def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P15 registration')
    if not all(present):register_simple_followup_p15_cards(r)
    for name,cost,attack,health,tribes in(('one',1,1,3,('undead',)),('two',2,2,4,('undead',)),('three',3,3,5,('undead',)),
            ('high',8,4,6,('undead',)),('tie',8,2,8,('undead',)),('beast',10,6,8,('beast',)),('dual',5,5,6,('beast','undead')),('all',7,6,7,('all',))):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,cost=cost,attack=attack,health=health,metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition(TEST+'unknown','Unknown tribes',CardType.MINION,cost=9,attack=1,health=3))
    r.register_card(CardDefinition(TEST+'reborn','Printed Reborn',CardType.MINION,cost=2,attack=2,health=4,metadata=META,keywords=(Keyword.REBORN,)))
    r.register_behavior(TEST+'marker',lambda c:(AddToHand(c.player_id,TEST+'marker_spell',c.source_id),))
    r.register_behavior(TEST+'noop',lambda c:())
    r.register_card(CardDefinition(TEST+'marker_spell','Battlecry marker',CardType.SPELL,on_play=TEST+'noop',metadata=replace(META,tribes=())))
    r.register_card(CardDefinition(TEST+'cry','Printed battlecry',CardType.MINION,cost=1,attack=1,health=3,battlecry=TEST+'marker',metadata=META))
    def prep(c):return(Buff(c.target_id,7,7,c.source_id),GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id),Freeze(c.target_id),Damage(c.target_id,1,c.source_id),Destroy(c.target_id,c.source_id))
    def killall(c):return(DestroyBatch(tuple(i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id not in(TEST+'watch','CORE_DAL_575')),c.source_id),)
    def reenter(c):
        e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
    r.register_behavior(TEST+'reenter',reenter)
    bodies={
        'killall':killall,'kill':lambda c:(Destroy(c.target_id,c.source_id),),'prep':prep,
        'discount':lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),),
        'take':lambda c:(ChangeControl(c.target_id,1),),'give':lambda c:(ChangeControl(c.target_id,2),),
        'form':lambda c:(Transform(c.target_id,TEST+'two'),),'silence':lambda c:(Silence(c.target_id),),
        'undead':lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),
        'no_tribe':lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',()),c.source_id),),
        'fill5':lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(YETI),),SummonCause.capture(c))for _ in range(5)),
        'fill7':lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(YETI),),SummonCause.capture(c))for _ in range(7)),
    }
    for name,body in bodies.items():
        key=TEST+name;r.register_behavior(key,body)
        target=None if name in('killall','fill5','fill7')else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=replace(META,tribes=()),targeting=target))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P15 deliberate waiting failure')))
    def actual_res(c):return any(row.entity_id==c.event.target_id and row.source_id is not None and c.state.entities[row.source_id].card_id in ROOTS for row in c.state.resurrection_history)
    def watch(c):
        target=c.event.target_id
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
            ChoiceOption('bounce','Same ID new residence',(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,target))),
            ChoiceOption('form','Different face',(Transform(target,YETI),)),ChoiceOption('control','New controller',(ChangeControl(target,2),)),
            ChoiceOption('kill','Retire original',(Destroy(target,c.source_id),)),ChoiceOption('silence','Same body silenced',(Silence(target),)),
            ChoiceOption('nested','Unrelated same name',(SummonByCard(c.player_id,(SummonEntryMaterial(TEST+'one'),),SummonCause.capture(c)),)),
            ChoiceOption('next_tier','Make a new cost2 death',(Transform(target,TEST+'two'),Destroy(target,c.source_id))),
        ),c.source_id),)
    r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'actual_res',actual_res)
    r.register_card(CardDefinition(TEST+'watch','Watch first real resurrection',CardType.MINION,health=9,metadata=replace(META,tribes=()),limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'actual_res'),)))
    r.validate();return r

class SimpleFollowupP15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=1515),self.r)
    def entities(self,g,cid,p=1,zone='board'):return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,source,target));return source
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def killall(self,g):self.play(g,TEST+'killall')
    def arrivals(self,g):return[g.state.entities[row.entity_id]for row in g.state.resurrection_history]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','resurrection_quantity_bodies','resurrection_summon_history','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_two_full_raw_rows_four_official_faces_shadow_schools_and_metadata(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS);self.assertEqual(len(d['official_observations']['observations']),4)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['skipped'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256']);card=self.r.card(raw['id'])
            self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=raw['id']));self.assertEqual(card.spell_school,SpellSchool.SHADOW)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['manaCost'],f['cardTypeId'],f['cardSetId'],f['spellSchoolId']),(raw['dbf_id'],raw['cost'],raw['tags']['CARDTYPE'],raw['card_set_id'],6))

    def test_explicit_unregistered_baseline_retains_all_old_definitions_and_pending_roots(self):
        with patch('hs_sim.cards.simple_followup_p15_cards.register_simple_followup_p15_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p15_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS))
        self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards))

    def test_default_311_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_manifest_selects_highest_friendly_printed_undead_and_pays_once(self):
        g=self.game((TEST+'killall',MANIFEST),(TEST+'one',TEST+'high',TEST+'beast'));old=set(g.state.players[1].board);self.killall(g);source=self.play(g,MANIFEST)
        body,=self.arrivals(g);self.assertEqual(body.card_id,TEST+'high');self.assertNotIn(body.id,old);self.assertIn(body.origin_entity_id,old)
        self.assertEqual(g.state.players[1].mana,36);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),3);self.portable(g)

    def test_manifest_dual_and_all_printed_tribes_qualify(self):
        for cid in('dual','all'):
            with self.subTest(cid=cid):
                g=self.game((TEST+'killall',MANIFEST),(TEST+cid,TEST+'beast'));self.killall(g);self.play(g,MANIFEST)
                body,=self.arrivals(g);self.assertEqual(body.card_id,TEST+cid);self.portable(g)

    def test_manifest_printed_tribe_basis_does_not_guess_from_dynamic_grants_or_removals(self):
        g=self.game((TEST+'undead',TEST+'no_tribe',TEST+'killall',MANIFEST),(TEST+'beast',TEST+'high'))
        self.play(g,TEST+'undead',self.first(g,TEST+'beast').id);self.play(g,TEST+'no_tribe',self.first(g,TEST+'high').id);self.killall(g);self.play(g,MANIFEST)
        self.assertEqual(self.arrivals(g)[0].card_id,TEST+'high');self.portable(g)

    def test_manifest_uses_printed_extreme_even_if_local_cost_at_death_is_zero(self):
        g=self.game((TEST+'discount',TEST+'killall',MANIFEST),(TEST+'high',TEST+'three'));self.play(g,TEST+'discount',self.first(g,TEST+'high').id);self.killall(g);self.play(g,MANIFEST)
        self.assertEqual(self.arrivals(g)[0].card_id,TEST+'high')

    def test_manifest_tied_death_occurrences_each_keep_one_random_weight(self):
        g=self.game((TEST+'killall',MANIFEST),(TEST+'high',TEST+'high',TEST+'tie'));self.killall(g);deaths=list(g.state.death_history)
        rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(deaths);self.play(g,MANIFEST)
        self.assertEqual(g.state.resurrection_history[0].death_id,expected.id);self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_manifest_original_controller_at_death_and_new_recipient_owner(self):
        g=self.game((TEST+'give',TEST+'take',TEST+'killall',MANIFEST),(TEST+'one',),(TEST+'high',));own=self.first(g,TEST+'one').id;enemy=self.first(g,TEST+'high',2).id
        self.play(g,TEST+'give',own);self.play(g,TEST+'take',enemy);self.killall(g);self.play(g,MANIFEST);body,=self.arrivals(g)
        self.assertEqual((body.card_id,body.owner,body.controller,body.origin_entity_id),(TEST+'high',1,1,enemy));self.portable(g)

    def test_manifest_death_face_identity_and_history_are_not_consumed(self):
        g=self.game((TEST+'form',TEST+'killall',MANIFEST,MANIFEST),(TEST+'high',));original=self.first(g,TEST+'high').id
        self.play(g,TEST+'form',original);self.killall(g);self.play(g,MANIFEST);self.play(g,MANIFEST)
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'two']*2);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual([e.origin_entity_id for e in self.arrivals(g)],[original]*2);self.portable(g)

    def test_manifest_unknown_necessary_tribe_fails_without_cropping_candidate(self):
        g=self.game((TEST+'killall',MANIFEST),(TEST+'high',TEST+'unknown'));self.killall(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown candidate'):self.play(g,MANIFEST)
        self.assertEqual(g.snapshot(),saved)

    def test_both_empty_pools_and_full_boards_keep_no_rng_or_fatigue_policies(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));rng=g._rng.getstate();self.play(g,cid);self.assertFalse(g.state.resurrection_history);self.assertEqual(g._rng.getstate(),rng)
                self.assertEqual(g.state.players[1].fatigue,0)
                g=self.game((TEST+'killall',TEST+'fill7',cid),(TEST+'one',));self.killall(g);self.play(g,TEST+'fill7');rng=g._rng.getstate();self.play(g,cid)
                self.assertFalse(g.state.resurrection_history);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_resuscitate_cost_slots_in_order_and_every_body_gets_reborn(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'three',TEST+'one',TEST+'two'));self.killall(g);source=self.play(g,RESUSCITATE)
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'one',TEST+'two',TEST+'three']);self.assertTrue(all(Keyword.REBORN in e.keywords for e in self.arrivals(g)))
        self.assertEqual(g.state.players[1].mana,34);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_resuscitate_each_quantity_extra_has_own_reborn_and_original_source(self):
        g=self.game((TEST+'killall',RESUSCITATE),('CORE_DAL_575',TEST+'one',TEST+'two',TEST+'three'));self.killall(g);source=self.play(g,RESUSCITATE)
        bodies=self.arrivals(g);self.assertEqual([e.card_id for e in bodies],[TEST+'one']*2+[TEST+'two']*2+[TEST+'three']*2)
        self.assertTrue(all(Keyword.REBORN in e.keywords for e in bodies));self.assertEqual(len(g.state.resurrection_quantity_bodies),6)
        self.assertTrue(all(any(a.kind=='keyword'and a.keyword==Keyword.REBORN and a.source_id==source for a in e.abilities)for e in bodies));self.portable(g)

    def test_resuscitate_base_reconstruction_discards_local_buffs_injury_and_keywords(self):
        g=self.game((TEST+'prep',RESUSCITATE),(TEST+'one',));self.play(g,TEST+'prep',self.first(g,TEST+'one').id);self.play(g,RESUSCITATE);body,=self.arrivals(g)
        self.assertEqual((body.attack,body.health,body.max_health),(1,3,3));self.assertFalse(body.frozen);self.assertNotIn(Keyword.LIFESTEAL,body.keywords);self.assertIn(Keyword.REBORN,body.keywords);self.portable(g)

    def test_resuscitate_missing_slots_skip_and_partial_capacity_does_not_give_fake_reward(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'two',));self.killall(g);self.play(g,RESUSCITATE)
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'two']);self.assertIn(Keyword.REBORN,self.arrivals(g)[0].keywords)
        g=self.game((TEST+'killall',TEST+'fill5',RESUSCITATE),(TEST+'one',TEST+'two',TEST+'three'));self.killall(g);self.play(g,TEST+'fill5');self.play(g,RESUSCITATE)
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'one',TEST+'two']);self.assertTrue(all(Keyword.REBORN in e.keywords for e in self.arrivals(g)));self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_resuscitate_does_not_execute_printed_battlecry(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'cry',));self.killall(g);self.play(g,RESUSCITATE)
        self.assertFalse(self.entities(g,TEST+'marker_spell',zone='hand'));self.assertIn(Keyword.REBORN,self.arrivals(g)[0].keywords)

    def test_resuscitate_first_entry_wait_has_no_early_reborn_and_restores_remaining_slots(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'watch',TEST+'one',TEST+'two',TEST+'three'));self.killall(g);self.play(g,RESUSCITATE)
        self.assertEqual(len(self.arrivals(g)),1);self.assertNotIn(Keyword.REBORN,self.arrivals(g)[0].keywords);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'one',TEST+'two',TEST+'three']);self.assertTrue(all(Keyword.REBORN in e.keywords for e in self.arrivals(g)));self.portable(g)

    def test_resuscitate_stale_original_reentry_transform_control_or_death_never_gets_grant(self):
        for key in('bounce','form','control','kill'):
            with self.subTest(key=key):
                g=self.game((TEST+'killall',RESUSCITATE),(TEST+'watch',TEST+'one'));self.killall(g);self.play(g,RESUSCITATE);eid=g.state.resurrection_history[0].entity_id;self.choose(g,key)
                self.assertNotIn(Keyword.REBORN,g.state.entities[eid].keywords);self.portable(g)

    def test_resuscitate_silence_keeps_original_body_for_post_entry_grant(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'watch',TEST+'one'));self.killall(g);self.play(g,RESUSCITATE);eid=g.state.resurrection_history[0].entity_id
        self.choose(g,'silence');self.assertIn(Keyword.REBORN,g.state.entities[eid].keywords);self.portable(g)

    def test_resuscitate_unrelated_nested_same_name_does_not_receive_original_grant(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'watch',TEST+'one'));self.killall(g);self.play(g,RESUSCITATE);eid=g.state.resurrection_history[0].entity_id;self.choose(g,'nested')
        bodies=self.entities(g,TEST+'one');self.assertEqual(len(bodies),2);self.assertIn(Keyword.REBORN,g.state.entities[eid].keywords)
        self.assertTrue(all(Keyword.REBORN not in e.keywords for e in bodies if e.id!=eid));self.portable(g)

    def test_resuscitate_retired_primary_does_not_exclude_successful_quantity_extra(self):
        g=self.game((TEST+'killall',RESUSCITATE),('CORE_DAL_575',TEST+'watch',TEST+'one'));self.killall(g);self.play(g,RESUSCITATE);first=g.state.resurrection_history[0].entity_id;self.choose(g,'form')
        self.assertEqual(len(g.state.resurrection_history),2);second=g.state.resurrection_history[1].entity_id
        self.assertNotIn(Keyword.REBORN,g.state.entities[first].keywords);self.assertIn(Keyword.REBORN,g.state.entities[second].keywords);self.portable(g)

    def test_resuscitate_later_cost_slot_accepts_new_actual_death_from_earlier_reaction(self):
        g=self.game((TEST+'killall',RESUSCITATE),(TEST+'watch',TEST+'one'));self.killall(g);self.play(g,RESUSCITATE);self.choose(g,'next_tier')
        self.assertEqual([e.card_id for e in self.arrivals(g)],[TEST+'two',TEST+'two']);last=g.state.resurrection_history[-1]
        self.assertEqual(g.state.death_history[last.death_id-1].card_id,TEST+'two');self.assertIn(Keyword.REBORN,g.state.entities[last.entity_id].keywords);self.portable(g)

    def test_resuscitate_printed_and_granted_reborn_consume_as_one_normal_rebirth(self):
        g=self.game((TEST+'silence',TEST+'kill',TEST+'kill',TEST+'kill',RESUSCITATE),(TEST+'reborn',));original=self.first(g,TEST+'reborn').id
        self.play(g,TEST+'silence',original);self.play(g,TEST+'kill',original);self.play(g,RESUSCITATE);body=self.first(g,TEST+'reborn');self.assertIn(Keyword.REBORN,body.keywords)
        self.play(g,TEST+'kill',body.id);child=self.first(g,TEST+'reborn');self.assertEqual(child.health,1);self.assertNotIn(Keyword.REBORN,child.keywords)
        self.play(g,TEST+'kill',child.id);self.assertFalse(self.entities(g,TEST+'reborn'));self.portable(g)

if __name__=='__main__':unittest.main()
