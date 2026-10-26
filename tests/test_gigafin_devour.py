"""Gigafin destroys actual victims; original granted payloads own base returns."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.gigafin_devour import CARD, MAW, load_batch, register_gigafin_devour
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayerSetup, ResolutionError, Scenario, SnapshotError, TargetMode,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, DestroyBatch, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k584.'
UNIT, TOKEN, HATCH, BOOM, REBORN, WATCH = (P+x for x in ('unit','token','hatch','boom','reborn','watch'))
KILL, QUIET, COPY, BASE, GIVE, BOUNCE, GROW, DORMANT, BOTH, ADD_MAW = (
    P+x for x in ('kill','silence','copy','base','give','bounce','grow','dormant','both','maw'))
SOURCE = 'CATA_EVENT_000'
CONTEXT = GenerationContext(P+'explicit-native-adapter-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    for pool in [v for v in r.pools.values() if v.target_id == f.target_id and v.mode == f.context.mode]:
        if pool.id != 'constructed.past.cards':
            r.register_pool(replace(pool, target_id=CONTEXT.target_id, mode=CONTEXT.mode))
    # Explicit adapter fixture; the untouched complete thirteen-member source
    # is not declared bound by this one-card positive entry.
    r.register_pool(PoolDefinition('constructed.past.cards', P+'one-native-body',
        CONTEXT.target_id, CONTEXT.mode, (PoolMember(CARD),), complete=True))
    def hatch(c): return (Summon(c.player_id, TOKEN),)
    def boom(c):
        body = next((c.state.entities[i] for i in c.state.players[3-c.player_id].board
            if c.state.entities[i].card_id == CARD), None)
        return () if body is None else (Damage(body.id, 4, c.source_id),)
    def fail(c): raise ResolutionError('K584 deliberate late failure')
    def watch(c):
        e = c.event
        if mode == 'return-wait' and e.kind == 'minion_summoned' and e.player_id == 2 and c.state.consumed_card_history:
            if c.state.entities[e.target_id].card_id == UNIT and sum(c.state.entities[i].card_id == UNIT for i in c.state.players[2].board) == 1:
                return (RequestChoice(c.player_id, (ChoiceOption('ok','continue'),
                    ChoiceOption('bad','fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))), c.source_id),)
        if e.kind != 'ability_granted' or e.target_id is None or c.state.entities[e.target_id].card_id != CARD: return ()
        rows = c.state.consumed_card_history
        if len(rows) != 2: return ()
        aid = dict(e.data).get('ability_id')
        if mode == 'devour-wait' and aid == rows[0].ability_id:
            return (RequestChoice(c.player_id, (ChoiceOption('ok','continue'),
                ChoiceOption('bad','fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))), c.source_id),)
        if mode == 'late-failure' and aid == rows[1].ability_id:
            return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return ()
    for name, body in ((P+'hatch',hatch),(P+'boom',boom),(P+'fail',fail),(P+'watch',watch)):
        r.register_behavior(name,body)
    for cid, health, dr, keywords in ((UNIT,3,None,()),(TOKEN,1,None,()),(HATCH,2,P+'hatch',()),
            (BOOM,1,P+'boom',()),(REBORN,2,None,(Keyword.REBORN,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,
            deathrattle=dr,keywords=keywords,metadata=META))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=tuple(TriggerSpec(kind,P+'watch') for kind in ('ability_granted','minion_summoned'))))
    def destroy_both(c):
        ids=tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in (CARD,MAW))
        return (DestroyBatch(ids,c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),), QUIET:lambda c:(Silence(c.target_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id),), BASE:lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),), BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        GROW:lambda c:(Buff(c.target_id,attack=3,health=5,source_id=c.source_id),),
        DORMANT:lambda c:(MakeDormant(c.target_id,None,c.source_id),), BOTH:destroy_both,
        ADD_MAW:lambda c:(Summon(c.player_id,MAW),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        spec=None if cid in (BOTH,ADD_MAW) else TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=spec,metadata=META))
    r.validate(); return r


class GigafinDevourTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(host)
    mode='normal'

    def game(self,hand=(),*,enemy=(UNIT,UNIT),own=(),player=1,mode='normal'):
        self.mode=mode
        if mode!='normal':own=(WATCH,*own)
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_09',hand=(SOURCE,*hand) if p==player else (),
            board=own if p==player else enemy,deck=(UNIT,)*12,mana=40,max_mana=40,mana_cap=40) for p in (1,2)),
            active_player=player,seed=584,generation_context=CONTEXT),host(mode))

    def reward(self,g,player=1):
        self.play(g,SOURCE,player=player);return self.play(g,CARD,player=player)

    def board(self,g,player=2):return [g.state.entities[i].card_id for i in g.state.players[player].board]

    def parent(self,g):return self.entity(g,CARD,zone='board').id

    def maw(self,g):return self.entity(g,MAW,zone='board').id

    def test_complete_raw_main_faces_and_original_named_maw_profile(self):
        data=load_batch();raw=data['cards'][0]['record']
        for face in data['official_observations']:batch.check_face(raw,face['face'],face['locale'])
        self.assertEqual([v['record']['id'] for v in data['evidence_only']],['TSC_962e','TSC_962e2'])
        self.assertEqual(host().consumption_profiles[CARD].kind,'board_minions')
        self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])

    def test_native_paid_entry_real_deaths_and_fresh_base_return_in_both_seats(self):
        for player in (1,2):
            g=self.game((KILL,),player=player);original=tuple(g.state.players[3-player].board)
            parent=self.reward(g,player)
            self.assertEqual(g.state.players[player].mana,26)
            self.assertEqual(self.board(g,player),[SOURCE,CARD,MAW]);self.assertEqual(self.board(g,3-player),[])
            rows=g.state.consumed_card_history;self.assertEqual(len(rows),2)
            self.assertTrue(all(v.destruction.kind=='destroy' for v in rows))
            self.assertEqual([v.entity_id for v in g.state.death_history],list(original))
            self.play(g,KILL,parent,player=player)
            self.assertEqual(self.board(g,3-player),[UNIT,UNIT])
            self.assertFalse(set(original)&set(g.state.players[3-player].board))

    def test_maw_first_digests_live_parent_payloads_and_both_dead_preserve_accepted_returns(self):
        g=self.game((KILL,KILL));parent=self.reward(g);self.play(g,KILL,self.maw(g))
        self.assertFalse(any(a.consumed_card_id is not None for a in g.state.entities[parent].abilities))
        self.play(g,KILL,parent);self.assertEqual(self.board(g),[])
        h=self.game((BOTH,));self.reward(h);self.play(h,BOTH)
        self.assertEqual(self.board(h),[UNIT,UNIT])

    def test_actual_victim_deathrattle_runs_and_new_token_is_not_added_to_old_return_inventory(self):
        g=self.game((KILL,),enemy=(HATCH,));parent=self.reward(g)
        self.assertEqual(self.board(g),[TOKEN]);self.assertEqual(len(g.state.consumed_card_history),1)
        self.play(g,KILL,parent);self.assertEqual(self.board(g),[TOKEN,HATCH])

    def test_victim_death_damage_can_kill_gigafin_and_release_inventory_during_its_battlecry(self):
        g=self.game(enemy=(BOOM,UNIT));parent=self.reward(g)
        self.assertEqual(g.state.entities[parent].zone,Zone.GRAVEYARD)
        self.assertEqual(self.board(g),[BOOM,UNIT]);self.portable(g)

    def test_reborn_and_dormant_victims_use_existing_death_and_presence_rules(self):
        g=self.game((KILL,),enemy=(REBORN,));parent=self.reward(g)
        self.assertEqual(len(g.state.consumed_card_history),1);self.assertEqual(self.board(g),[REBORN])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,1)
        self.play(g,KILL,parent);self.assertEqual(self.board(g),[REBORN,REBORN])
        h=self.game((DORMANT,KILL));sleep=h.state.players[2].board[0];self.play(h,DORMANT,sleep)
        parent=self.reward(h);self.assertEqual(self.board(h),[UNIT]);self.assertEqual(len(h.state.consumed_card_history),1)
        self.play(h,KILL,parent);self.assertEqual(self.board(h),[UNIT,UNIT])

    def test_return_discards_ordinary_stats_damage_and_current_enchantments(self):
        g=self.game((GROW,KILL),enemy=(UNIT,));old=g.state.players[2].board[0];self.play(g,GROW,old)
        parent=self.reward(g);self.play(g,KILL,parent)
        returned=g.state.entities[g.state.players[2].board[0]]
        self.assertEqual((returned.attack,returned.max_health,returned.damage),(1,3,0))

    def test_silence_or_parent_return_to_hand_removes_return_payloads(self):
        for script in (QUIET,BOUNCE):
            g=self.game((script,KILL));parent=self.reward(g);self.play(g,script,parent)
            if script==BOUNCE:
                self.play(g,CARD)
            self.play(g,KILL,parent);self.assertEqual(self.board(g),[])

    def test_current_parent_copy_keeps_inventory_and_original_maw_does_not_digest_new_parent(self):
        g=self.game((COPY,KILL,KILL,KILL));original=self.reward(g);self.play(g,COPY,original)
        copied=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD and i!=original)
        maw=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==MAW)
        self.play(g,KILL,maw);self.play(g,KILL,copied);self.assertEqual(self.board(g),[UNIT,UNIT])
        self.play(g,KILL,original);self.assertEqual(self.board(g),[UNIT,UNIT])

    def test_current_maw_copy_keeps_parent_binding_and_base_copy_has_no_old_parent(self):
        for script,expected in ((COPY,[]),(BASE,[UNIT,UNIT])):
            g=self.game((script,KILL,KILL));parent=self.reward(g);original=self.maw(g);self.play(g,script,original)
            copied=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==MAW and i!=original)
            self.play(g,KILL,copied);self.play(g,KILL,parent);self.assertEqual(self.board(g),expected)

    def test_bounced_replayed_maw_and_standalone_maw_do_not_digest_original_parent(self):
        for script in (BOUNCE,ADD_MAW):
            g=self.game((script,KILL,KILL));parent=self.reward(g);old=self.maw(g)
            if script==BOUNCE:
                self.play(g,script,old);self.play(g,MAW);other=old
            else:
                self.play(g,script);other=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==MAW and i!=old)
            self.play(g,KILL,other);self.play(g,KILL,parent);self.assertEqual(self.board(g),[UNIT,UNIT])

    def test_stolen_parent_returns_opposite_current_deathrattle_controller(self):
        g=self.game((GIVE,KILL));parent=self.reward(g);self.play(g,GIVE,parent);self.play(g,KILL,parent)
        self.assertEqual(self.board(g),[]);self.assertEqual(self.board(g,1).count(UNIT),2)

    def test_devour_and_first_return_waits_restore_clone_replay_and_bad_choice_is_atomic(self):
        for mode in ('devour-wait','return-wait'):
            g=self.game((KILL,),mode=mode);parent=self.reward(g)
            if mode=='return-wait':self.play(g,KILL,parent)
            self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),saved)
            self.choose(g,'ok');self.choose(restored,'ok');self.assertEqual(g.snapshot(),restored.snapshot())

    def test_late_failure_rolls_back_complete_devour_payment_marks_grants_events_and_rng(self):
        g=self.game(mode='late-failure');self.play(g,SOURCE);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_private_views_do_not_expose_destruction_material_parent_residence_or_history_ids(self):
        g=self.game();self.reward(g)
        for player in (1,2):
            view=json.dumps(g.observe(player))
            for key in ('devour_parent','consumed_card_id','consumed_card_history','destruction','presence_id','resolution_frame'):
                self.assertNotIn('"'+key+'"',view)

    def test_rehashed_wrong_destruction_unknown_parent_and_old_schema_are_rejected(self):
        g=self.game();self.reward(g);saved=g.snapshot();bad=deepcopy(saved)
        bad['state']['consumed_card_history'][0]['destruction']['source_id']=g.state.players[2].hero_id
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,host('normal','independent-reader'))
        bad=deepcopy(saved);maw=self.maw(g)
        ability=next(a for a in bad['state']['entities'][str(maw)]['abilities'] if a.get('devour_parent'))
        ability['devour_parent']['entity_id']=999999
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,host('normal','independent-reader'))
        bad=deepcopy(saved);bad['schema_version']=599
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,host('normal','independent-reader'))

    def test_late_child_metadata_failure_does_not_leave_partial_native_registration(self):
        r=build_registry();data=load_batch()
        for cid in (CARD,MAW):del r._cards[cid]
        del r._consumption_profiles[CARD]
        for key in ('producer_behavior_id','deathrattle_behavior_id','maw_behavior_id'):del r._behaviors[data[key]]
        r._pool_cards[MAW]=replace(r.pool_card(MAW),cost=7)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors),dict(r.consumption_profiles))
        with self.assertRaises(TargetValidationError):register_gigafin_devour(r)
        self.assertEqual((dict(r.cards),dict(r.pool_cards),dict(r._behaviors),dict(r.consumption_profiles)),before)


if __name__=='__main__':unittest.main()
