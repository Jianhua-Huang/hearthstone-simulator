"""Actual Heat Wave accepts inverse targets over original Quickdraw facts."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from types import MappingProxyType
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import heatwave_card as native
from hs_sim.engine import (CardClass,CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError,TriggerSpec)
from hs_sim.engine.body_conditions import BodyPlayConditions
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,Draw,InvokeBehavior,RequestChoice
from hs_sim.engine.model import CardMetadata,Rarity,Zone
from hs_sim.engine.play_history import preplay_conditions
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.target_conditions import TARGET_CONDITIONS,target_condition_active,target_condition_keyword
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

HEAT=native.CARD;P='k606.'
NOOP,GAIN,DRAW,AUTO,LEFT,MIDDLE,RIGHT,OTHER,DORMANT,POWER,WAIT_BEFORE,WAIT_HIT,KILL_BEFORE,ADD_BEFORE=(
    P+s for s in('noop','gain','draw','auto','left','middle','right','other','dormant','power','wait_before','wait_hit','kill_before','add_before'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(GAIN,lambda c:(AddToHand(c.player_id,HEAT,c.source_id),))
    r.register_behavior(DRAW,lambda c:(Draw(c.player_id,source_id=c.source_id),))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,HEAT,c.source_id),))
    def fault(c):raise ResolutionError('K606 deliberate saved choice failure')
    r.register_behavior(P+'fault',fault)
    def wait(c):return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
        ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if source is None or source.card_id!=HEAT:return ()
        if c.source.card_id==WAIT_BEFORE and e.kind=='card_committed':return wait(c)
        if c.source.card_id==WAIT_HIT and e.kind=='damage_dealt':return wait(c)
        if c.source.card_id==KILL_BEFORE and e.kind=='card_committed':
            return tuple(Destroy(i,c.source_id)for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==MIDDLE)
        if c.source.card_id==ADD_BEFORE and e.kind=='card_committed':return(AddToHand(c.player_id,HEAT,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid in(NOOP,GAIN,DRAW,AUTO):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    for cid in(LEFT,MIDDLE,RIGHT,OTHER,DORMANT,POWER,WAIT_BEFORE,WAIT_HIT,KILL_BEFORE,ADD_BEFORE):
        event='damage_dealt' if cid==WAIT_HIT else 'card_committed'
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=30 if cid in(WAIT_BEFORE,WAIT_HIT,KILL_BEFORE,ADD_BEFORE)else 5,
            spell_damage=1 if cid==POWER else 0,dormant_turns=2 if cid==DORMANT else 0,metadata=META,
            triggers=(TriggerSpec(event,P+'watch'),)if cid in(WAIT_BEFORE,WAIT_HIT,KILL_BEFORE,ADD_BEFORE)else()))
    r.validate();return r


class HeatWaveTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,deck=(NOOP,)*6,board=(),enemy_board=(LEFT,MIDDLE,RIGHT),player=1):
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else(),deck=deck if p==player else(NOOP,)*6,
            board=board if p==player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=606),registry())

    def paid(self,g,cid=HEAT,target=None,p=1):
        e=self.entity(g,cid,p);cost=quote_cost(g.state,g.registry,e).amount;mana=g.state.players[p].mana
        source=self.play(g,cid,target,p);self.assertEqual(g.state.players[p].mana,mana-cost)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,cost));return source

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def flags(self,g,cid=HEAT,p=1):return preplay_conditions(g.state,self.entity(g,cid,p),g.registry)

    def healths(self,g,p):return [g.state.entities[i].health for i in g.state.players[p].board]

    def public_actions(self,g,p=1):
        listing=g.for_player(p).legal_actions();own=listing['observation']['players'][p-1]
        refs={c['ref']for c in own['hand']if c['card_id']==HEAT}
        return listing,[a for a in listing['actions']if a['type']=='play_card' and a['card']in refs]

    def test_complete_real_face_two_primary_observations_and_original_printed_quickdraw(self):
        data=native.load_batch();raw=data['cards'][0]['record']
        for obs in data['official_observations']:batch.check_face(raw,obs['face'],obs['locale'])
        self.assertEqual(len(data['official_observations']),2)
        card=registry().card(HEAT);self.assertEqual((card.cost,card.spell_school.value,card.target_condition),(2,'fire','unless_quickdraw'))
        self.assertIn(Keyword.QUICKDRAW,card.keywords);self.assertEqual(card.targeting.relation,'enemy');self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_finite_shared_truth_table_uses_original_boolean_mapping_and_typed_body_facts(self):
        self.assertEqual(len(TARGET_CONDITIONS),6);self.assertTrue(target_condition_active(None,None))
        for quickdraw in(False,True):
            values=dict(combo=False,outcast=True,finale=False,quickdraw=quickdraw,manathirst=False)
            typed=BodyPlayConditions(False,True,False,quickdraw,False,30,None)
            for original in(values,MappingProxyType(values),typed):
                self.assertEqual(target_condition_active('unless_quickdraw',original),not quickdraw)
                for key,value in values.items():self.assertEqual(target_condition_active(key,original),value)
        self.assertEqual(target_condition_keyword('unless_quickdraw'),'quickdraw')
        for bad in('unless_combo','not_quickdraw','',True):
            with self.assertRaises(ValueError):target_condition_active(bad,{'quickdraw':True})
        for values in({},dict(quickdraw=1),dict(quickdraw='false')):
            with self.assertRaises(ValueError):target_condition_active('unless_quickdraw',values)

    def test_inverse_declaration_requires_actual_printed_quickdraw_and_rejects_unreviewed_inverse(self):
        card=registry().card(HEAT)
        with self.assertRaisesRegex(ValueError,'printed keyword'):registry()._validate_card(replace(card,keywords=()))
        with self.assertRaises(ValueError):registry()._validate_card(replace(card,target_condition='unless_combo'))

    def test_initial_scenario_hand_is_old_and_normal_mode_hits_exact_enemy_neighbours_both_seats(self):
        for p in(1,2):
            g=self.game((HEAT,),board=(OTHER,),player=p);self.assertFalse(self.flags(g,p=p)['quickdraw'])
            self.paid(g,target=g.state.players[3-p].board[1],p=p)
            self.assertEqual(self.healths(g,3-p),[3,3,3]);self.assertEqual(self.healths(g,p),[5]);self.assertEqual(self.hero(g,3-p).health,30)
            self.assertFalse(g.state.play_history[-1].quickdraw)

    def test_normal_mode_needs_enemy_minion_and_rejects_hero_friendly_and_no_target_without_payment(self):
        g=self.game((HEAT,),board=(OTHER,));saved=g.snapshot()
        for target in(None,g.state.players[1].hero_id,g.state.players[2].hero_id,g.state.players[1].board[0]):
            with self.assertRaises(IllegalAction):self.play(g,HEAT,target)
            self.assertEqual(g.snapshot(),saved)
        g=self.game((HEAT,),enemy_board=());saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HEAT)
        self.assertEqual(g.snapshot(),saved);_,actions=self.public_actions(g);self.assertEqual(actions,[])

    def test_normal_neighbours_use_physical_slots_without_jumping_over_dormant_occupant(self):
        g=self.game((HEAT,),enemy_board=(LEFT,DORMANT,MIDDLE,RIGHT));self.paid(g,target=g.state.players[2].board[2])
        self.assertEqual(self.healths(g,2),[5,5,3,3])

    def test_generated_quickdraw_has_no_target_hits_all_enemies_and_only_their_hero_both_seats(self):
        for p in(1,2):
            g=self.game((GAIN,),board=(OTHER,),player=p);self.paid(g,GAIN,p=p);self.assertTrue(self.flags(g,p=p)['quickdraw'])
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,HEAT,g.state.players[3-p].board[1],p)
            self.assertEqual(g.snapshot(),saved);self.paid(g,p=p)
            self.assertEqual(self.healths(g,3-p),[3,3,3]);self.assertEqual(self.hero(g,3-p).health,28);self.assertEqual(self.hero(g,p).health,30)
            self.assertEqual(self.healths(g,p),[5]);self.assertTrue(g.state.play_history[-1].quickdraw)

    def test_quickdraw_with_no_enemy_minions_is_still_playable_and_damages_hero(self):
        g=self.game((GAIN,),enemy_board=());self.paid(g,GAIN);self.paid(g);self.assertEqual(self.hero(g,2).health,28)

    def test_real_draw_enables_quickdraw_and_older_same_card_keeps_its_original_target_mode(self):
        g=self.game((HEAT,DRAW),deck=(HEAT,));old=self.entity(g,HEAT).id;self.paid(g,DRAW)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==HEAT]
        self.assertEqual([preplay_conditions(g.state,g.state.entities[i],g.registry)['quickdraw']for i in ids],[False,True])
        fresh=next(i for i in ids if i!=old);g.apply(PlayCard(1,fresh));self.assertTrue(g.state.play_history[-1].quickdraw)
        self.assertEqual(self.hero(g,2).health,28);self.assertFalse(self.flags(g)['quickdraw'])

    def test_real_acquisition_quickdraw_expires_and_restores_original_target_requirement_next_turn(self):
        g=self.game((GAIN,));self.paid(g,GAIN);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertFalse(self.flags(g)['quickdraw'])
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HEAT)
        self.assertEqual(g.snapshot(),saved);self.paid(g,target=g.state.players[2].board[1]);self.assertEqual(self.hero(g,2).health,30)

    def test_public_player_actions_agree_with_both_native_target_modes_and_real_payments(self):
        for acquired in(False,True):
            g=self.game((GAIN,)if acquired else(HEAT,))
            if acquired:self.paid(g,GAIN)
            listing,actions=self.public_actions(g);self.assertTrue(actions)
            self.assertTrue(all((a['target']is None)==acquired for a in actions))
            self.assertTrue(g.for_player(1).submit({'revision':listing['revision'],'action':actions[0]})['accepted'])
            self.assertEqual(g.state.players[1].mana,28);self.assertEqual(g.state.play_history[-1].cost,2)

    def test_automatic_cast_uses_existing_false_quickdraw_fact_and_normal_enemy_minion_domain(self):
        g=self.game((AUTO,),enemy_board=(MIDDLE,));self.paid(g,AUTO)
        self.assertEqual(self.healths(g,2),[3]);self.assertEqual(self.hero(g,2).health,30)
        cast=g.state.cast_history[-1];self.assertEqual(cast.card_id,HEAT);self.assertFalse(cast.quickdraw);self.assertTrue(cast.payload_started)
        self.assertEqual(len(g.state.play_history),1)

    def test_automatic_cast_with_no_normal_target_does_not_forge_quickdraw_or_hero_damage(self):
        g=self.game((AUTO,),enemy_board=());rng=g.snapshot()['rng_state'];self.paid(g,AUTO)
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(g.snapshot()['rng_state'],rng)
        cast=g.state.cast_history[-1];self.assertFalse(cast.quickdraw);self.assertFalse(cast.payload_started)

    def test_each_mode_uses_shared_spell_damage_once_per_actual_original_packet(self):
        for acquired in(False,True):
            g=self.game((GAIN,)if acquired else(HEAT,),board=(POWER,))
            if acquired:self.paid(g,GAIN)
            self.paid(g,target=None if acquired else g.state.players[2].board[1])
            self.assertEqual(self.healths(g,2),[2,2,2]);self.assertEqual(self.hero(g,2).health,27 if acquired else 30)

    def test_normal_target_removed_after_original_acceptance_keeps_payment_and_does_not_reselect(self):
        g=self.game((HEAT,),board=(KILL_BEFORE,));target=g.state.players[2].board[1];self.paid(g,target=target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(self.healths(g,2),[5,5]);self.assertEqual(g.state.players[1].mana,28)

    def test_adding_a_new_same_card_before_body_does_not_rewrite_original_old_hand_flag(self):
        g=self.game((HEAT,),board=(ADD_BEFORE,));source=self.paid(g,target=g.state.players[2].board[1])
        self.assertNotEqual(self.entity(g,HEAT).id,source);self.assertTrue(self.flags(g)['quickdraw'])
        self.assertFalse(g.state.play_history[-1].quickdraw);self.assertEqual(self.hero(g,2).health,30)

    def test_both_original_modes_wait_before_body_restore_clone_replay_and_failure_preserve_payment(self):
        for acquired in(False,True):
            g=self.game((GAIN,)if acquired else(HEAT,),board=(WAIT_BEFORE,))
            if acquired:self.paid(g,GAIN)
            self.paid(g,target=None if acquired else g.state.players[2].board[1]);self.assertIsNotNone(g.state.pending_choice)
            other=self.portable(g);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'fault')
            self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
            self.assertEqual(self.hero(g,2).health,28 if acquired else 30);self.assertEqual(g.state.players[1].mana,28)

    def test_both_damage_modes_wait_with_original_packet_group_and_restore_without_repayment(self):
        for acquired in(False,True):
            g=self.game((GAIN,)if acquired else(HEAT,),board=(WAIT_HIT,))
            if acquired:self.paid(g,GAIN)
            self.paid(g,target=None if acquired else g.state.players[2].board[1]);self.assertIsNotNone(g.state.pending_choice)
            other=self.portable(g)
            for obj in(g,other):
                while obj.state.pending_choice is not None:self.choose(obj)
            self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.healths(g,2),[3,3,3]);self.assertEqual(g.state.players[1].mana,28)

    def test_rehashed_original_quickdraw_corruption_in_play_cast_or_both_cannot_change_saved_target_mode(self):
        g=self.game((GAIN,),board=(WAIT_HIT,));self.paid(g,GAIN);self.paid(g)
        self.assertEqual(g.state.cast_history[-1].card_id,HEAT)
        for keys in(('play_history',),('cast_history',),('play_history','cast_history')):
            data=g.snapshot()
            for key in keys:data['state'][key][-1]['quickdraw']=False
            data['state_hash']=canonical_hash({k:v for k,v in data.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(data,registry('normal','independent-reader'))

    def test_inverse_condition_does_not_create_or_publish_a_new_saved_flag_or_private_hand_history(self):
        g=self.game((GAIN,));self.paid(g,GAIN)
        own=g.observe(1)['players'][0]['hand'][0];hidden=g.observe(2)['players'][0]['hand'][0]
        self.assertTrue(own['play_conditions']['quickdraw']);self.assertNotIn('unless_quickdraw',own['play_conditions']);self.assertNotIn('play_conditions',hidden)
        for token in('"hand_entry_id"','"resolution_frame"','"state_hash"','"rng_state"'):self.assertNotIn(token,json.dumps(g.for_player(1).observe()))

    def test_bad_original_keyword_rejected_before_partial_card_or_behavior_registration(self):
        data=deepcopy(native.load_batch());data['cards'][0]['record']['tags']['QUICKDRAW']=0
        r=batch.registration_prefix(build_registry,'hs_sim.cards.heatwave_card.register_heatwave_card',native.register_heatwave_card)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data):
            with self.assertRaises(TargetValidationError):native.register_heatwave_card(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
