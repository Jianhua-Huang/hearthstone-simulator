"""Lightcaller's real weapon damage and two original Lifesteal restorations."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards.lightcaller_card import CARD,load_batch,register_lightcaller_card
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,EquipWeapon,GrantKeyword,InvokeBehavior,
    ModifyWeapon,RequestChoice,TransferWeapon)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.lifesteal_recipients import LifestealRecipientProfile
from hs_sim.engine.model import (CardClass,CardMetadata,DamageKind,EquippedWeaponReference,
    HealthFlow,HealthLayer,HealthOp,HealthRule)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from tools.card_batch import canonical,check_face

P='fixture.lightcaller.'
NEAR=P+'near_lethal'
FILL,TINY,SHIELD,LIFE,OLD,VANILLA,WOUND,WEAR,SWAP,TRANSFER,DRAIN,HERO_DAMAGE,WEAPON_DAMAGE,WATCH=(P+x for x in
    ('fill','tiny','shield','life','old','vanilla','wound','wear','swap','transfer','drain','hero_damage','weapon_damage','watch'))
DOUBLE,INCOMING,PREVENT,CONVERT,REDUCE=(P+x for x in ('double','incoming','prevent','convert','reduce'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    assert role in ('writer','reader')
    r=build_registry();register_lightcaller_card(r)
    for cid,attack,health,keywords in ((FILL,3,12,()),(TINY,0,1,()),
            (SHIELD,0,12,(Keyword.DIVINE_SHIELD,)),(LIFE,2,8,(Keyword.LIFESTEAL,Keyword.CHARGE))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,keywords=keywords,metadata=META))
    r.register_card(CardDefinition(OLD,OLD,CardType.WEAPON,cost=3,attack=4,durability=2,
        keywords=(Keyword.LIFESTEAL,),metadata=META))
    r.register_card(CardDefinition(VANILLA,VANILLA,CardType.WEAPON,cost=1,attack=1,durability=2,metadata=META))
    def hero(c,pid=None):return c.state.players[c.player_id if pid is None else pid].hero_id
    def weapon(c):return EquippedWeaponReference.capture(c.state.entities[c.state.players[c.player_id].weapon_id])
    def hero_damage(c):
        return (GrantKeyword(hero(c),Keyword.LIFESTEAL,c.source_id),
            Damage(hero(c,3-c.player_id),2,hero(c),DamageKind.EFFECT))
    bodies={WOUND:lambda c:(LoseHealth(hero(c),12,c.source_id),LoseHealth(hero(c,3-c.player_id),8,c.source_id)),
        NEAR:lambda c:(LoseHealth(hero(c),28,c.source_id),LoseHealth(hero(c,3-c.player_id),28,c.source_id)),
        WEAR:lambda c:(ModifyWeapon(weapon(c),durability=-1,source_id=c.source_id),),
        SWAP:lambda c:(EquipWeapon(c.player_id,VANILLA),),
        TRANSFER:lambda c:(TransferWeapon(weapon(c),3-c.player_id,c.source_id),),
        DRAIN:lambda c:(Damage(hero(c,3-c.player_id),2,c.source_id,DamageKind.SPELL),),
        HERO_DAMAGE:hero_damage,
        WEAPON_DAMAGE:lambda c:(Damage(hero(c,3-c.player_id),2,weapon(c).entity_id),)}
    for cid,fn in bodies.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            keywords=(Keyword.LIFESTEAL,) if cid==DRAIN else ()))
    rules={DOUBLE:HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly'),
        INCOMING:HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,layer=HealthLayer.TARGET,target_relation='friendly'),
        PREVENT:HealthRule(HealthFlow.HEALING,HealthOp.PREVENT,source_relation='friendly'),
        CONVERT:HealthRule(HealthFlow.HEALING,HealthOp.CONVERT,source_relation='friendly'),
        REDUCE:HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,1,denominator=4,layer=HealthLayer.TARGET,
            target_relation='friendly',target_kinds=(CardType.HERO,),damage_kinds=(DamageKind.COMBAT,))}
    for cid,rule in rules.items():
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=12,health_rules=(rule,),metadata=META))
    def fail(c):raise ResolutionError('Lightcaller deliberate failure')
    r.register_behavior(P+'fail',fail)
    if mode:
        def watch(c):
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec('lifesteal',WATCH),)))
    return r


class LightcallerTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(WOUND,CARD),board=(),enemy=(),armor=0,seat=1):
        self.mode,self.seat=mode,seat
        own=PlayerSetup('HERO_08',hand=hand,board=board+((WATCH,) if mode else ()),deck=(FILL,)*6,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',board=enemy,deck=(FILL,)*6,armor=armor,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=374),fixture(mode))
    def play(self,g,cid=CARD):
        pid=self.seat;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def ready(self,*args,weapon=CARD,**kw):
        g=self.game(*args,**kw);self.play(g,WOUND);self.play(g,weapon);return g
    def hero(self,g,pid=None):return g.state.entities[g.state.players[self.seat if pid is None else pid].hero_id]
    def healths(self,g):return (self.hero(g).health,self.hero(g,3-self.seat).health)
    def weapon(self,g,pid=None):
        eid=g.state.players[self.seat if pid is None else pid].weapon_id
        return None if eid is None else g.state.entities[eid]
    def attack(self,g,target=None):
        return g.apply(Attack(self.seat,self.hero(g).id,self.hero(g,3-self.seat).id if target is None else target))
    def lifes(self,result):return [e for e in result.events if e.kind=='lifesteal']
    def restore(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in (g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original damage credit and two separate healing results must restore')
        return Game.from_snapshot(s,r)

    def test_complete_source_and_two_primary_faces_keep_real_three_mana_four_two_weapon(self):
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(canonical(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        card=fixture().card(CARD);self.assertEqual((card.cost,card.attack,card.durability),(3,4,2))
        self.assertEqual(card.keywords,(Keyword.LIFESTEAL,));self.assertFalse(d['cn_calibrated'])

    def test_paid_weapon_play_equips_real_entity_with_native_lifesteal_and_one_policy(self):
        g=self.game();eid=self.play(g)
        self.assertEqual((self.weapon(g).id,self.weapon(g).card_id,self.weapon(g).attack,self.weapon(g).durability),(eid,CARD,4,2))
        self.assertEqual(g.state.players[1].mana,7);self.assertIn(Keyword.LIFESTEAL,self.hero(g).keywords)
        self.assertEqual(tuple(g.registry.lifesteal_recipient_profiles),(CARD,))

    def test_hero_attack_heals_both_from_one_damage_and_keeps_original_source_credit(self):
        g=self.ready();wid=self.weapon(g).id;result=self.attack(g)
        self.assertEqual(self.healths(g),(22,22));self.assertEqual(self.weapon(g).durability,1)
        events=self.lifes(result);self.assertEqual([e.target_id for e in events],[self.hero(g).id,self.hero(g,2).id])
        self.assertTrue(all((e.source_id,e.player_id,e.amount)==(self.hero(g).id,1,4) for e in events))
        damage=[r.health_result for r in g.state.damage_history if r.health_result.damage_dealt]
        self.assertEqual(len(damage),1);self.assertEqual(damage[0].weapon_id,wid)
        rows=[r.health_result for r in g.state.healing_history];self.assertEqual(len(rows),2)
        self.assertTrue(all(r.from_lifesteal and r.source_controller==1 and r.healed==4 for r in rows))
        self.restore(g)

    def test_minion_combat_keeps_retaliation_and_heals_enemy_hero_without_healing_minion(self):
        g=self.ready(enemy=(FILL,));eid=g.state.players[2].board[0];self.attack(g,eid)
        self.assertEqual(self.healths(g),(19,26));self.assertEqual(g.state.entities[eid].health,8)
        self.assertEqual([r.health_result.healed for r in g.state.healing_history],[4,4])

    def test_armor_damage_also_restores_both_heroes_from_actual_dealt_amount(self):
        g=self.ready(armor=10);self.attack(g)
        self.assertEqual(self.healths(g),(22,26));self.assertEqual(self.hero(g,2).armor,6)
        result=next(r.health_result for r in g.state.damage_history if r.health_result.damage_dealt)
        self.assertEqual((result.damage_dealt,result.armor_absorbed),(4,4))

    def test_prevented_shield_damage_does_not_create_either_restoration(self):
        g=self.ready(enemy=(SHIELD,));result=self.attack(g,g.state.players[2].board[0])
        self.assertEqual(self.healths(g),(18,22));self.assertFalse(self.lifes(result));self.assertFalse(g.state.healing_history)
        self.assertEqual(self.weapon(g).durability,1)

    def test_overkill_uses_actual_dealt_not_remaining_minion_health(self):
        g=self.ready(enemy=(TINY,));eid=g.state.players[2].board[0];self.attack(g,eid)
        self.assertEqual(self.healths(g),(22,26));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.damage_history[0].health_result.damage_dealt,4)

    def test_target_damage_reduction_changes_both_healing_amounts(self):
        g=self.ready(enemy=(REDUCE,));self.attack(g)
        self.assertEqual(self.healths(g),(19,22));self.assertEqual(g.state.damage_history[0].health_result.damage_dealt,1)
        self.assertEqual([r.health_result.healed for r in g.state.healing_history],[1,1])

    def test_source_healing_multiplier_quotes_two_original_restorations(self):
        g=self.ready(board=(DOUBLE,));result=self.attack(g)
        self.assertEqual(self.healths(g),(26,26));self.assertEqual([dict(e.data)['healed'] for e in self.lifes(result)],[8,8])

    def test_recipient_healing_multiplier_applies_to_that_hero_only(self):
        g=self.ready(enemy=(INCOMING,));self.attack(g)
        self.assertEqual(self.healths(g),(22,26))
        self.assertEqual([r.health_result.modified_amount for r in g.state.healing_history],[4,8])

    def test_healing_conversion_hits_both_once_without_recursive_lifesteal(self):
        g=self.ready(board=(CONVERT,));result=self.attack(g)
        self.assertEqual(self.healths(g),(14,14));self.assertEqual(len(self.lifes(result)),2)
        self.assertTrue(all(dict(e.data)['converted'] for e in self.lifes(result)))
        self.assertEqual(sum(r.health_result.from_lifesteal for r in g.state.damage_history),2)

    def test_healing_prevention_preserves_two_separate_original_attempts(self):
        g=self.ready(board=(PREVENT,));result=self.attack(g)
        self.assertEqual(self.healths(g),(18,18));self.assertEqual(len(self.lifes(result)),2)
        self.assertEqual(sum(e.kind=='healing_prevented' for e in result.events),2)

    def test_full_hero_still_has_original_overheal_result_instead_of_redirecting_to_other_hero(self):
        g=self.game(hand=(CARD,));self.play(g);self.attack(g)
        self.assertEqual(self.healths(g),(30,30));rows=[r.health_result for r in g.state.healing_history]
        self.assertEqual([(r.healed,r.overheal) for r in rows],[(0,4),(4,0)])

    def test_lethal_enemy_damage_or_retaliation_keeps_existing_same_batch_rescue_local_policy(self):
        for enemy,expected in (((),(6,2)),((FILL,),(3,6))):
            with self.subTest(enemy=enemy):
                g=self.game(hand=(NEAR,CARD),enemy=enemy);self.play(g,NEAR);self.play(g)
                target=g.state.players[2].board[0] if enemy else None;self.attack(g,target)
                self.assertEqual(self.healths(g),expected);self.assertEqual(g.state.status,'playing')
                self.assertEqual(len(g.state.healing_history),2)
                self.assertTrue(any(r.health_result.health_before<=0 for r in g.state.healing_history))

    def test_last_durability_heals_both_before_original_weapon_breaks_and_histories_restore(self):
        g=self.ready(hand=(WOUND,CARD,WEAR));wid=self.weapon(g).id;self.play(g,WEAR);self.attack(g)
        self.assertIsNone(self.weapon(g));self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD)
        self.assertEqual(self.healths(g),(22,22));self.restore(g)

    def test_replacing_weapon_removes_both_hero_policy_from_later_combat(self):
        g=self.ready(hand=(WOUND,CARD,SWAP));self.play(g,SWAP);result=self.attack(g)
        self.assertEqual((self.weapon(g).card_id,self.healths(g)),(VANILLA,(18,21)))
        self.assertFalse(self.lifes(result));self.assertFalse(g.state.healing_history)

    def test_ordinary_lifesteal_weapon_still_heals_only_its_controller(self):
        g=self.ready(weapon=OLD,hand=(WOUND,OLD));result=self.attack(g)
        self.assertEqual(self.healths(g),(22,18));self.assertEqual(len(self.lifes(result)),1)

    def test_equipped_lightcaller_does_not_extend_minion_spell_or_noncombat_hero_lifesteal(self):
        g=self.ready(hand=(WOUND,CARD,DRAIN,HERO_DAMAGE),board=(LIFE,))
        for cid in (DRAIN,HERO_DAMAGE):
            before=len(g.state.healing_history);self.play(g,cid);self.assertEqual(len(g.state.healing_history)-before,1)
        result=g.apply(Attack(1,g.state.players[1].board[0],self.hero(g,2).id))
        self.assertEqual(len(self.lifes(result)),1);self.assertEqual(self.healths(g),(24,16))
        self.assertEqual(self.weapon(g).durability,2)

    def test_effect_damage_credited_directly_to_original_weapon_uses_its_native_recipients(self):
        g=self.ready(hand=(WOUND,CARD,WEAPON_DAMAGE));wid=self.weapon(g).id;self.play(g,WEAPON_DAMAGE)
        self.assertEqual(self.healths(g),(20,22));self.assertEqual(self.weapon(g).durability,2)
        self.assertEqual([r.health_result.source_id for r in g.state.healing_history],[wid,wid])

    def test_weapon_transfer_uses_actual_new_controller_and_original_two_hero_damage_credit(self):
        g=self.ready(hand=(WOUND,CARD,TRANSFER));wid=self.weapon(g).id;self.play(g,TRANSFER)
        self.assertIsNone(self.weapon(g));self.assertEqual(self.weapon(g,2).id,wid)
        g.apply(EndTurn(1));self.seat=2;result=self.attack(g)
        self.assertEqual(self.healths(g),(26,18));self.assertTrue(all(e.player_id==2 for e in self.lifes(result)))
        self.assertTrue(all(r.health_result.source_controller==2 for r in g.state.healing_history));self.restore(g)

    def test_two_lifesteal_reactions_wait_after_both_results_and_restore_without_rehealing(self):
        g=self.ready('wait');self.attack(g);count=0
        while g.state.pending_choice:
            count+=1;self.assertEqual(self.healths(g),(22,22));self.assertEqual(len(g.state.healing_history),2)
            g=self.restore(g);q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(count,2);self.assertEqual(self.weapon(g).durability,1)

    def test_failed_attack_and_choice_preserve_existing_transaction_boundaries(self):
        g=self.ready('fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.attack(g)
        self.assertTrue(g.snapshot()==before)
        g=self.ready('wait');self.attack(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertTrue(g.snapshot()==before);self.assertEqual(self.healths(g),(22,22))

    def test_second_seat_public_views_hide_internal_profiles_and_original_health_receipts(self):
        g=self.ready('wait',seat=2);self.attack(g);self.assertEqual(self.healths(g),(22,22))
        for pid in (1,2):
            text=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in ('lifesteal_recipient_profiles','resolution_frame','rng_state','rule_ids','health_rule'):
                self.assertNotIn(private,text)

    def test_profile_is_immutable_typed_weapon_only_and_changes_registry_identity(self):
        r=build_registry();register_lightcaller_card(r)
        with self.assertRaisesRegex(ValueError,'Duplicate'):r.register_lifesteal_recipient_profile(LifestealRecipientProfile(CARD))
        with self.assertRaises(ValueError):LifestealRecipientProfile(CARD,'all_characters')
        with self.assertRaises(ValueError):r.register_lifesteal_recipient_profile({'card_id':CARD})
        r.register_card(CardDefinition(LIFE,LIFE,CardType.MINION,health=1,keywords=(Keyword.LIFESTEAL,)))
        with self.assertRaises(ValueError):r.register_lifesteal_recipient_profile(LifestealRecipientProfile(LIFE))
        with self.assertRaises(TypeError):r.lifesteal_recipient_profiles[CARD]=None
        old=r.fingerprint();r._lifesteal_recipient_profiles.clear();self.assertNotEqual(r.fingerprint(),old)
