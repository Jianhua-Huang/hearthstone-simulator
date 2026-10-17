"""Wildwood's real family, post-summon grant, finite attachment and native activations."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p21_cards import CIRCLE,SUMMON,GRANT,TREANT,ROOTS,DEPENDENCIES,PYROMANCER,PREFIX,load_batch,register_simple_followup_p21_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,CopyMinion,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p21.test.';YETI='CORE_CS2_182';KHADGAR='CORE_DAL_575';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p21_cards(r)
    for name,body in(('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),)),
        ('bounce',lambda c:(ReturnToHand(c.target_id,to_owner=True),)),('steal',lambda c:(ChangeControl(c.target_id,2),)),
        ('copy',lambda c:(CopyMinion(c.target_id,c.player_id),)),('base_copy',lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)),
        ('trigger',lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)),('generate',lambda c:(AddToHand(1,CIRCLE,c.source_id),)),
        ('counter',lambda c:(SetSecret(2,'EX1_287'),))):
        key=TEST+name;r.register_behavior(key,body);kwargs={}if name in('generate','counter')else{'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,**kwargs))
    r.register_card(CardDefinition(TEST+'dormant','Dormant excluded',CardType.MINION,health=8,dormant_turns=2,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P21 deliberate pending failure')))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id==TREANT
        def watch(c):
            extra=(Summon(1,YETI),)if mode=='add'else(ReturnToHand(c.event.target_id,to_owner=True),)if mode=='depart'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'treant_entry',eligible)
        r.register_card(CardDefinition(TEST+'watch','First actual Treant entry reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'treant_entry'),)))
    r.validate();return r

class SimpleFollowupP21Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2121),r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,zone='hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def board(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board]
    def grants(self,g,eid):return[a for a in g.state.entities[eid].abilities if a.kind=='deathrattle'and a.behavior_id==PREFIX+'rattle']
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','fragment_ids','deathrattle_history','card_summon_history','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_six_raw_rows_eight_faces_and_exact_nature_druid_treant_metadata(self):
        d=load_batch();self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']),6);self.assertEqual(len(d['official_observations']['observations']),8);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_@.]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];self.assertEqual(canonical_digest(raw),row['record_sha256']);card=self.r.card(cid);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=cid));self.assertEqual(card.metadata.classes,(CardClass.DRUID,));self.assertEqual(card.metadata.collectible,cid==CIRCLE)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['card_set_id']))
                if cid==CIRCLE:self.assertEqual(f['childIds'],[122972,122973,126886])
            if cid!=TREANT:self.assertEqual(card.spell_school,SpellSchool.NATURE);self.assertEqual(card.cost,4)
        token=self.r.card(TREANT);self.assertEqual((token.cost,token.attack,token.health),(1,2,2));self.assertIsNone(token.deathrattle);self.assertEqual(token.metadata.tribes,());self.assertEqual(token.metadata.subtypes,());self.assertIsNone(token.spell_school);self.assertEqual(d['dependencies'][-1]['record']['tags']['2831'],1)

    def test_only_complete_four_definitions_added_old_definitions_and_evidence_preserved(self):
        with patch('hs_sim.cards.simple_followup_p21_cards.register_simple_followup_p21_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p21_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual('CATA_134e'in before.cards,'CATA_134e'in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_real_root_splits_and_adjacent_fragments_recombine(self):
        g=self.game((CIRCLE,YETI));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SUMMON,YETI,GRANT]);self.assertFalse(g.state.play_history)
        g=self.game((SUMMON,GRANT));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[CIRCLE]);self.assertNotIn(Keyword.SHATTER,self.first(g,CIRCLE,zone='hand').keywords)

    def test_whole_pays_once_summons_two_exact_bodies_then_grants_each_current_friend_once(self):
        g=self.game((SUMMON,GRANT),(YETI,));source=self.play(g,CIRCLE);board=self.board(g);self.assertEqual([e.card_id for e in board],[YETI,TREANT,TREANT]);self.assertTrue(all(len(self.grants(g,e.id))==1 for e in board));self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.cast_history),1)
        for e in board:
            a,=self.grants(g,e.id);self.assertEqual((a.source_id,a.deathrattle_grant_card_id,a.origin),(source,CIRCLE,'granted'))
        for row in g.state.card_summon_history:self.assertEqual((row.request.cause.source.entity_id,row.request.cause.origin,row.request.cause.cast_card_id),(source,'spell_cast',CIRCLE))
        self.portable(g)

    def test_summon_fragment_has_no_grant_or_printed_token_deathrattle(self):
        g=self.game((SUMMON,TEST+'kill'));self.play(g,SUMMON);board=self.board(g);self.assertEqual(len(board),2);self.assertTrue(all((e.card_id,e.attack,e.health)==(TREANT,2,2)for e in board));self.assertTrue(all(not self.grants(g,e.id)for e in board));self.play(g,TEST+'kill',board[0].id);self.assertEqual(len(self.board(g)),1)

    def test_grant_fragment_summons_nothing_until_real_death_then_newborn_is_vanilla(self):
        g=self.game((GRANT,TEST+'kill',TEST+'kill'),(YETI,));target=self.first(g,YETI).id;source=self.play(g,GRANT);self.assertEqual(len(self.board(g)),1);self.play(g,TEST+'kill',target);token=self.first(g,TREANT);self.assertFalse(self.grants(g,token.id));self.assertEqual((token.attack,token.health),(2,2));row,=g.state.deathrattle_history;self.assertEqual((row.capture.origin,row.capture.ability.deathrattle_grant_card_id),('death',GRANT));self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,target);self.assertNotEqual(target,source);self.play(g,TEST+'kill',token.id);self.assertFalse(self.board(g));self.portable(g)

    def test_whole_granted_treant_death_produces_one_new_body_without_recursive_grant(self):
        g=self.game((SUMMON,GRANT,TEST+'kill'));self.play(g,CIRCLE);old=self.board(g);target=old[0].id;self.play(g,TEST+'kill',target);self.assertEqual(len(self.board(g)),2);fresh=[e for e in self.board(g)if e.id not in{v.id for v in old}];self.assertEqual(len(fresh),1);self.assertFalse(self.grants(g,fresh[0].id));self.assertTrue(self.grants(g,old[1].id))

    def test_grant_ignores_enemy_hand_deck_and_dormant(self):
        g=self.game((GRANT,YETI),(YETI,TEST+'dormant'),(YETI,));self.play(g,GRANT);self.assertTrue(self.grants(g,self.first(g,YETI).id));self.assertFalse(self.grants(g,self.first(g,TEST+'dormant').id));self.assertFalse(self.grants(g,self.first(g,YETI,2).id));self.assertFalse(self.grants(g,self.first(g,YETI,zone='hand').id));self.assertFalse(self.grants(g,self.first(g,YETI,zone='deck').id))

    def test_empty_grant_has_no_persistent_aura_and_later_token_is_not_rewarded(self):
        g=self.game((GRANT,YETI,SUMMON));self.play(g,GRANT);self.assertFalse(g.state.players[1].player_effects);self.play(g,SUMMON);self.assertEqual(len(self.board(g)),2);self.assertTrue(all(not self.grants(g,e.id)for e in self.board(g)))

    def test_full_board_still_grants_existing_friends_and_partial_capacity_grants_actual_summon(self):
        for n in(6,7):
            with self.subTest(n=n):
                g=self.game((SUMMON,GRANT),(YETI,)*n);self.play(g,CIRCLE);self.assertEqual(len(self.board(g)),7);self.assertEqual(sum(e.card_id==TREANT for e in self.board(g)),7-n);self.assertTrue(all(len(self.grants(g,e.id))==1 for e in self.board(g)))

    def test_real_quantity_source_all_four_actual_summons_receive_grant_and_newborns_do_not(self):
        g=self.game((SUMMON,GRANT,TEST+'kill'),(KHADGAR,));self.play(g,CIRCLE);tokens=[e for e in self.board(g)if e.card_id==TREANT];self.assertEqual(len(tokens),4);self.assertTrue(all(len(self.grants(g,e.id))==1 for e in self.board(g)));self.play(g,TEST+'kill',tokens[0].id);fresh=[e for e in self.board(g)if e.card_id==TREANT and e.id not in{v.id for v in tokens}];self.assertEqual(len(fresh),2);self.assertTrue(all(not self.grants(g,e.id)for e in fresh));self.portable(g)

    def test_live_effect_trigger_has_no_fake_death_uses_carrier_and_right_position(self):
        g=self.game((GRANT,TEST+'trigger'),(YETI,YETI));target=self.board(g)[0].id;self.play(g,GRANT);trigger=self.play(g,TEST+'trigger',target);board=self.board(g);self.assertEqual([e.card_id for e in board],[YETI,TREANT,YETI]);self.assertFalse(g.state.death_history);row,=g.state.deathrattle_history;self.assertEqual((row.capture.origin,row.capture.death_id,row.capture.trigger_source_id),('effect',None,trigger));self.assertFalse(self.grants(g,board[1].id));self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,target);self.portable(g)

    def test_multiple_actual_grants_are_distinct_and_each_triggers_one_body(self):
        g=self.game((GRANT,GRANT,TEST+'kill'),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,GRANT);self.assertEqual(len({a.id for a in self.grants(g,target)}),2);self.play(g,TEST+'kill',target);self.assertEqual([e.card_id for e in self.board(g)],[TREANT,TREANT]);self.assertEqual(len(g.state.deathrattle_history),2)

    def test_silence_and_normal_return_remove_grant(self):
        for name in('silence','bounce'):
            with self.subTest(name=name):
                g=self.game((GRANT,TEST+name,TEST+'kill'),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+name,target)
                if name=='bounce':self.play(g,YETI)
                self.assertFalse(self.grants(g,target));self.play(g,TEST+'kill',target);self.assertFalse(self.board(g))

    def test_controlled_carrier_natural_death_summons_for_new_controller(self):
        g=self.game((GRANT,TEST+'steal',TEST+'kill'),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+'steal',target);self.play(g,TEST+'kill',target);self.assertFalse(self.board(g));self.assertEqual([e.card_id for e in self.board(g,2)],[TREANT]);self.assertEqual(g.state.card_summon_history[-1].request.cause.player_id,2)

    def test_current_copy_retains_grant_with_new_identity_base_copy_does_not(self):
        for name,expected in(('copy',1),('base_copy',0)):
            with self.subTest(name=name):
                g=self.game((GRANT,TEST+name),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+name,target);copy=next(e for e in self.board(g)if e.id!=target);self.assertEqual(len(self.grants(g,copy.id)),expected)
                if expected:self.assertNotEqual(self.grants(g,copy.id)[0].id,self.grants(g,target)[0].id)

    def test_countered_real_spell_pays_but_neither_summons_nor_grants(self):
        g=self.game((TEST+'counter',SUMMON,GRANT),(YETI,));self.play(g,TEST+'counter');self.play(g,CIRCLE);self.assertEqual([e.card_id for e in self.board(g)],[YETI]);self.assertFalse(self.grants(g,self.first(g,YETI).id));self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(g.state.players[1].mana,46)

    def test_whole_waiting_first_summon_reaction_addition_is_in_late_grant(self):
        g=self.game((SUMMON,GRANT),(TEST+'watch',),mode='add');self.play(g,CIRCLE);self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(not self.grants(g,e.id)for e in self.board(g)));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([e.card_id for e in self.board(g)],[TEST+'watch',TREANT,YETI,TREANT]);self.assertTrue(all(len(self.grants(g,e.id))==1 for e in self.board(g)));self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_whole_waiting_departed_first_token_not_granted_but_later_success_is(self):
        g=self.game((SUMMON,GRANT),(TEST+'watch',),mode='depart');self.play(g,CIRCLE);self.choose(g);self.assertEqual([e.card_id for e in self.board(g)],[TEST+'watch',TREANT]);self.assertTrue(all(len(self.grants(g,e.id))==1 for e in self.board(g)));held=self.first(g,TREANT,zone='hand');self.assertFalse(self.grants(g,held.id))

    def test_live_deathrattle_summon_wait_restores_and_new_body_stays_ungranted(self):
        g=self.game((GRANT,TEST+'trigger'),(TEST+'watch',YETI),mode='wait');target=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,TEST+'trigger',target);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(self.grants(g,self.first(g,TREANT).id));self.assertFalse(g.state.death_history);self.assertTrue(g.state.deathrattle_history[0].completed);self.portable(g)

    def test_real_family_entry_triggers_existing_pyromancer_without_playing_payload(self):
        g=self.game((TEST+'generate',YETI),(PYROMANCER,),(YETI,));self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,3);self.assertEqual([e.card_id for e in self.board(g)],[PYROMANCER]);self.assertFalse(self.grants(g,self.first(g,PYROMANCER).id));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SUMMON,YETI,GRANT]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1)

if __name__=='__main__':unittest.main()
