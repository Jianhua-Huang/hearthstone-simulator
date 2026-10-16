"""Sewer Swimmer native Prepare, paid Battlecry and actual Deathrattle activation."""
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p18_cards import SWIMMER,MATRIARCH,ROOTS,DEPENDENCIES,PREFIX,load_batch,register_simple_followup_p18_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Resource,Scenario,SelectChoice,TargetSpec,UseHandAction,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,GainArmor,GrantDeathrattle,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import HandActionSpec,LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p18.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry()
    if SWIMMER not in r.cards:register_simple_followup_p18_cards(r)
    r.register_behavior(TEST+'armor',lambda c:(GainArmor(c.state.players[c.player_id].hero_id,2),))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P18 deliberate pending failure')))
    def wait(c):return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.state.players[c.player_id].hero_id,3),)),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(TEST+'wait',wait)
    r.register_card(CardDefinition(TEST+'rattle','Native witness',CardType.MINION,attack=1,health=6,metadata=META,deathrattle=TEST+'armor'))
    r.register_card(CardDefinition(TEST+'wait_rattle','Waiting native witness',CardType.MINION,health=6,metadata=META,deathrattle=TEST+'wait'))
    r.register_card(CardDefinition(TEST+'dormant','Dormant witness',CardType.MINION,health=4,dormant_turns=2,metadata=META))
    for name,body in(('silence',lambda c:(Silence(c.target_id),)),('bounce',lambda c:(ReturnToHand(c.target_id),)),
        ('give',lambda c:(ChangeControl(c.target_id,2),)),('take',lambda c:(ChangeControl(c.target_id,1),)),
        ('grant',lambda c:(GrantDeathrattle(c.target_id,TEST+'armor',c.source_id),)),('kill',lambda c:(Destroy(c.target_id,c.source_id),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'summon',lambda c:(Summon(c.player_id,SWIMMER),))
    r.register_card(CardDefinition(TEST+'summon','Effect summon',CardType.SPELL,on_play=TEST+'summon',metadata=META))
    r.validate();return r

class SimpleFollowupP18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mana=40):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=mana,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=1818),self.r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,1,'hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def records(self,g):return[r for r in g.state.deathrattle_history if r.capture.card_id.startswith(TEST)]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','deathrattle_history','behavior_id','deathrattle_capture'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_two_rows_four_official_faces_and_full_metadata(self):
        d=load_batch();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['official_observations']['observations']),4);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['attack'],raw['health'],raw['card_set_id']))
        raw=d['cards'][0]['record'];c=self.r.card(SWIMMER);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=SWIMMER));self.assertEqual(c.metadata.classes,(CardClass.HUNTER,));self.assertEqual(c.metadata.tribes,('beast',));self.assertEqual(c.hand_actions,(HandActionSpec('prepare','prepare',1),));self.assertEqual(c.battlecry,PREFIX+'swimmer')

    def test_only_swimmer_added_complete_old_definitions_preserved_and_queen_stays_skipped(self):
        with patch('hs_sim.cards.simple_followup_p18_cards.register_simple_followup_p18_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if SWIMMER not in after.cards:register_simple_followup_p18_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(MATRIARCH in before.cards,MATRIARCH in after.cards);self.assertFalse(DEPENDENCIES);self.assertEqual(load_batch()['skipped'][0]['id'],MATRIARCH)

    def test_default_311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_paid_native_battlecry_activates_without_death_or_corpses(self):
        g=self.game((SWIMMER,),(TEST+'rattle',));target=self.first(g,TEST+'rattle').id;source=self.play(g,SWIMMER,target);row,=self.records(g)
        self.assertEqual(g.state.players[1].mana,36);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,3));self.assertEqual(self.armor(g),2)
        self.assertEqual((row.capture.origin,row.capture.death_id,row.capture.trigger_source_id),('effect',None,source));self.assertTrue(row.completed);self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertFalse(g.state.death_history);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.portable(g)

    def test_friendly_vanilla_is_legal_no_deathrattle_filter(self):
        g=self.game((SWIMMER,),(YETI,));self.play(g,SWIMMER,self.first(g,YETI).id);self.assertFalse(self.records(g));self.assertEqual(self.armor(g),0)

    def test_empty_board_allows_no_target_battlecry(self):
        g=self.game((SWIMMER,));self.play(g,SWIMMER);self.assertFalse(self.records(g));self.assertEqual(g.state.players[1].mana,36)

    def test_ally_present_requires_target_and_wrong_domains_rollback(self):
        for bad in('none','enemy','hero','hand','deck','dormant'):
            with self.subTest(bad=bad):
                g=self.game((SWIMMER,YETI),(YETI,TEST+'dormant'),(TEST+'rattle',));target={'none':None,'enemy':self.first(g,TEST+'rattle',2).id,'hero':g.state.players[1].hero_id,'hand':self.first(g,YETI,1,'hand').id,'deck':g.state.players[1].deck[0],'dormant':self.first(g,TEST+'dormant').id}[bad];saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,SWIMMER,target)
                self.assertEqual(g.snapshot(),saved)

    def test_silenced_target_is_legal_but_removed_rattle_does_not_execute(self):
        g=self.game((TEST+'silence',SWIMMER),(TEST+'rattle',));target=self.first(g,TEST+'rattle').id;self.play(g,TEST+'silence',target);self.play(g,SWIMMER,target);self.assertFalse(self.records(g));self.assertEqual(self.armor(g),0)

    def test_printed_and_granted_rattles_each_activate(self):
        g=self.game((TEST+'grant',SWIMMER),(TEST+'rattle',));target=self.first(g,TEST+'rattle').id;self.play(g,TEST+'grant',target);self.play(g,SWIMMER,target);self.assertEqual(self.armor(g),4);rows=self.records(g);self.assertEqual(len(rows),2);self.assertEqual(len({r.capture.ability.id for r in rows}),2);self.assertFalse(g.state.death_history)

    def test_real_four_family_source_repeats_battlecry_and_each_deathrattle(self):
        g=self.game((SWIMMER,),('TIME_064',TEST+'rattle'));self.play(g,SWIMMER,self.first(g,TEST+'rattle').id);self.assertEqual(self.armor(g),8);self.assertEqual(len(self.records(g)),4);self.assertTrue(all(r.completed for r in self.records(g)));self.assertEqual(g.state.players[1].mana,36);self.portable(g)

    def test_borrowed_friendly_target_uses_current_controller(self):
        g=self.game((TEST+'take',SWIMMER),(),(TEST+'rattle',));target=self.first(g,TEST+'rattle',2).id;self.play(g,TEST+'take',target);self.play(g,SWIMMER,target);self.assertEqual(self.armor(g,1),2);self.assertEqual(self.armor(g,2),0);self.assertEqual(g.state.entities[target].owner,2)

    def test_effect_summon_has_no_battlecry(self):
        g=self.game((TEST+'summon',),(TEST+'rattle',));self.play(g,TEST+'summon');self.assertFalse(self.records(g));self.assertEqual(self.armor(g),0);self.assertEqual(self.first(g,SWIMMER).attack,4)

    def test_prepare_investment_once_lock_and_no_battlecry_then_paid_zero(self):
        g=self.game((SWIMMER,),(TEST+'rattle',),mana=10);source=self.first(g,SWIMMER,1,'hand').id;g.apply(UseHandAction(1,source,'prepare'));e=g.state.entities[source];self.assertEqual(g.state.players[1].mana,7);self.assertEqual(e.preparation.mana_spent,3);self.assertFalse(self.records(g));self.assertFalse(g.state.play_history);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SWIMMER,self.first(g,TEST+'rattle').id)
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(IllegalAction):g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual(g.snapshot(),saved);self.portable(g);self.cycle(g);before=g.state.players[1].mana;self.play(g,SWIMMER,self.first(g,TEST+'rattle').id);self.assertEqual(g.state.players[1].mana,before);self.assertEqual(self.armor(g),2)

    def test_partial_prepare_spends_one_then_native_remaining_cost_two(self):
        g=self.game((SWIMMER,),(TEST+'rattle',),mana=1);eid=self.first(g,SWIMMER,1,'hand').id;g.apply(UseHandAction(1,eid,'prepare'));self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.entities[eid].preparation.mana_spent,1);self.cycle(g);before=g.state.players[1].mana;self.play(g,SWIMMER,self.first(g,TEST+'rattle').id);self.assertEqual(g.state.players[1].mana,before-2)

    def test_return_resets_preparation_and_reentry_pays_printed_cost(self):
        g=self.game((SWIMMER,TEST+'bounce'),(TEST+'rattle',));eid=self.first(g,SWIMMER,1,'hand').id;g.apply(UseHandAction(1,eid,'prepare'));self.cycle(g);self.play(g,SWIMMER,self.first(g,TEST+'rattle').id);self.play(g,TEST+'bounce',eid);self.assertIsNone(g.state.entities[eid].preparation);before=g.state.players[1].mana;self.play(g,SWIMMER,self.first(g,TEST+'rattle').id);self.assertEqual(g.state.players[1].mana,before-4);self.assertEqual(self.armor(g),4)

    def test_actual_waiting_rattle_restore_clone_replay_failed_resume_once_payment(self):
        g=self.game((SWIMMER,),(TEST+'wait_rattle',));self.play(g,SWIMMER,self.first(g,TEST+'wait_rattle').id);self.assertIsNotNone(g.state.pending_choice);row,=self.records(g);self.assertFalse(row.completed);self.assertEqual(g.state.players[1].mana,36);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),3);self.assertEqual(g.state.players[1].mana,36);self.assertTrue(self.records(g)[0].completed);self.assertFalse(g.state.death_history);self.portable(g)

if __name__=='__main__':unittest.main()

