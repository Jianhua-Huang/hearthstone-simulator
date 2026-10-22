"""Actual prefix material controls native Colossal entry and all saved identities."""
from dataclasses import asdict, replace, FrozenInstanceError
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_colossal_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_colossal import AssembleColossalSource
from hs_sim.engine.assemble_faces import AssembleRecipe, printed_face
from hs_sim.engine.effects import ChoiceOption, CopyMinion, Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AppendageSpec, CardClass, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture, PING, HEAL, PAIN
from test_assemble_attack_finished_followups import DUMMY
from test_assemble_card_play_followups import META, N, KILL, MUTE, COIN, WAR, CURATOR, LOOT
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLE_POOL

BLOOD,VULCANOS=cards.SOURCES
P='k428.'
COPY,COPY_BASE,PURGE,BOUNCE,WATCH,FAIL,UNKNOWN=(P+x for x in ('copy','copy_base','purge','bounce','watch','fail','unknown'))
FIRE='CORE_CS2_029'
CTX=GenerationContext('k428-reviewed-colossal-prefix-domain','experimental')
DECK=(COIN,)*24


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('normal',role);r._version+='.k428.'+mode
    targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    for cid,copy_mode in ((COPY,'current'),(COPY_BASE,'base')):
        def copy(c,copy_mode=copy_mode):
            return (CopyMinion(c.target_id,c.player_id,mode=copy_mode),)
        r.register_behavior(cid,copy)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=META))
    r.register_behavior(PURGE,lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id in cards.LIMBS))
    r.register_card(CardDefinition(PURGE,PURGE,CardType.SPELL,on_play=PURGE,metadata=META))
    r.register_behavior(BOUNCE,lambda c:(ReturnToHand(c.target_id),))
    r.register_card(CardDefinition(BOUNCE,BOUNCE,CardType.SPELL,on_play=BOUNCE,targeting=targeting,metadata=META))
    def fail(c):raise ResolutionError('K428 deliberate Colossal continuation failure')
    def watch(c):
        if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=cards.LIMBS[0]:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('go','Continue'),ChoiceOption('bad','Fail',
            (GainArmor(c.player_id,1),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(FAIL,fail);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,metadata=META,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    members=(FIRE,)
    if mode=='unknown_fire':
        missing=CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,cost=1,spell_school=SpellSchool.FIRE,
            metadata=replace(META,collectible=True,classes=(CardClass.MAGE,),deck_identity=UNKNOWN))
        r.register_pool_card(PoolCard.from_definition(missing));members+=(UNKNOWN,)
    if mode!='no_fire':
        r.register_pool(PoolDefinition(cards.load_batch()['plume_pool_id'],'k428-full-explicit-fire-domain',
            CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    if mode in ('assemble_blood','assemble_vulcanos'):
        root=BLOOD if mode=='assemble_blood'else VULCANOS
        r.register_pool(PoolDefinition(ASSEMBLE_POOL,'k428-real-low-primary-colossal-and-five-donor',
            CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in (PAIN,root,WAR)),complete=True))
    r.validate();return r


class AssembleColossalTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode='normal',hero='HERO_09'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=DECK,mana=30,max_mana=30,mana_cap=30)),
            seed=428,generation_context=CTX),fixture(mode))

    def eid(self,g,cid,player=1,zone='board'):
        return next(i for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,source,target));return source

    def pick(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def count(self,g,cid,zone='board'):
        return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[1],zone))

    def board_ids(self,g):return [g.state.entities[i].card_id for i in g.state.players[1].board]

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader')
        self.assertIsNot(reader,g.registry);other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','assemble_colossal_sources','condition_id'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a_seven_complete_sources_fourteen_faces_full_query_and_exact_self_reconstruction(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),7);self.assertEqual(len(d['official_observations']),14)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256'])
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            original=r.card(cid);derived=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual((derived.cost,derived.attack,derived.health,derived.metadata,derived.keywords,derived.colossal),
                (original.cost,original.attack,original.health,original.metadata,original.keywords,original.colossal))
            self.assertEqual(r.assemble_colossal_sources[cid].appendages,original.colossal)

    def test_b_top_replacement_uses_actual_selected_order_not_primary_material(self):
        r=fixture()
        for primary,secondary in ((BLOOD,VULCANOS),(VULCANOS,BLOOD),(WAR,BLOOD)):
            face=r.card(AssembleRecipe(primary,secondary,'top').card_id)
            self.assertEqual(face.colossal,r.card(secondary).colossal)
            self.assertEqual((face.cost,face.attack,face.health,face.metadata),
                (r.card(primary).cost,r.card(primary).attack,r.card(primary).health,r.card(primary).metadata))

    def test_c_non_colossal_top_replacement_removes_old_primary_appendages_and_keyword(self):
        r=fixture()
        for primary in cards.SOURCES:
            face=r.card(AssembleRecipe(primary,WAR,'top').card_id)
            self.assertEqual(face.colossal,());self.assertNotIn(Keyword.COLOSSAL,face.keywords)
            self.assertEqual(face.cost,r.card(primary).cost)

    def test_d_original_and_self_paid_entries_keep_complete_left_right_order_and_one_payment(self):
        for original in cards.SOURCES:
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game((cid,));mana=g.state.players[1].mana;source=self.play(g,cid)
                specs=g.registry.card(original).colossal
                expected=[x.card_id for x in specs if x.side=='left']+[cid]+[x.card_id for x in specs if x.side=='right']
                self.assertEqual(self.board_ids(g),expected)
                self.assertEqual(g.state.players[1].mana,mana-g.registry.card(original).cost)
                row,=g.state.colossal_history;self.assertEqual(row.entity_id,source)
                self.assertEqual(tuple(g.state.entities[x].card_id for x in row.limbs),tuple(x.card_id for x in specs))

    def test_e_original_and_self_vulcanos_damage_actual_limbs_and_get_original_discounted_fire(self):
        for cid in (VULCANOS,AssembleRecipe(VULCANOS,VULCANOS,'bottom').card_id):
            g=self.game((cid,),enemy=(DUMMY,));source=self.play(g,cid);g.apply(EndTurn(1))
            self.assertEqual(g.state.entities[source].health,8)
            self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,3)
            self.assertEqual(self.count(g,FIRE,zone='hand'),2)
            self.assertEqual([g.state.entities[self.eid(g,x)].health for x in cards.LIMBS[3:]],[2,2])

    def test_f_original_and_self_blood_trigger_after_actual_owner_healing_and_ignore_overheal(self):
        for cid in (BLOOD,AssembleRecipe(BLOOD,BLOOD,'bottom').card_id):
            g=self.game((cid,PING,HEAL,HEAL),enemy=(DUMMY,));source=self.play(g,cid)
            hero=g.state.players[1].hero_id;target=self.eid(g,DUMMY,2)
            self.play(g,PING,hero);self.play(g,HEAL,hero)
            self.assertEqual(g.state.entities[target].damage,5)
            self.assertEqual(g.state.entities[source].damage,1)
            rng=g.snapshot()['rng_state'];self.play(g,HEAL,hero)
            self.assertEqual(g.state.entities[target].damage,5);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_g_borrowed_ordinary_prefix_keeps_three_limbs_but_draws_instead_of_attacking(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        g=self.game((cid,PING,HEAL),enemy=(DUMMY,));source=self.play(g,cid)
        hero=g.state.players[1].hero_id;self.play(g,PING,hero);self.play(g,HEAL,hero)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.players[1].board),6)
        self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,0)
        self.assertEqual(g.state.entities[source].damage,0)

    def test_h_borrowed_owner_end_prefix_keeps_two_limbs_without_native_area_damage(self):
        cid=AssembleRecipe(VULCANOS,WAR,'bottom').card_id
        g=self.game((cid,),enemy=(DUMMY,));self.play(g,cid);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.draw_history),2)  # own reward and next player's normal draw
        self.assertEqual(self.count(g,FIRE,zone='hand'),0)
        self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,0)
        self.assertEqual([g.state.entities[self.eid(g,x)].health for x in cards.LIMBS[3:]],[5,5])

    def test_i_non_colossal_replacement_really_enters_without_old_limbs_and_executes_subject(self):
        cid=AssembleRecipe(VULCANOS,CURATOR,'top').card_id
        g=self.game((cid,),board=(N,),enemy=(DUMMY,));source=self.play(g,cid)
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(g.state.colossal_history,[])
        self.assertEqual(g.state.entities[self.eid(g,N)].damage,3)
        self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,3)
        self.assertEqual(g.state.entities[source].damage,0)

    def test_j_switching_two_colossal_prefixes_uses_new_two_limb_sequence(self):
        cid=AssembleRecipe(BLOOD,VULCANOS,'top').card_id
        g=self.game((cid,),enemy=(DUMMY,));source=self.play(g,cid)
        self.assertEqual(self.board_ids(g),[cards.LIMBS[3],cid,cards.LIMBS[4]])
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,5)
        self.assertEqual(g.state.entities[source].damage,1)

    def test_k_capacity_attempts_each_ordered_limb_without_substituting_new_identity(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        for occupants,expected in ((5,1),(6,0)):
            g=self.game((cid,),board=(N,)*occupants);self.play(g,cid)
            self.assertEqual(len(g.state.players[1].board),7)
            row,=g.state.colossal_history;self.assertEqual(sum(x is not None for x in row.limbs),expected)
            if expected:self.assertEqual(g.state.entities[row.limbs[0]].card_id,cards.LIMBS[0])

    def test_l_current_copy_of_assembled_source_reuses_colossal_entry_and_material(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        g=self.game((cid,PURGE,COPY));source=self.play(g,cid);self.play(g,PURGE);self.play(g,COPY,source)
        self.assertEqual(self.count(g,cid),2);self.assertEqual(len(g.state.colossal_history),2)
        self.assertEqual(len(g.state.players[1].board),5)
        self.assertEqual(g.state.colossal_history[-1].origin_id,source)
        self.portable(g)

    def test_m_current_silenced_copy_keeps_no_active_colossal_while_base_copy_restores_it(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        for copy in (COPY,COPY_BASE):
            g=self.game((cid,PURGE,MUTE,copy));source=self.play(g,cid)
            self.play(g,PURGE);self.play(g,MUTE,source);self.play(g,copy,source)
            self.assertEqual(self.count(g,cid),2)
            self.assertEqual(len(g.state.colossal_history),2 if copy==COPY_BASE else 1)

    def test_n_return_and_replay_same_entity_creates_new_entry_without_reusing_old_limbs(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        g=self.game((cid,PURGE,BOUNCE));source=self.play(g,cid);first=g.state.colossal_history[0]
        self.play(g,PURGE);self.play(g,BOUNCE,source);again=self.play(g,cid)
        self.assertEqual(source,again);last=g.state.colossal_history[-1]
        self.assertNotEqual((first.zone_epoch,first.entered_order),(last.zone_epoch,last.entered_order))
        self.assertTrue(set(first.limbs).isdisjoint(last.limbs));self.portable(g)

    def test_o_waiting_mid_appendage_restores_clones_replays_and_rolls_back_bad_resume(self):
        cid=AssembleRecipe(BLOOD,WAR,'bottom').card_id
        g=self.game((cid,),board=(WATCH,));self.play(g,cid)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(any(x is None for x in g.state.colossal_history[0].limbs))
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K428 deliberate'):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.pick(g,'go');self.pick(other,'go');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertTrue(all(x is not None for x in g.state.colossal_history[0].limbs))

    def test_p_real_priest_offer_installs_three_limbs_on_original_low_cost_neutral_body(self):
        cid=AssembleRecipe(PAIN,BLOOD,'top').card_id
        g=self.game((MISMATCH,),mode='assemble_blood');self.play(g,MISMATCH)
        self.pick(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
        mana=g.state.players[1].mana;source=self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,mana-3);self.assertEqual(len(g.state.players[1].board),5)
        self.assertEqual(self.count(g,MISMATCH),1)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(1,4))
        self.assertEqual(g.registry.card(cid).metadata,g.registry.card(PAIN).metadata)

    def test_q_real_mage_offer_installs_two_limbs_and_owner_end_draw_on_low_primary(self):
        cid=AssembleRecipe(PAIN,VULCANOS,'top').card_id
        g=self.game((MISMATCH,),mode='assemble_vulcanos',hero='HERO_08');self.play(g,MISMATCH)
        self.pick(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
        self.play(g,cid);self.assertEqual(self.board_ids(g),[MISMATCH,cards.LIMBS[3],cid,cards.LIMBS[4]])
        g.apply(EndTurn(1));self.assertEqual(len([r for r in g.state.draw_history if r.player_id==1]),1)

    def test_r_missing_or_unknown_fire_domain_rolls_back_entire_native_colossal_end(self):
        for mode in ('no_fire','unknown_fire'):
            cid=AssembleRecipe(VULCANOS,VULCANOS,'bottom').card_id
            g=self.game((cid,),mode=mode);self.play(g,cid);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'domain|pool|unsupported|unimplemented'):g.apply(EndTurn(1))
            self.assertEqual(g.snapshot(),saved)

    def test_s_source_declarations_are_immutable_unique_and_frozen_registry_rejects_changes(self):
        r=build_registry();profile=r.assemble_colossal_sources[BLOOD]
        with self.assertRaises(FrozenInstanceError):profile.card_id=VULCANOS
        with self.assertRaises(TypeError):r.assemble_colossal_sources[BLOOD]=profile
        with self.assertRaisesRegex(ValueError,'Duplicate'):r.register_assemble_colossal_source(profile)
        with self.assertRaises(ValueError):r.register_assemble_colossal_source(replace(profile,appendages=profile.appendages[:-1]))
        r.freeze()
        with self.assertRaisesRegex(ValueError,'frozen'):r.register_assemble_colossal_source(profile)

    def test_t_original_order_missing_limb_or_missing_template_cannot_be_silently_accepted(self):
        r=build_registry();old=r._cards[BLOOD]
        r._cards[BLOOD]=replace(old,colossal=tuple(reversed(old.colossal)))
        with self.assertRaisesRegex(ValueError,'Colossal'):r.validate()
        r._cards[BLOOD]=old;limb=r._cards.pop(cards.LIMBS[0])
        with self.assertRaisesRegex(ValueError,'appendage'):r.validate()
        r._cards[cards.LIMBS[0]]=limb;template=r._assemble_templates.pop(BLOOD)
        bridge=r._assemble_reaction_sources.pop(BLOOD)
        with self.assertRaisesRegex(ValueError,'template'):r.validate()
        r._assemble_templates[BLOOD]=template;r._assemble_reaction_sources[BLOOD]=bridge;r.validate()

    def test_u_no_keyword_only_shortcut_and_old_core_snapshot_are_accepted(self):
        r=fixture();t=r.assemble_templates[BLOOD]
        with self.assertRaisesRegex(ValueError,'complete selected prefix'):printed_face(r.card(BLOOD),t.prefix,t.suffix,BLOOD)
        g=self.game();saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v667'
        with self.assertRaisesRegex(SnapshotError,'Mechanics version mismatch'):Game.from_snapshot(saved,fixture('normal','reader'))

    def test_v_whole_original_source_or_plume_query_drift_rejects_before_installation(self):
        with patch('hs_sim.cards.assemble_colossal_followups.register_assemble_colossal_followups',lambda r:None):r=build_registry()
        old=r._cards[cards.LIMBS[0]];r._cards[cards.LIMBS[0]]=replace(old,health=old.health+1)
        with self.assertRaises(TargetValidationError):cards.register_assemble_colossal_followups(r)
        self.assertEqual(dict(r.assemble_colossal_sources),{})
        r._cards[cards.LIMBS[0]]=old
        with patch.object(cards.native_limbs,'FIRE_QUERY',replace(cards.native_limbs.FIRE_QUERY,collectible=False)):
            with self.assertRaisesRegex(TargetValidationError,'Plume query'):cards.register_assemble_colossal_followups(r)
        self.assertEqual(dict(r.assemble_colossal_sources),{})
