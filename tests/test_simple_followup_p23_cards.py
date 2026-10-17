"""Schism's native target acceptance, post-grant current copy and original residence."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p23_cards import SCHISM,GRANT,COPY,ROOTS,DEPENDENCIES,PYROMANCER,load_batch,register_simple_followup_p23_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
TEST='p23.test.';YETI='CORE_CS2_182';KHADGAR='CORE_DAL_575';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p23_cards(r)
    def prep(c):return(Buff(c.target_id,1,1,c.source_id),Damage(c.target_id,2,c.source_id),GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id))
    for name,body in(('prep',prep),('generate',lambda c:(AddToHand(1,SCHISM,c.source_id),)),('counter',lambda c:(SetSecret(2,'EX1_287'),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,requires_target=name=='prep'))
    r.register_card(CardDefinition(TEST+'dormant','Dormant excluded',CardType.MINION,health=8,dormant_turns=2,metadata=META))
    r.register_card(CardDefinition(TEST+'elusive','Already Elusive',CardType.MINION,health=4,keywords=(Keyword.ELUSIVE,),metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P23 deliberate pending failure')))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==SCHISM
        def watch(c):
            target=c.event.target_id;extra=()
            if mode=='grow':extra=(Buff(target,1,1,c.source_id),)
            elif mode=='dead':extra=(Destroy(target,c.source_id),)
            elif mode=='return':extra=(ReturnToHand(target,to_owner=True),SummonFromZone(1,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
            elif mode=='control':extra=(ChangeControl(target,2),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'schism_buff',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual original grant reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('stats_changed',TEST+'watch',condition_id=TEST+'schism_buff'),)))
    r.validate();return r

class SimpleFollowupP23Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2323),r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,zone='hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def board(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','fragment_ids','BoardPresenceReference','MinionReference','deathrattle_inherited_from','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_five_raw_rows_six_faces_and_exact_priest_shadow_t1_t2(self):
        d=load_batch();self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),6);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_@.]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];card=self.r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=cid));self.assertEqual(card.metadata.classes,(CardClass.PRIEST,));self.assertEqual((card.cost,card.spell_school),(4,SpellSchool.SHADOW));self.assertEqual(card.metadata.collectible,cid==SCHISM)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['cardSetId']),(raw['dbf_id'],4,raw['card_set_id']))
                if cid==SCHISM:self.assertEqual(f['childIds'],[122876,122877])
        self.assertEqual((self.r.card(SCHISM).shatter.left_card_id,self.r.card(SCHISM).shatter.right_card_id),(GRANT,COPY));self.assertTrue(all(self.r.card(cid).targeting.relation=='friendly'for cid in ROOTS+DEPENDENCIES))

    def test_only_complete_three_definitions_added_old_definitions_and_evidence_preserved(self):
        with patch('hs_sim.cards.simple_followup_p23_cards.register_simple_followup_p23_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p23_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual('CATA_306e'in before.cards,'CATA_306e'in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_real_root_split_and_adjacent_fragments_recombine(self):
        g=self.game((SCHISM,YETI));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[GRANT,YETI,COPY]);self.assertFalse(g.state.play_history)
        g=self.game((GRANT,COPY));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SCHISM]);self.assertNotIn(Keyword.SHATTER,self.first(g,SCHISM,zone='hand').keywords)

    def test_whole_pays_once_buffs_original_then_copies_after_own_elusive(self):
        g=self.game((GRANT,COPY),(YETI,));target=self.first(g,YETI).id;source=self.play(g,SCHISM,target);board=self.board(g);self.assertEqual(len(board),2);self.assertTrue(all((e.card_id,e.attack,e.health,e.max_health)==(YETI,6,8,8)for e in board));self.assertTrue(all(Keyword.ELUSIVE in e.keywords for e in board));self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.cast_history),1);copy=next(e for e in board if e.id!=target);self.assertEqual(copy.origin_entity_id,target)
        cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.source.entity_id,cause.origin,cause.cast_card_id),(source,'spell_cast',SCHISM));self.portable(g)

    def test_grant_fragment_buffs_only_without_copy(self):
        g=self.game((GRANT,),(YETI,));target=self.first(g,YETI).id;self.play(g,GRANT,target);self.assertEqual(len(self.board(g)),1);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(6,8));self.assertIn(Keyword.ELUSIVE,g.state.entities[target].keywords);self.assertFalse(g.state.card_summon_history)

    def test_copy_fragment_copies_only_without_new_grant(self):
        g=self.game((COPY,),(YETI,));target=self.first(g,YETI).id;self.play(g,COPY,target);self.assertEqual(len(self.board(g)),2);self.assertTrue(all((e.attack,e.health)==(4,5)and Keyword.ELUSIVE not in e.keywords for e in self.board(g)))

    def test_all_three_require_friendly_eligible_minion_and_initial_elusive_is_rejected(self):
        for cid in ROOTS+DEPENDENCIES:
            for bad in('none','hero','enemy','hand','deck','dormant','elusive'):
                with self.subTest(cid=cid,bad=bad):
                    hand=(GRANT,COPY,YETI)if cid==SCHISM else(cid,YETI);g=self.game(hand,(YETI,TEST+'dormant',TEST+'elusive'),(YETI,));target={'none':None,'hero':g.state.players[1].hero_id,'enemy':self.first(g,YETI,2).id,'hand':self.first(g,YETI,zone='hand').id,'deck':g.state.players[1].deck[0],'dormant':self.first(g,TEST+'dormant').id,'elusive':self.first(g,TEST+'elusive').id}[bad];saved=g.snapshot()
                    with self.assertRaises(IllegalAction):self.play(g,cid,target)
                    self.assertEqual(g.snapshot(),saved)

    def test_current_copy_retains_preexisting_stats_damage_and_keywords(self):
        g=self.game((TEST+'prep',GRANT,COPY),(YETI,));target=self.first(g,YETI).id;self.play(g,TEST+'prep',target);self.play(g,SCHISM,target);board=self.board(g);self.assertEqual(len(board),2)
        for e in board:self.assertEqual((e.attack,e.health,e.max_health),(7,7,9));self.assertIn(Keyword.LIFESTEAL,e.keywords);self.assertIn(Keyword.ELUSIVE,e.keywords)
        self.assertTrue(set(a.id for a in board[0].abilities).isdisjoint(a.id for a in board[1].abilities));self.portable(g)

    def test_full_board_keeps_original_grants_but_no_copy_and_one_free_slot_delivers(self):
        for n in(6,7):
            with self.subTest(n=n):
                g=self.game((GRANT,COPY),(YETI,)*n);target=self.board(g)[0].id;self.play(g,SCHISM,target);self.assertEqual(len(self.board(g)),7);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(6,8));self.assertIn(Keyword.ELUSIVE,g.state.entities[target].keywords)

    def test_real_quantity_source_copies_current_material_for_each_delivery(self):
        g=self.game((GRANT,COPY),(KHADGAR,YETI));target=self.first(g,YETI).id;self.play(g,SCHISM,target);cards=[e for e in self.board(g)if e.card_id==YETI];self.assertEqual(len(cards),3);self.assertTrue(all((e.attack,e.health)==(6,8)and Keyword.ELUSIVE in e.keywords for e in cards));self.portable(g)

    def test_countered_whole_preserves_target_and_pays_once(self):
        g=self.game((TEST+'counter',GRANT,COPY),(YETI,));self.play(g,TEST+'counter');self.play(g,SCHISM,self.first(g,YETI).id);self.assertEqual(len(self.board(g)),1);self.assertEqual((self.first(g,YETI).attack,self.first(g,YETI).health),(4,5));self.assertNotIn(Keyword.ELUSIVE,self.first(g,YETI).keywords);self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(g.state.players[1].mana,46)

    def test_waiting_after_actual_buff_restores_and_copy_observes_later_current_growth(self):
        g=self.game((GRANT,COPY),(TEST+'watch',YETI),mode='grow');target=self.first(g,YETI).id;self.play(g,SCHISM,target);self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(Keyword.ELUSIVE,g.state.entities[target].keywords);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());cards=[e for e in self.board(g)if e.card_id==YETI];self.assertEqual(len(cards),2);self.assertTrue(all((e.attack,e.health)==(7,9)and Keyword.ELUSIVE in e.keywords for e in cards));self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_original_target_death_or_same_id_return_reentry_does_not_rebind_copy(self):
        for mode in('dead','return'):
            with self.subTest(mode=mode):
                g=self.game((GRANT,COPY),(TEST+'watch',YETI),mode=mode);target=self.first(g,YETI).id;before=g.state.entities[target].board_presence_id;self.play(g,SCHISM,target);self.choose(g);copies=[e for e in self.board(g)if e.origin_entity_id==target];self.assertFalse(copies)
                if mode=='return':self.assertNotEqual(g.state.entities[target].board_presence_id,before);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,5));self.assertNotIn(Keyword.ELUSIVE,g.state.entities[target].keywords)
                else:self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_same_residence_control_change_keeps_original_copy_target_for_original_caster(self):
        g=self.game((GRANT,COPY),(TEST+'watch',YETI),mode='control');target=self.first(g,YETI).id;self.play(g,SCHISM,target);self.choose(g);self.assertEqual(g.state.entities[target].controller,2);copies=[e for e in self.board(g)if e.origin_entity_id==target];self.assertEqual(len(copies),1);self.assertEqual((copies[0].attack,copies[0].health),(6,8));self.assertNotIn(Keyword.ELUSIVE,copies[0].keywords)

    def test_real_family_entry_triggers_existing_pyromancer_without_target_payload(self):
        g=self.game((TEST+'generate',YETI),(PYROMANCER,),(YETI,));self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,3);self.assertEqual([e.card_id for e in self.board(g)],[PYROMANCER]);self.assertEqual((self.first(g,PYROMANCER).attack,self.first(g,PYROMANCER).health),(4,3));self.assertNotIn(Keyword.ELUSIVE,self.first(g,PYROMANCER).keywords);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[GRANT,YETI,COPY]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1)

if __name__=='__main__':unittest.main()
