"""The actual owner-start qualifier stays with the prefix and the original gate stays native."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_owner_start_body_fragments import CARD,load_batch,register_assemble_owner_start_body_fragments
from hs_sim.cards.native_assemble_entry_cards import NURTURER,FLESH,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleRecipe,OWNER_START_PREFIX,printed_face
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import ChangeControl,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,KILL,MUTE,COPY,BOUNCE)

FLY,IMP,RUST,LOOT,BEETLE,BEAR,CURATOR,CAIRNE='CORE_UNG_809','CORE_EX1_319','CORE_SW_072','CORE_EX1_096','CORE_LOOT_413','CORE_AV_337','CORE_KAR_061','CORE_EX1_110'
P='fixture.assemble_owner_start_split.'
GIVE,WATCH,FAULT=(P+x for x in('give','watch','fault'))
CTX=GenerationContext('k402-real-owner-start-split-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k402.'+mode
    r.register_behavior(GIVE,lambda c:(ChangeControl(c.target_id,2),))
    r.register_card(CardDefinition(GIVE,GIVE,CardType.SPELL,on_play=GIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def fault(c):raise ResolutionError('deliberate owner-start split observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        if c.event.player_id!=c.player_id or c.event.amount!=3:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('armor_gained',WATCH),)))
    members=(CARD,CURATOR,CAIRNE)if mode=='doom_primary'else (IMP,CARD,RUST)if mode=='imp_start'else (
        LOOT,CARD,RUST)if mode=='flesh'else (FLY,CARD,RUST)
    if mode=='missing':r._assemble_templates.pop(CARD)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-owner-start-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleOwnerStartBodyTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07',hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=402,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid
    def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
    def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def choose(self,g,primary,secondary,half):
        cid=AssembleRecipe(primary,secondary,half).card_id;q=g.state.pending_choice
        option=next(x for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)));return cid

    def test_two_complete_originals_four_whole_primary_faces_and_separated_native_recipes(self):
        data=load_batch();rows={x['record']['id']:x for x in data['existing_dependencies']};r=build_registry();decl=data['reviewed_templates'][0]
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(data['official_observations']),4)
        for obs in data['official_observations']:
            row=rows[obs['card_id']]
            check_face(row['record'],obs['face'],obs['locale'],numeric_normalizations={'attack':0}if obs['card_id']==CARD else None)
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        self.assertEqual(r.behavior(decl['original_start_turn_id']).__defaults__[1],'own_turn_start')
        self.assertIsNone(r.behavior(decl['behavior_id']).__defaults__[1])
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_exact_original_trigger_bridge_reconstructs_all_other_complete_source_fields(self):
        r=build_registry();d=r.card(CARD);t=r.assemble_templates[CARD];new=printed_face(d,t.prefix,t.suffix,CARD)
        self.assertEqual(t.original_start_turn_id,d.triggers[0].behavior_id)
        self.assertEqual(new.triggers,(TriggerSpec('turn_started',OWNER_START_PREFIX+t.suffix.behavior_id),))
        self.assertEqual(replace(new,triggers=d.triggers),d)
        r._assemble_templates.pop(CARD)
        with self.assertRaises(ValueError):r.register_assemble_template(replace(t,original_start_turn_id=None))
        with self.assertRaisesRegex(ValueError,'complete original trigger identity'):
            r.register_assemble_template(replace(t,original_start_turn_id=r.card(IMP).battlecry))

    def test_bridge_rejects_wrong_timing_derived_identity_and_extra_original_triggers(self):
        r=build_registry();t=r.assemble_templates[CARD]
        for change in({'prefix':AssemblePrefix('battlecry')},{'original_start_turn_id':OWNER_START_PREFIX+t.suffix.behavior_id}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(t,**change)
        r._assemble_templates.pop(CARD);d=r.card(CARD)
        r._cards[CARD]=replace(d,triggers=(*d.triggers,TriggerSpec('card_drawn',t.original_start_turn_id)))
        with self.assertRaisesRegex(ValueError,'complete original trigger identity'):r.register_assemble_template(t)

    def test_normalized_no_change_and_derived_lookup_are_readonly(self):
        r=build_registry();before=r.fingerprint();ids=set(r.cards)
        self.assertEqual(recipe_options(r,CARD,CARD),())
        for half in('top','bottom'):
            face=r.card(AssembleRecipe(CARD,LOOT,half).card_id);self.assertEqual(face.cost,2)
        self.assertEqual(r.fingerprint(),before);self.assertEqual(set(r.cards),ids)

    def test_real_nurturer_borrowed_battlecry_destroys_immediately_without_old_start_gate(self):
        g=self.game(hand=(NURTURER,),board=(UNIT,),enemy=(UNIT,));self.play(g,NURTURER)
        cid=self.choose(g,FLY,CARD,'bottom');eid=self.play(g,cid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board)
        self.assertEqual(len(g.state.death_history),4);self.assertEqual((self.hp(g),self.hp(g,2)),(30,30))
        self.assertFalse(g.state.cast_history);self.portable(g)

    def test_real_nurturer_prefix_moves_imp_damage_only_to_its_owners_start(self):
        g=self.game(hand=(NURTURER,),mode='imp_start');self.play(g,NURTURER)
        cid=self.choose(g,IMP,CARD,'top');eid=self.play(g,cid);self.assertEqual(self.hp(g),30)
        g.apply(EndTurn(1));self.assertEqual(self.hp(g),30)
        g.apply(EndTurn(2));self.assertEqual(self.hp(g),27);self.assertEqual(g.state.entities[eid].health,2)

    def test_real_mismatch_new_start_draw_body_does_not_keep_original_destruction(self):
        g=self.game(hand=(MISMATCH,),mode='doom_primary');self.play(g,MISMATCH)
        cid=self.choose(g,CARD,CURATOR,'bottom');eid=self.play(g,cid)
        self.assertFalse(g.state.draw_history);self.next_turn(g)
        self.assertEqual(len([x for x in g.state.draw_history if x.player_id==1]),4);self.assertIn(eid,g.state.players[1].board)
        self.assertEqual(len(g.state.players[1].board),2);self.assertFalse(g.state.death_history)

    def test_original_and_new_native_start_preserve_one_wipe_and_later_deathrattle_children(self):
        for source in(CARD,AssembleRecipe(CARD,CARD,'top').card_id):
            with self.subTest(source=source):
                g=self.game(board=(source,UNIT,BEETLE),enemy=(BEAR,));g.apply(EndTurn(1))
                self.assertEqual(len(g.state.players[1].board),3);self.assertEqual(len(g.state.players[2].board),1)
                g.apply(EndTurn(2));self.assertFalse(g.state.players[1].board)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],['AV_337t','AV_337t'])
                self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.death_history),4)

    def test_same_ungated_body_works_on_natural_death_and_existing_end_boundary(self):
        death=AssembleRecipe(LOOT,CARD,'bottom').card_id
        g=self.game(board=(death,UNIT),enemy=(UNIT,),hand=(KILL,));self.play(g,KILL,g.state.players[1].board[0])
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board);self.assertFalse(g.state.draw_history)
        end=AssembleRecipe(CARD,'BE_152','top').card_id
        g=self.game(hand=(end,),board=(UNIT,),enemy=(UNIT,));self.play(g,end)
        self.assertEqual(len(g.state.players[1].board),2);g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board)

    def test_owner_start_uses_current_controller_after_control_change(self):
        cid=AssembleRecipe(BEETLE,CARD,'top').card_id;g=self.game(board=(cid,),hand=(GIVE,));eid=g.state.players[1].board[0]
        self.play(g,GIVE,eid);self.assertEqual((g.state.entities[eid].owner,g.state.entities[eid].controller),(1,2))
        g.apply(EndTurn(1));self.assertEqual((self.armor(g),self.armor(g,2)),(0,3))

    def test_current_copy_silence_and_return_reset_keep_the_new_start_face(self):
        cid=AssembleRecipe(BEETLE,CARD,'top').card_id;g=self.game(board=(cid,),hand=(COPY,MUTE,BOUNCE))
        eid=g.state.players[1].board[0];self.play(g,COPY,eid);self.play(g,MUTE,eid);self.next_turn(g)
        self.assertEqual(self.armor(g),3);self.play(g,BOUNCE,eid);self.play(g,cid);self.assertEqual(self.armor(g),3)
        self.next_turn(g);self.assertEqual(self.armor(g),9)

    def test_owner_start_wait_restore_failed_resume_and_private_views_keep_original_window(self):
        cid=AssembleRecipe(BEETLE,CARD,'top').card_id;g=self.game(board=(cid,WATCH),mode='wait');self.next_turn(g)
        self.assertEqual(self.armor(g),3);saved=self.portable(g);q=g.state.pending_choice;self.assertIsNotNone(q)
        with self.assertRaisesRegex(ResolutionError,'owner-start split observer fault'):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(self.armor(g),3);self.assertEqual(g.state.active_player,1);self.assertIsNone(g.state.pending_choice);self.portable(g)
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for field in('definition_sha256','source_guard','source_sha256','original_start_turn_id'):
                self.assertNotIn('"'+field+'"',visible)

    def test_missing_eligible_source_or_domain_rolls_back_original_payment_and_rng(self):
        for mode in('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(NURTURER,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,NURTURER)
                self.assertEqual(g.snapshot(),saved)

    def test_changed_complete_original_definition_is_rejected_before_template_installation(self):
        r=build_registry();r._assemble_templates.pop(CARD);r._cards[CARD]=replace(r.card(CARD),health=8)
        with self.assertRaisesRegex(TargetValidationError,'complete original minion'):register_assemble_owner_start_body_fragments(r)
        self.assertNotIn(CARD,r.assemble_templates)

    def test_reviewed_old_draw_amendment_preserves_every_prior_field_and_rejects_unpinned_or_frozen_changes(self):
        r=build_registry();current=r.assemble_templates[LOOT];amendment=load_batch()['profile_amendments'][0]
        prior=replace(current,suffix=replace(current.suffix,allowed_timings=('battlecry','deathrattle','end_turn')))
        legacy=asdict(prior)
        self.assertIsNone(legacy.pop('original_end_turn_id'))
        self.assertIsNone(legacy.pop('original_deathrattle_id'))
        self.assertIsNone(legacy['prefix'].pop('before_behavior_id'))
        self.assertEqual(canonical_digest(legacy),amendment['original_template_sha256'])
        self.assertEqual(current.suffix.allowed_timings,('battlecry','deathrattle','end_turn','start_turn','on_play'))
        saved=r.fingerprint();pin=canonical_digest(asdict(current))
        for timings,expected in((('start_turn',),'0'*64),(('start_turn',),pin),((),pin),([],pin),(('invented',),pin)):
            with self.subTest(timings=timings),self.assertRaises(ValueError):
                r.extend_assemble_suffix_timings(LOOT,timings,expected_template_sha256=expected)
            self.assertEqual(r.fingerprint(),saved)
        r.freeze()
        with self.assertRaisesRegex(ValueError,'frozen'):r.extend_assemble_suffix_timings(LOOT,('end_turn',),expected_template_sha256=pin)
        self.assertEqual(r.fingerprint(),saved)

    def test_real_deathrattle_source_keeps_reviewed_loot_start_option_and_executes_one_draw(self):
        g=self.game(hand=(FLESH,),mode='flesh');self.play(g,FLESH)
        cid=self.choose(g,LOOT,CARD,'top');eid=self.play(g,cid);self.assertFalse(g.state.draw_history)
        self.next_turn(g);own=[x for x in g.state.draw_history if x.player_id==1]
        self.assertEqual(len(own),2);self.assertIn(eid,g.state.players[1].board)


if __name__=='__main__':unittest.main()
