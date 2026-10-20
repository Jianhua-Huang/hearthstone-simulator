"""Actual Aya entry, persistent Coin material, opening policy and old consumers."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.aya_counterfeit_cards import CARD,JADE,GRIMY,KABAL,COINS,FORMS,FAMILY,PREFIX,load_batch
from hs_sim.cards.shadow_of_demise_card import CARD as SHADOW
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,Game,
    MatchSetup,PlayCard,PlayerSetup,Rarity,ResolutionError,Scenario,SelectChoice,SnapshotError,
    TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.coin_replacements import ACCEPTED,CHANGED,RETIRED,active_program
from hs_sim.engine.composed_spells import recipe_from_id
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand)
from hs_sim.engine.jade import CLASSIC,SummonJadeGolem,jade_count
from hs_sim.engine.opening_turn_order import EVENT
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,DrawMatching,MoveCard
from hs_sim.engine.pools import PoolQuery
from tools.card_batch import check_face
from hs_sim.targets import canonical_digest

P='fixture.aya.';UNIT=P+'unit';WATCH=P+'watch';COIN='GAME_005';FAKE=P+'fake'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=8,metadata=META))
    r.register_card(CardDefinition(FAKE,'The Coin',CardType.SPELL,on_play=P+'noop'))
    r.register_behavior(P+'noop',lambda c:())
    def fail(c):raise ResolutionError('Aya observer fixture failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if c.event.kind!='stored_card_transformed'or c.state.entities[c.event.target_id].zone!=Zone.HAND:return ()
        if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,
        triggers=(TriggerSpec('stored_card_transformed',P+'watch'),)))
    scripts={'get':lambda c:(AddToHand(c.player_id,COIN,source_id=c.source_id),),
        'get_two':lambda c:tuple(AddToHand(c.player_id,COIN,source_id=c.source_id)for _ in range(2)),
        'deck':lambda c:(AddToDeck(c.player_id,COIN,position='bottom',source_id=c.source_id),),
        'draw':lambda c:(Draw(c.player_id,1,c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),),
        'transform':lambda c:(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),COIN,c.source_id),),
        'steal':lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),),
        'draw_other':lambda c:(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.SPELL,)),'skip',source_id=c.source_id,owner_id=3-c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'classic':lambda c:(SummonJadeGolem(c.player_id,c.source_id,CLASSIC),),
        'forged_program':lambda c:(AddPlayerEffect(c.player_id,PREFIX+JADE,c.source_id),),
        'remove':lambda c:(RemovePlayerEffect(c.player_id,active_program(c.state,r,c.player_id).id),)}
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='enemy'if key=='steal'else'friendly')if key in('copy','transform','steal')else None
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,targeting=target,requires_target=key=='bounce'))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class AyaCounterfeitTests(unittest.TestCase):
    def game(self,hand=(CARD,COIN),deck=(),enemy_hand=(),enemy_deck=(),enemy_board=(),mode='normal',active=1,board=()):
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_03',hand=hand if p==active else enemy_hand,
            deck=deck if p==active else enemy_deck,board=((WATCH,)if mode in('wait','fail')else())+board if p==active else enemy_board,
            mana=10,max_mana=10)for p in(1,2)),active_player=active,seed=309),fixture(mode))
    def eid(self,g,cid,owner=None):return next(i for i in g.state.players[owner or g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def choose(self,g,cid):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(cid,)))
    def upgrade(self,g,cid=JADE):self.play(g,CARD);self.choose(g,cid)
    def held(self,g,p=None):return[g.state.entities[i].card_id for i in g.state.players[p or g.state.active_player].hand]
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));r=fixture.__wrapped__(mode)
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
        return other
    def opening(self,players=(1,),first=None):
        decks=tuple(((CARD,)if p in players else())+(UNIT,)*(12-int(p in players))for p in(1,2))
        policy=DeckPolicy('aya.actual-opening','aya-original-decks-experiment','experimental',(CARD,UNIT),deck_size=12,max_copies=12)
        setup=MatchSetup(tuple(DeckSpec('HERO_03','HERO_03bp',CardClass.ROGUE,d)for d in decks),policy,COIN,seed=309,first_player=first)
        return Game.from_decks(setup,fixture())

    def test_actual_source_preserves_grimy_and_potion_and_registers_complete_jade_artwork(self):
        d=load_batch();r=fixture();self.assertEqual(len(d['official_observations']),18)
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(6,6,3))
        for cid,pin in d['existing_dependency_definition_pins'].items():self.assertEqual(canonical_digest(asdict(r.card(cid))),pin['sha256'])
        self.assertEqual(r.jade_families[FAMILY].forms,FORMS)
        self.assertEqual(len(next(iter(r._coin_replacement_profiles.values())).coin_card_ids),68)

    def test_actual_aya_battlecry_pays_once_replaces_original_coins_and_gets_three(self):
        for active in(1,2):
            g=self.game(deck=(COIN,UNIT),enemy_hand=(COIN,),active=active);original=self.eid(g,COIN)
            self.upgrade(g,JADE)
            self.assertEqual(self.held(g),[JADE]*4);self.assertEqual(g.state.entities[original].card_id,JADE)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[active].deck],[JADE,UNIT])
            self.assertEqual(self.held(g,3-active),[COIN])
            self.assertEqual((g.state.players[active].mana,len(g.state.play_history),len(g.state.cast_history)),(4,1,0))

    def test_single_aya_original_deck_forces_second_before_deal_and_overrides_requested_first(self):
        for owner in(1,2):
            g=self.opening((owner,),owner)
            self.assertEqual(g.state.opening.first_player,3-owner)
            self.assertEqual([len(g.state.players[p].hand)for p in(1,2)],[4 if p==owner else 3 for p in(1,2)])
            proof=next(e for e in g.events if e.kind==EVENT)
            self.assertEqual(json.loads(dict(proof.data)['proof'])['mode'],'forced')
            self.portable(g)

    def test_both_aya_decks_use_declared_tie_policy_and_one_normal_second_player_coin(self):
        g=self.opening((1,2));self.assertEqual(g.state.opening.first_player,self.opening((1,2)).state.opening.first_player)
        proof=json.loads(dict(next(e for e in g.events if e.kind==EVENT).data)['proof'])
        self.assertEqual((proof['mode'],proof['qualified_players']),('random',[1,2]))
        second=3-g.state.opening.first_player
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(sum(self.held(g,p).count(COIN)for p in(1,2)),1)
        self.assertIn(COIN,self.held(g,second));self.portable(g)

    def test_no_original_aya_keeps_ordinary_opening_and_later_generated_aya_is_not_an_opening_rule(self):
        g=self.opening((),2);self.assertEqual(g.state.opening.first_player,2)
        self.assertFalse(any(e.kind==EVENT for e in g.events))
        g=self.game();self.upgrade(g);self.assertIsNone(g.state.opening)

    def test_both_original_aya_decks_respect_fixed_tie_without_consuming_first_player_rng(self):
        g=self.opening((1,2),2)
        proof=json.loads(dict(next(e for e in g.events if e.kind==EVENT).data)['proof'])
        self.assertEqual((g.state.opening.first_player,proof['mode']),(2,'fixed'))
        self.assertEqual(proof['rng_before'],proof['rng_after'])

    def test_each_actual_choice_installs_one_permanent_player_program(self):
        for cid in COINS:
            g=self.game();self.upgrade(g,cid)
            program=active_program(g.state,g.registry,1)
            self.assertEqual((program.spec_id,program.remaining_turns),(PREFIX+cid,None))
            self.assertEqual(self.held(g),[cid]*4)

    def test_grimy_coin_keeps_real_mana_then_random_enemy_spell_damage_body(self):
        g=self.game(enemy_board=(UNIT,));self.upgrade(g,GRIMY);self.play(g,GRIMY)
        self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,6)
        self.assertEqual(len(g.state.cast_history),1)

    def test_existing_shadow_mirrors_actual_selected_coin_and_keeps_its_complete_body(self):
        g=self.game((CARD,SHADOW,COIN));self.upgrade(g,KABAL);shadow=self.eid(g,SHADOW)
        self.play(g,KABAL);self.assertEqual(g.state.entities[shadow].card_id,KABAL)
        g.apply(PlayCard(1,shadow))
        self.assertEqual(sum(cid.startswith('potion:')for cid in self.held(g)),2)
        self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_jade_coin_uses_shared_growth_with_classic_and_its_own_real_artwork(self):
        g=self.game((P+'classic',CARD,COIN));self.play(g,P+'classic');self.upgrade(g,JADE);self.play(g,JADE)
        golems=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].jade_size is not None]
        self.assertEqual([e.jade_size for e in golems],[1,2])
        self.assertEqual(golems[-1].card_id,FORMS[0]);self.assertEqual(golems[-1].attack,2)

    def test_kabal_coin_delivers_complete_two_component_potion_after_temporary_mana(self):
        g=self.game();self.upgrade(g,KABAL);self.play(g,KABAL)
        potion=next(cid for cid in self.held(g)if cid.startswith('potion:'))
        self.assertEqual(len(recipe_from_id(potion).parts),2)
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_future_create_and_deck_create_are_replaced_before_delivery_observers(self):
        g=self.game((CARD,P+'get',P+'deck'));self.upgrade(g,KABAL)
        self.play(g,P+'get');self.play(g,P+'deck')
        self.assertEqual(self.held(g).count(KABAL),4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[KABAL])
        self.assertNotIn(COIN,self.held(g));self.portable(g)

    def test_opponent_hand_and_deck_acquisition_keep_physical_card_and_follow_new_holder(self):
        for key in('steal','draw_other'):
            g=self.game((CARD,P+key),enemy_hand=(COIN,),enemy_deck=(COIN,));self.upgrade(g,JADE)
            if key=='steal':
                original=self.eid(g,COIN,2);self.play(g,P+key,original)
            else:
                original=g.state.players[2].deck[0];self.play(g,P+key)
            self.assertEqual(g.state.entities[original].card_id,JADE)
            self.assertEqual(g.state.entities[original].owner,2)
            self.assertEqual(g.state.entities[original].controller,1);self.portable(g)

    def test_copy_and_explicit_transform_into_coin_follow_active_selection(self):
        g=self.game((CARD,P+'copy',P+'transform',FAKE));self.upgrade(g,KABAL)
        original=self.eid(g,FAKE);self.play(g,P+'transform',original)
        self.assertEqual(g.state.entities[original].card_id,KABAL)
        self.play(g,P+'copy',original);self.assertEqual(self.held(g).count(KABAL),5);self.portable(g)

    def test_repeated_real_aya_chooses_new_counterfeit_and_retires_previous_program(self):
        g=self.game((CARD,CARD,COIN))
        self.upgrade(g,JADE)
        # Gain the two mana needed for a second real six-cost Battlecry.
        self.play(g,JADE);self.play(g,JADE)
        self.upgrade(g,KABAL)
        self.assertTrue(all(cid==KABAL for cid in self.held(g)))
        self.assertEqual(active_program(g.state,g.registry,1).spec_id,PREFIX+KABAL)
        self.assertEqual(sum(e.kind==RETIRED for e in g.events),1);self.portable(g)

    def test_bouncing_original_aya_does_not_retire_independent_coin_program(self):
        g=self.game((CARD,P+'bounce',P+'get'));self.upgrade(g,GRIMY)
        source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD)
        self.play(g,P+'bounce',source);self.play(g,P+'get')
        self.assertEqual(self.held(g).count(GRIMY),4)
        self.assertEqual(active_program(g.state,g.registry,1).source_id,source);self.portable(g)

    def test_named_noncoin_is_not_changed_and_future_overflow_burns_selected_physical_face(self):
        g=self.game((CARD,FAKE,COIN));self.upgrade(g,JADE);self.assertIn(FAKE,self.held(g))
        # A full hand after upgrading still creates and burns all real rewards.
        g=self.game((CARD,COIN)+(FAKE,)*8);self.upgrade(g,KABAL)
        self.assertEqual(len(self.held(g)),10)
        burned=[g.state.entities[i]for i in g.state.players[1].graveyard if g.state.entities[i].card_id==KABAL]
        self.assertEqual(len(burned),2)

    def test_waiting_replacement_is_atomic_and_restores_independent_registry_clone_and_replay(self):
        g=self.game(mode='wait',deck=(COIN,));self.upgrade(g,KABAL)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,KABAL)
        self.portable(g,'wait');self.choose(g,'ok');self.assertEqual(self.held(g),[KABAL]*4)

    def test_future_original_coin_overflow_is_transformed_and_burned_as_selected(self):
        g=self.game((CARD,P+'get_two',COIN)+(FAKE,)*7);self.upgrade(g,JADE)
        self.play(g,P+'get_two')
        self.assertEqual(len(self.held(g)),10)
        burned=[g.state.entities[i].card_id for i in g.state.players[1].graveyard]
        self.assertEqual(burned.count(JADE),3);self.assertNotIn(COIN,burned)
        self.portable(g)

    def test_failed_replacement_choice_rolls_back_program_inventory_and_payment_boundary(self):
        g=self.game(mode='fail');self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,KABAL)
        self.assertEqual(g.snapshot(),saved)
        g=self.game(mode='wait');self.upgrade(g,JADE);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok')

    def test_program_requires_actual_aya_battlecry_and_ordinary_removal_is_proved(self):
        g=self.game((P+'forged_program',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'forged_program')
        self.assertEqual(g.snapshot(),saved)
        g=self.game((CARD,P+'remove',P+'get'));self.upgrade(g,JADE);self.play(g,P+'remove');self.play(g,P+'get')
        self.assertIn(COIN,self.held(g));self.assertIsNone(active_program(g.state,g.registry,1));self.portable(g)

    def test_rehashed_missing_program_or_origin_and_changed_selection_are_rejected(self):
        g=self.game();self.upgrade(g,JADE);saved=g.snapshot()
        changed=deepcopy(saved);changed['state']['players']['1']['player_effects']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(changed),fixture())
        changed=deepcopy(saved);changed['state']['players']['1']['player_effects'][0]['spec_id']=PREFIX+KABAL
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(changed),fixture())
        for kind in(ACCEPTED,CHANGED):
            changed=deepcopy(saved);changed['events']=[e for e in changed['events']if e['kind']!=kind]
            with self.subTest(kind=kind),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(changed),fixture())

    def test_original_opening_qualification_and_rng_proof_are_not_player_information(self):
        g=self.opening((1,),1);saved=g.snapshot();event=next(e for e in saved['events']if e['kind']==EVENT)
        proof=json.loads(event['data']['proof']);proof['qualified_players']=[2];event['data']['proof']=json.dumps(proof,sort_keys=True,separators=(',',':'))
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),fixture())
        self.assertNotIn('rng_before',json.dumps(g.observe(1)))

    def test_choice_and_active_program_stay_private_until_actual_coin_is_revealed(self):
        g=self.game();self.upgrade(g,KABAL)
        mine=json.dumps(g.observe(1));other=json.dumps(g.observe(2))
        self.assertIn(PREFIX+KABAL,mine);self.assertNotIn(PREFIX+KABAL,other)
        self.assertNotIn('instance_json',mine);self.assertNotIn('original_decks',other)
        other_hand=next(p for p in g.observe(2)['players']if p['id']==1)['hand']
        self.assertTrue(all('card_id'not in row or row['card_id']is None for row in other_hand))

    def test_jade_primary_display_keeps_both_complete_bodies_and_rejects_rule_drift(self):
        data=load_batch();row=data['dependencies'][0]['record']
        for obs in data['official_observations']:
            if obs['card_id']!=JADE:continue
            decl={'@':'','{0}':''}if obs['locale']=='zh_CN'else{'@':'','{0}':'','{1}':''}
            check_face(row,obs['face'],obs['locale'],decl,numeric_normalizations={'cost':0})
            changed=deepcopy(row);changed['text']+='抽一张牌。';changed['text_en']+=' Draw a card.'
            with self.assertRaises(ValueError):check_face(changed,obs['face'],obs['locale'],decl,numeric_normalizations={'cost':0})


if __name__=='__main__':unittest.main()
