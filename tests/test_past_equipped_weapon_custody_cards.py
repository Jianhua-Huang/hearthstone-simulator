"""Actual Skulker, original equipped material and first-activation semantics."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_equipped_weapon_custody_cards import (
    P as NATIVE,SKULKER,load_batch,register_past_equipped_weapon_custody_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayerSetup,Registry,Scenario,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,Draw,EquipWeapon,
    GainArmor,InvokeBehavior,ModifyWeapon,RequestChoice,ReturnToHand,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.consumed_cards import RETURN_EVENT,ResolveConsumedDeathrattle
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DeathrattleRepeatSpec,RewindSpec
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from tools import card_batch as batch

P='k493.'
HERO,POWER,A,W,OTHER,WATCH,DOUBLE=(P+x for x in('hero','power','a','weapon','other','watch','double'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_equipped_weapon_custody_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior(P+'weapon_battlecry',lambda c:(GainArmor(c.player_id,20),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    r.register_card(CardDefinition(A,A,CardType.MINION,attack=1,health=20,metadata=META))
    r.register_card(CardDefinition(W,W,CardType.WEAPON,cost=2,attack=3,durability=4,
        keywords=(Keyword.LIFESTEAL,),battlecry=P+'weapon_battlecry',deathrattle=P+'armor',metadata=META))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.WEAPON,attack=1,durability=2,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=10,metadata=META,
        deathrattle_repeats=(DeathrattleRepeatSpec(2),)))
    def fail(c):raise ResolutionError('K493 deliberate late native failure')
    r.register_behavior(P+'fail',fail)
    targeted=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        rewind=lambda c:(Destroy(c.target_id,c.source_id),),
        trigger=lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        twice=lambda c:(TriggerDeathrattles(c.target_id,c.source_id,2),),
        full_trigger=lambda c:(Draw(c.player_id,2,c.source_id),TriggerDeathrattles(c.target_id,c.source_id)),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,A),),
        give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),
        base=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),))
    for key,body in targeted.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,metadata=META,
            on_play=P+key,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
            **(dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if key=='rewind'else{})))
    for key,body in dict(equip=lambda c:(EquipWeapon(c.player_id,OTHER),),
            buff_weapon=lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,2,-1,c.source_id),)).items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META))
    if mode=='before_payload_wait':
        original=r._behaviors.pop(NATIVE+'payload')
        def wrapped(c):
            accepted=original(c)
            if not accepted:return ()
            options=(ChoiceOption('continue','Continue'),ChoiceOption('silence','Silence',(Silence(c.source_id),)))
            return(RequestChoice(c.player_id,options,c.source_id),*accepted)
        r.register_behavior(NATIVE+'payload',wrapped)
    def watch(c):
        e=c.event
        relevant=(mode in('take_wait','take_fail')and e.kind=='ability_granted'and
            dict(e.data).get('ability_kind')=='deathrattle'and c.state.entities[e.target_id].card_id==SKULKER or
            mode=='claim_wait'and e.kind==RETURN_EVENT or
            mode in('return_wait','return_fail')and e.kind=='weapon_equipped'and
            c.state.entities[e.target_id].origin_entity_id is not None)
        if not relevant:return ()
        if mode.endswith('fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=tuple(TriggerSpec(k,WATCH)for k in('ability_granted',RETURN_EVENT,'weapon_equipped'))))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return saved


class PastEquippedWeaponCustodyTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),weapon=W,enemy_weapon=None,mode='normal',max_hand=40,deck=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*12 if deck is None else tuple(deck),
            weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,hand=tuple(enemy_hand),
            board=tuple(enemy),weapon_card_id=enemy_weapon,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40)),seed=493),
            fixture(mode),Ruleset(max_hand=max_hand))

    def board(self,g,p=1):return self.entity(g,SKULKER,p,zone='board')
    def weapon(self,g,p=1):return g.state.entities.get(g.state.players[p].weapon_id)
    def take(self,g):return self.play(g,SKULKER)
    def returns(self,g):return[e for e in g.events if e.kind=='weapon_equipped'and g.state.entities[e.target_id].origin_entity_id is not None]
    def claims(self,g):return[e for e in g.events if e.kind==RETURN_EVENT]
    def kill(self,g,target=None,p=1):self.play(g,P+'kill',self.board(g,p).id if target is None else target,player=p)

    def test_full_raw_and_both_primary_faces_and_two_actual_classes(self):
        d=load_batch();raw=d['dependencies'][0]['record'];self.assertEqual(raw['id'],SKULKER)
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(raw,o['face'],o['locale'])
        self.assertEqual(set(fixture().card(SKULKER).metadata.classes),{CardClass.ROGUE,CardClass.DEMON_HUNTER})
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_actual_constructed_boundary_adds_exact_one_full_definition(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_equipped_weapon_custody_cards.register_past_equipped_weapon_custody_cards',
            register_past_equipped_weapon_custody_cards,after=True)
        self.assertEqual(len(r.cards),2694);self.assertEqual(r.card(SKULKER),fixture().card(SKULKER))

    def test_paid_battlecry_hides_current_weapon_gains_stats_and_does_not_kill_it(self):
        g=self.game((SKULKER,));original=self.weapon(g).id;self.take(g);source=self.board(g)
        self.assertEqual((source.attack,source.max_health,g.state.players[1].mana),(4,5,39))
        self.assertIn(Keyword.RUSH,source.keywords);self.assertIsNone(self.weapon(g))
        self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE);self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(g.state.consumed_card_history[0].card.origin.entity_id,original);self.portable(g)

    def test_no_weapon_does_not_search_hand_deck_or_opponent_and_keeps_printed_deathrattle(self):
        g=self.game((SKULKER,W),weapon=None,enemy_weapon=OTHER,deck=(W,A));before=g.snapshot()['rng_state']
        self.assertTrue(any(a.kind=='deathrattle'for a in self.entity(g,SKULKER).abilities));self.take(g)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(1,1))
        self.assertTrue(any(a.kind=='deathrattle'for a in self.board(g).abilities))
        self.assertFalse(g.state.consumed_card_history);self.assertEqual(self.weapon(g,2).card_id,OTHER)
        self.assertEqual(self.entity(g,W).card_id,W);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_summoned_unactivated_source_does_not_take_or_return_a_weapon(self):
        g=self.game((P+'kill',),board=(SKULKER,));original=self.weapon(g).id;self.kill(g)
        self.assertEqual(self.weapon(g).id,original);self.assertFalse(g.state.consumed_card_history)

    def test_natural_death_equips_current_material_without_hand_or_weapon_battlecry(self):
        g=self.game((SKULKER,P+'buff_weapon',P+'kill'));self.play(g,P+'buff_weapon')
        old=self.weapon(g).id;self.take(g);self.assertEqual((self.board(g).attack,self.board(g).max_health),(6,4))
        self.kill(g);weapon=self.weapon(g)
        self.assertEqual((weapon.card_id,weapon.attack,weapon.durability,weapon.origin_entity_id),(W,5,3,old))
        self.assertIn(Keyword.LIFESTEAL,weapon.keywords);self.assertNotEqual(weapon.id,old)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertFalse(any(e.kind=='card_added_to_hand'for e in g.events));self.portable(g)

    def test_later_independent_active_trigger_and_death_do_not_return_again(self):
        g=self.game((SKULKER,P+'trigger',P+'trigger',P+'kill'));self.take(g);host=self.board(g).id
        self.play(g,P+'trigger',host);returned=self.weapon(g).id
        self.play(g,P+'trigger',host);self.kill(g,host)
        self.assertEqual(self.weapon(g).id,returned);self.assertEqual(len(self.returns(g)),1)
        self.assertEqual(len(self.claims(g)),1);self.portable(g)

    def test_two_active_trigger_rounds_are_independent_and_return_only_once(self):
        g=self.game((SKULKER,P+'twice'));self.take(g);self.play(g,P+'twice',self.board(g).id)
        self.assertEqual(len(self.returns(g)),1);self.assertEqual(len(self.claims(g)),1);self.portable(g)

    def test_doubled_first_activation_returns_twice_and_claims_once(self):
        g=self.game((SKULKER,P+'trigger'),board=(DOUBLE,));self.take(g)
        self.play(g,P+'trigger',self.board(g).id)
        self.assertEqual(len(self.returns(g)),2);self.assertEqual(len(self.claims(g)),1)
        self.assertEqual(len([d for d in g.state.death_history if d.zone==Zone.WEAPON]),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_doubled_first_activation_does_not_allow_the_second_trigger_round(self):
        g=self.game((SKULKER,P+'twice'),board=(DOUBLE,));self.take(g)
        self.play(g,P+'twice',self.board(g).id)
        self.assertEqual(len(self.returns(g)),2);self.assertEqual(len(self.claims(g)),1);self.portable(g)

    def test_natural_doubled_first_activation_uses_the_same_original_weapon_material(self):
        g=self.game((SKULKER,P+'kill'),board=(DOUBLE,));self.take(g);self.kill(g)
        self.assertEqual(len(self.returns(g)),2)
        self.assertEqual(len({g.state.entities[e.target_id].origin_entity_id for e in self.returns(g)}),1)

    def test_current_copy_before_first_use_has_independent_payload(self):
        g=self.game((SKULKER,P+'copy',P+'kill',P+'kill'));self.take(g);host=self.board(g).id
        self.play(g,P+'copy',host);copy=g.state.players[1].board[-1]
        self.kill(g,host);self.kill(g,copy);self.assertEqual(len(self.returns(g)),2)
        self.assertEqual(len(self.claims(g)),2);self.portable(g)

    def test_current_copy_after_first_use_inherits_consumption(self):
        g=self.game((SKULKER,P+'trigger',P+'copy',P+'kill'));self.take(g);host=self.board(g).id
        self.play(g,P+'trigger',host);self.play(g,P+'copy',host);self.kill(g,g.state.players[1].board[-1])
        self.assertEqual(len(self.returns(g)),1);self.assertEqual(len(self.claims(g)),1)

    def test_base_copy_does_not_inherit_stored_weapon(self):
        g=self.game((SKULKER,P+'base',P+'kill'));self.take(g);self.play(g,P+'base',self.board(g).id)
        self.kill(g,g.state.players[1].board[-1]);self.assertIsNone(self.weapon(g));self.assertFalse(self.claims(g))

    def test_silence_or_transform_removes_unused_payload_and_gain(self):
        for spell in('silence','transform'):
            g=self.game((SKULKER,P+spell,P+'kill'));self.take(g);host=self.board(g).id
            self.play(g,P+spell,host);self.kill(g,host);self.assertIsNone(self.weapon(g));self.assertFalse(self.claims(g))

    def test_bounce_and_replay_without_weapon_does_not_keep_old_payload(self):
        g=self.game((SKULKER,P+'bounce',P+'kill'));self.take(g);self.play(g,P+'bounce',self.board(g).id)
        self.take(g);self.kill(g);self.assertIsNone(self.weapon(g));self.assertFalse(self.claims(g));self.portable(g)

    def test_stolen_carrier_returns_to_its_death_controller(self):
        g=self.game((SKULKER,P+'give'),enemy_hand=(P+'kill',));old=self.weapon(g).id;self.take(g);host=self.board(g).id
        self.play(g,P+'give',host);g.apply(EndTurn(1));self.kill(g,host,2)
        self.assertIsNone(self.weapon(g));self.assertEqual((self.weapon(g,2).owner,self.weapon(g,2).origin_entity_id),(2,old));self.portable(g)

    def test_return_replaces_intervening_weapon_through_ordinary_death(self):
        g=self.game((SKULKER,P+'equip',P+'kill'));self.take(g);self.play(g,P+'equip');other=self.weapon(g).id
        self.kill(g);self.assertEqual(self.weapon(g).card_id,W)
        self.assertTrue(any(d.entity_id==other and d.zone==Zone.WEAPON for d in g.state.death_history));self.portable(g)

    def test_take_wait_and_late_take_failure_preserve_original_transaction(self):
        for mode in('take_wait','take_fail'):
            g=self.game((SKULKER,),board=(WATCH,),mode=mode);before=g.snapshot()
            if mode=='take_fail':
                with self.assertRaises(ResolutionError):self.take(g)
                self.assertEqual(g.snapshot(),before)
            else:
                self.take(g);self.assertIsNone(self.weapon(g));other=self.portable(g)
                self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_queued_equipment_after_claim_round_trips_with_full_material(self):
        g=self.game((SKULKER,P+'kill'),board=(WATCH,),mode='claim_wait');self.take(g);self.kill(g)
        self.assertIsNone(self.weapon(g));self.assertEqual(len(self.claims(g)),1)
        self.assertIn('EquipWeaponCopy',json.dumps(g.snapshot()['resolution_frame']));other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.weapon(g).card_id,W)

    def test_return_wait_and_failing_choice_restore_consumed_state_without_repeating(self):
        g=self.game((SKULKER,P+'trigger'),board=(WATCH,),mode='return_wait');self.take(g)
        self.play(g,P+'trigger',self.board(g).id);before=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.returns(g)),1);self.portable(g)

    def test_late_equipment_failure_rolls_back_kill_first_claim_and_live_consumption(self):
        g=self.game((SKULKER,P+'kill'),board=(WATCH,),mode='return_fail');self.take(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.kill(g)
        self.assertEqual(g.snapshot(),before);self.assertFalse(self.claims(g));self.portable(g)

    def test_accepted_payload_still_equips_after_original_ability_is_silenced(self):
        g=self.game((SKULKER,P+'trigger'),mode='before_payload_wait');self.take(g)
        self.play(g,P+'trigger',self.board(g).id);other=self.portable(g)
        self.choose(g,'silence');self.choose(other,'silence');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.weapon(g).card_id,W);self.portable(g)

    def test_rehashed_material_first_receipt_and_used_live_payload_reset_are_rejected(self):
        g=self.game((SKULKER,P+'trigger'));self.take(g);host=self.board(g).id
        self.play(g,P+'trigger',host);saved=g.snapshot()
        for kind in('material','claim','reset'):
            bad=deepcopy(saved)
            if kind=='material':bad['state']['consumed_card_history'][0]['card']['origin']['entity_id']=host
            elif kind=='claim':
                event=next(e for e in bad['events']if e['kind']==RETURN_EVENT)
                event['data']['trigger_index']=999
            else:
                row=bad['state']['entities'][str(host)]
                next(a for a in row['abilities']if a['consumed_card_id']is not None)['consumed']=False
            with self.subTest(kind=kind),self.assertRaises(SnapshotError)as caught:
                Game.from_snapshot(rehash(bad),fixture('normal','forgery'))
            self.assertNotIn('digest mismatch',str(caught.exception))
        self.portable(g)

    def test_real_rewind_restores_payload_and_uses_only_new_effective_claim(self):
        from hs_sim.engine.hero_health_history import effective_events
        g=self.game((SKULKER,P+'rewind'));self.take(g);self.play(g,P+'rewind',self.board(g).id)
        self.choose(g,'retry')
        self.assertEqual(self.weapon(g).card_id,W)
        self.assertEqual(len([e for e in effective_events(g.events)if e.kind==RETURN_EVENT]),1)
        self.assertGreater(len(self.claims(g)),1);self.portable(g)

    def test_full_hand_does_not_burn_an_equipment_return_or_reveal_private_storage(self):
        g=self.game((SKULKER,P+'full_trigger',A),max_hand=3);self.take(g)
        self.play(g,P+'full_trigger',self.board(g).id);self.assertEqual(self.weapon(g).card_id,W)
        self.assertEqual(len(g.state.players[1].hand),3)
        self.assertFalse(any(e.kind=='card_burned'for e in g.events))
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            events=json.dumps(g.player_events(player))
            for key in('consumed_card_history','source_material','consumed_weapon_return_claimed'):
                self.assertNotIn(key,view);self.assertNotIn(key,events)
