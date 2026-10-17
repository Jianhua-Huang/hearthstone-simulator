"""Flight Maneuvers complete real family and finite post-summon Attack/shield grants."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p22_cards import FLIGHT,SUMMON,GRANT,DRAKE,ROOTS,DEPENDENCIES,PYROMANCER,load_batch,register_simple_followup_p22_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,CopyMinion,Damage,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.targets import canonical_digest
TEST='p22.test.';YETI='CORE_CS2_182';KHADGAR='CORE_DAL_575';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p22_cards(r)
    for name,body in(('damage',lambda c:(Damage(c.target_id,1,c.source_id),)),('silence',lambda c:(Silence(c.target_id),)),
        ('bounce',lambda c:(ReturnToHand(c.target_id,to_owner=True),)),('copy',lambda c:(CopyMinion(c.target_id,1),)),
        ('base_copy',lambda c:(CopyMinion(c.target_id,1,mode='base'),)),('generate',lambda c:(AddToHand(1,FLIGHT,c.source_id),)),
        ('counter',lambda c:(SetSecret(2,'EX1_287'),))):
        key=TEST+name;r.register_behavior(key,body);kwargs={}if name in('generate','counter')else{'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,**kwargs))
    r.register_card(CardDefinition(TEST+'dormant','Dormant excluded',CardType.MINION,health=8,dormant_turns=2,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P22 deliberate pending failure')))
    if mode:
        def eligible(c):
            if mode=='grant_fail':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in(FLIGHT,GRANT)
            return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id==DRAKE
        def watch(c):
            if mode=='grant_fail':return(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)
            extra=(Summon(1,YETI),)if mode=='add'else(ReturnToHand(c.event.target_id,to_owner=True),)if mode=='depart'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual effect boundary observer',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('stats_changed'if mode=='grant_fail'else'minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP22Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2222),r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,zone='hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def board(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board]
    def shield(self,g,eid):return Keyword.DIVINE_SHIELD in g.state.entities[eid].keywords
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','fragment_ids','MinionReference','card_summon_history','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_six_raw_rows_eight_faces_and_exact_holy_paladin_dragon_metadata(self):
        d=load_batch();self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']),6);self.assertEqual(len(d['official_observations']['observations']),8);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_@.]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];card=self.r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=cid));self.assertEqual(card.metadata.classes,(CardClass.PALADIN,));self.assertEqual(card.metadata.collectible,cid==FLIGHT)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['card_set_id']))
                if cid==FLIGHT:self.assertEqual(f['childIds'],[123141,123142,123140])
            if cid!=DRAKE:self.assertEqual((card.cost,card.spell_school),(4,SpellSchool.HOLY))
        card=self.r.card(DRAKE);self.assertEqual((card.cost,card.attack,card.health,card.metadata.tribes),(3,4,2,('dragon',)));self.assertFalse(card.keywords);self.assertIsNone(card.spell_school)

    def test_only_four_definitions_added_all_old_definitions_and_evidence_preserved(self):
        with patch('hs_sim.cards.simple_followup_p22_cards.register_simple_followup_p22_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p22_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual('CATA_479e'in before.cards,'CATA_479e'in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_real_root_split_and_adjacent_fragments_recombine(self):
        g=self.game((FLIGHT,YETI));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SUMMON,YETI,GRANT]);self.assertFalse(g.state.play_history)
        g=self.game((SUMMON,GRANT));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[FLIGHT]);self.assertNotIn(Keyword.SHATTER,self.first(g,FLIGHT,zone='hand').keywords)

    def test_whole_pays_once_two_real_drakes_then_grants_attack_and_shield_once(self):
        g=self.game((SUMMON,GRANT),(YETI,));source=self.play(g,FLIGHT);board=self.board(g);self.assertEqual([e.card_id for e in board],[YETI,DRAKE,DRAKE]);self.assertTrue(all((e.attack,e.health)==(5,5 if e.card_id==YETI else 2)for e in board));self.assertTrue(all(self.shield(g,e.id)for e in board));self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.cast_history),1)
        for e in board:
            self.assertTrue(any(a.kind=='keyword'and a.keyword==Keyword.DIVINE_SHIELD and a.source_id==source for a in e.abilities));self.assertTrue(any(a.attack==1 and a.source_id==source for a in e.enchantments))
        for row in g.state.card_summon_history:self.assertEqual((row.request.cause.source.entity_id,row.request.cause.origin,row.request.cause.cast_card_id),(source,'spell_cast',FLIGHT))
        self.portable(g)

    def test_summon_fragment_creates_only_plain_four_two_drakes(self):
        g=self.game((SUMMON,));self.play(g,SUMMON);self.assertEqual(len(self.board(g)),2);self.assertTrue(all((e.card_id,e.attack,e.health)==(DRAKE,4,2)for e in self.board(g)));self.assertTrue(all(not self.shield(g,e.id)for e in self.board(g)))

    def test_grant_fragment_summons_nothing_affects_only_current_friendly_board(self):
        g=self.game((GRANT,YETI),(YETI,TEST+'dormant'),(YETI,),enemy_hand=(YETI,));self.play(g,GRANT);target=self.first(g,YETI);self.assertEqual(target.attack,5);self.assertTrue(self.shield(g,target.id));self.assertEqual(len(self.board(g)),2)
        for e in(self.first(g,TEST+'dormant'),self.first(g,YETI,2),self.first(g,YETI,zone='hand'),self.first(g,YETI,zone='deck'),self.first(g,YETI,2,'hand')):self.assertEqual(e.attack,4 if e.card_id==YETI else 0);self.assertFalse(self.shield(g,e.id))

    def test_empty_grant_has_no_aura_and_later_summons_receive_nothing(self):
        g=self.game((GRANT,YETI,SUMMON));self.play(g,GRANT);self.assertFalse(g.state.players[1].player_effects);self.play(g,SUMMON);self.assertTrue(all(e.attack==4 and not self.shield(g,e.id)for e in self.board(g)))

    def test_whole_later_summon_fragment_creates_unbuffed_drakes(self):
        g=self.game((SUMMON,GRANT,SUMMON));self.play(g,FLIGHT);old={e.id for e in self.board(g)};self.play(g,SUMMON);self.assertEqual(len(self.board(g)),4)
        for e in self.board(g):self.assertEqual((e.attack,self.shield(g,e.id)),(5,True)if e.id in old else(4,False))

    def test_full_board_still_buffs_and_partial_capacity_only_real_summon(self):
        for n in(6,7):
            with self.subTest(n=n):
                g=self.game((SUMMON,GRANT),(YETI,)*n);self.play(g,FLIGHT);self.assertEqual(len(self.board(g)),7);self.assertEqual(sum(e.card_id==DRAKE for e in self.board(g)),7-n);self.assertTrue(all(e.attack==5 and self.shield(g,e.id)for e in self.board(g)))

    def test_real_quantity_source_four_actual_drakes_receive_finite_grants(self):
        g=self.game((SUMMON,GRANT),(KHADGAR,));self.play(g,FLIGHT);tokens=[e for e in self.board(g)if e.card_id==DRAKE];self.assertEqual(len(tokens),4);self.assertTrue(all((e.attack,e.health)==(5,2)and self.shield(g,e.id)for e in tokens));self.assertTrue(self.shield(g,self.first(g,KHADGAR).id));self.portable(g)

    def test_multiple_grants_stack_attack_but_shield_is_consumed_as_one_protection(self):
        g=self.game((GRANT,GRANT,TEST+'damage',TEST+'damage'),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,GRANT);self.assertEqual(g.state.entities[target].attack,6);self.play(g,TEST+'damage',target);self.assertFalse(self.shield(g,target));self.assertEqual(g.state.entities[target].health,5);self.play(g,TEST+'damage',target);self.assertEqual(g.state.entities[target].health,4)

    def test_single_granted_shield_blocks_one_hit_without_health_buff(self):
        g=self.game((SUMMON,GRANT,TEST+'damage',TEST+'damage'));self.play(g,FLIGHT);target=self.first(g,DRAKE).id;self.play(g,TEST+'damage',target);self.assertEqual(g.state.entities[target].health,2);self.assertFalse(self.shield(g,target));self.play(g,TEST+'damage',target);self.assertEqual(g.state.entities[target].health,1);self.assertEqual(g.state.entities[target].attack,5)

    def test_silence_and_return_reset_attack_and_shield(self):
        for name in('silence','bounce'):
            with self.subTest(name=name):
                g=self.game((GRANT,TEST+name),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+name,target)
                if name=='bounce':self.play(g,YETI)
                self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(4,5));self.assertFalse(self.shield(g,target))

    def test_current_copy_keeps_removable_grants_base_copy_does_not(self):
        for name,expected in(('copy',(5,True)),('base_copy',(4,False))):
            with self.subTest(name=name):
                g=self.game((GRANT,TEST+name),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+name,target);copy=next(e for e in self.board(g)if e.id!=target);self.assertEqual((copy.attack,self.shield(g,copy.id)),expected)

    def test_countered_whole_pays_but_neither_summons_nor_grants(self):
        g=self.game((TEST+'counter',SUMMON,GRANT),(YETI,));self.play(g,TEST+'counter');self.play(g,FLIGHT);self.assertEqual([e.card_id for e in self.board(g)],[YETI]);self.assertEqual(self.first(g,YETI).attack,4);self.assertFalse(self.shield(g,self.first(g,YETI).id));self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(g.state.players[1].mana,46)

    def test_waiting_first_summon_reaction_new_body_receives_late_grant_after_resume(self):
        g=self.game((SUMMON,GRANT),(TEST+'watch',),mode='add');self.play(g,FLIGHT);self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(not self.shield(g,e.id)for e in self.board(g)));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([e.card_id for e in self.board(g)],[TEST+'watch',DRAKE,YETI,DRAKE]);self.assertTrue(all(self.shield(g,e.id)for e in self.board(g)));self.assertTrue(all(e.attack==5 for e in self.board(g)if e.card_id in(DRAKE,YETI)));self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_departed_first_summon_excluded_from_late_captured_recipients(self):
        g=self.game((SUMMON,GRANT),(TEST+'watch',),mode='depart');self.play(g,FLIGHT);self.choose(g);self.assertEqual([e.card_id for e in self.board(g)],[TEST+'watch',DRAKE]);held=self.first(g,DRAKE,zone='hand');self.assertEqual(held.attack,4);self.assertFalse(self.shield(g,held.id));self.assertEqual(self.first(g,DRAKE).attack,5);self.assertTrue(self.shield(g,self.first(g,DRAKE).id))

    def test_late_grant_reaction_failure_rolls_back_entire_paid_action(self):
        g=self.game((SUMMON,GRANT),(TEST+'watch',YETI),mode='grant_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,FLIGHT)
        self.assertEqual(g.snapshot(),saved)

    def test_real_family_entry_triggers_existing_pyromancer_without_playing_payload(self):
        g=self.game((TEST+'generate',YETI),(PYROMANCER,),(YETI,));self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,3);self.assertEqual([e.card_id for e in self.board(g)],[PYROMANCER]);self.assertEqual(self.first(g,PYROMANCER).attack,4);self.assertFalse(self.shield(g,self.first(g,PYROMANCER).id));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SUMMON,YETI,GRANT]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1)

if __name__=='__main__':unittest.main()
