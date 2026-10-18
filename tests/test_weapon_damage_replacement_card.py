"""Finite physical durability replacement through normal damage transactions."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.weapon_damage_replacement_card import CARD, load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayerSetup, PlayCard, Rarity, Scenario, SelectChoice, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, Draw, EquipWeapon, GainArmor,
    GrantHealthRule, GrantKeyword, Heal, InvokeBehavior, ModifyWeapon, RequestChoice, TransferWeapon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import (EquippedWeaponReference, HealthFlow, HealthLayer, HealthOp,
    HealthRule, LimitedTriggerSpec)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.weapon_damage_replacement import RULE,validate_carrier,validate_definition

P='bulwark.test.'
FILL,VANILLA,WATCH=(P+x for x in ('fill','vanilla','watch'))
HIT,FIVE,ZERO,ARMOR,LOSE,HEAL,DRAW,MINION,ENEMY,IMMUNE,PREVENT,BUFF,TRANSFER,SWAP,BAD,MIXED,WOUND,TAIL=(
    P+x for x in ('hit','five','zero','armor','lose','heal','draw','minion','enemy','immune',
        'prevent','buff','transfer','swap','bad','mixed','wound','tail'))


@lru_cache(maxsize=None)
def registry(wait,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(collectible=False,classes=(CardClass.NEUTRAL,),rarity=Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=2,health=30,metadata=meta))
    r.register_card(CardDefinition(VANILLA,VANILLA,CardType.WEAPON,attack=1,durability=3,metadata=meta))
    def hero(c,pid=None):return c.state.players[c.player_id if pid is None else pid].hero_id
    def damage(c,n):return Damage(hero(c),n,c.source_id)
    def batch(c):return DamageBatch(tuple(damage(c,7) for _ in range(5)))
    def weapon(c):return EquippedWeaponReference.capture(c.state.entities[c.state.players[c.player_id].weapon_id])
    ordinary=HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,layer=HealthLayer.TARGET,target_relation='self',target_kinds=(CardType.HERO,))
    bodies={HIT:lambda c:(damage(c,7),),FIVE:lambda c:(batch(c),),ZERO:lambda c:(damage(c,0),),
        ARMOR:lambda c:(GainArmor(c.player_id,10),),LOSE:lambda c:(LoseHealth(hero(c),4,c.source_id),),
        HEAL:lambda c:(Heal(hero(c),3,c.source_id),),DRAW:lambda c:(Draw(c.player_id,5,c.source_id),),
        MINION:lambda c:(Damage(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==FILL),7,c.source_id),),
        ENEMY:lambda c:(Damage(hero(c,3-c.player_id),7,c.source_id),),
        IMMUNE:lambda c:(GrantKeyword(hero(c),Keyword.IMMUNE,c.source_id,c.state.turn),),
        PREVENT:lambda c:(GrantHealthRule(hero(c),ordinary,c.source_id),),
        BUFF:lambda c:(ModifyWeapon(weapon(c),durability=2,source_id=c.source_id),),
        TRANSFER:lambda c:(TransferWeapon(weapon(c),3-c.player_id,c.source_id),),
        SWAP:lambda c:(EquipWeapon(c.player_id,VANILLA),),BAD:lambda c:(GrantHealthRule(hero(c),RULE,c.source_id),),
        MIXED:lambda c:(DamageBatch((Damage(c.state.players[c.player_id].board[0],3,c.source_id),damage(c,6),
            Damage(hero(c,3-c.player_id),3,c.source_id),damage(c,8))),),
        WOUND:lambda c:(LoseHealth(hero(c,3-c.player_id),10,c.source_id),),
        TAIL:lambda c:(batch(c),damage(c,1))}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    def fail(c):raise ResolutionError('Bulwark deliberate continuation failure')
    r.register_behavior(P+'fail',fail)
    if wait:
        def eligible(c):
            e=c.state.entities.get(c.event.target_id)
            return e is not None and e.card_id==CARD and dict(c.event.data).get('durability')==3
        def pause(c):
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('replace','Equip a new Bulwark',(EquipWeapon(1,CARD),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'pause',pause)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec('weapon_changed',P+'pause',condition_id=P+'eligible'),)))
    r.validate();r.freeze();return r


class WeaponDamageReplacementTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),wait=False,empty_deck=False):
        self.wait=wait;deck=() if empty_deck else (FILL,)*12
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=((WATCH,) if wait else ())+enemy,
            deck=deck,mana=50,max_mana=50,mana_cap=50)),seed=781),registry(wait,'writer'))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def weapon(self,g,pid=1):
        eid=g.state.players[pid].weapon_id
        return None if eid is None else g.state.entities[eid]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry(self.wait,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,r).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),r).snapshot(),snap)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('resolution_frame','rule_ids','health_rule','rng_state'):
                self.assertNotIn('"'+key+'"',public)
    def test_a00_paid_weapon_blocks_positive_damage_with_one_real_durability(self):
        g=self.game((CARD,HIT));wid=self.play(g,CARD);self.play(g,HIT)
        self.assertEqual(g.state.players[1].mana,47)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(30,3))
        self.assertEqual(self.weapon(g).id,wid);self.portable(g)
    def test_a01_fifth_simultaneous_hit_passes_after_four_charges(self):
        g=self.game((CARD,FIVE));wid=self.play(g,CARD);self.play(g,FIVE)
        self.assertEqual(self.hero(g).health,23);self.assertIsNone(self.weapon(g))
        self.assertEqual((g.state.entities[wid].zone,g.state.entities[wid].durability),(Zone.GRAVEYARD,0))
        outcomes=[dict(e.data)['result'] for e in g._events if e.kind=='health_resolved']
        self.assertEqual(len(outcomes),5);self.portable(g)
    def test_a02_guard_preserves_armor_before_any_absorption(self):
        g=self.game((ARMOR,CARD,HIT));self.play(g,ARMOR);self.play(g,CARD);self.play(g,HIT)
        self.assertEqual((self.hero(g).health,self.hero(g).armor,self.weapon(g).durability),(30,10,3));self.portable(g)
    def test_a03_zero_damage_healing_and_direct_health_loss_do_not_pay_durability(self):
        g=self.game((CARD,ZERO,LOSE,HEAL));self.play(g,CARD);self.play(g,ZERO);self.play(g,LOSE);self.play(g,HEAL)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(29,4));self.portable(g)
    def test_a04_other_friendly_minions_and_enemy_hero_are_not_guarded(self):
        g=self.game((CARD,MINION,ENEMY),board=(FILL,));self.play(g,CARD);self.play(g,MINION);self.play(g,ENEMY)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,23)
        self.assertEqual((self.hero(g,2).health,self.weapon(g).durability),(23,4));self.portable(g)
    def test_a05_mixed_simultaneous_targets_only_consume_own_hero_packets(self):
        g=self.game((CARD,MIXED),board=(FILL,));self.play(g,CARD);self.play(g,MIXED)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health,self.weapon(g).durability),(30,27,2));self.portable(g)
    def test_a06_actual_fatigue_uses_four_charges_then_deals_fifth_damage(self):
        g=self.game((CARD,DRAW),empty_deck=True);self.play(g,CARD);self.play(g,DRAW)
        self.assertEqual(g.state.players[1].fatigue,5);self.assertEqual(self.hero(g).health,25)
        self.assertIsNone(self.weapon(g));self.portable(g)
    def test_b00_ordinary_immunity_prevents_damage_without_spending_durability(self):
        g=self.game((CARD,IMMUNE,HIT));self.play(g,CARD);self.play(g,IMMUNE);self.play(g,HIT)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(30,4));self.portable(g)
    def test_b01_existing_rule_prevention_does_not_spend_weapon_resource(self):
        g=self.game((CARD,PREVENT,HIT));self.play(g,CARD);self.play(g,PREVENT);self.play(g,HIT)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(30,4));self.portable(g)
    def test_b02_attacking_a_minion_pays_guard_and_ordinary_attack_wear(self):
        g=self.game((CARD,),enemy=(FILL,));self.play(g,CARD)
        g.apply(Attack(1,self.hero(g).id,g.state.players[2].board[0]))
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(30,2));self.portable(g)
    def test_b03_last_guard_charge_during_attack_finishes_original_weapon(self):
        g=self.game((CARD,HIT,HIT,HIT),enemy=(FILL,));wid=self.play(g,CARD)
        for _ in range(3):self.play(g,HIT)
        self.assertEqual(self.weapon(g).durability,1)
        g.apply(Attack(1,self.hero(g).id,g.state.players[2].board[0]))
        self.assertEqual(self.hero(g).health,30);self.assertIsNone(self.weapon(g))
        self.assertLessEqual(g.state.entities[wid].durability,0);self.portable(g)
    def test_b04_prevented_attack_does_not_produce_lifesteal_healing(self):
        g=self.game((CARD,WOUND),enemy=('CATA_432t2',));self.play(g,WOUND);self.play(g,CARD)
        g.apply(EndTurn(1));g.apply(Attack(2,g.state.players[2].board[0],self.hero(g).id))
        self.assertEqual((self.hero(g).health,self.hero(g,2).health,self.weapon(g).durability),(30,20,3));self.portable(g)
    def test_c00_replacement_with_an_ordinary_weapon_retires_old_guard(self):
        g=self.game((CARD,SWAP,HIT));old=self.play(g,CARD);self.play(g,SWAP);self.play(g,HIT)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(self.weapon(g).card_id,VANILLA)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)
    def test_c01_transfer_protects_current_controller_and_not_original_owner(self):
        g=self.game((CARD,TRANSFER,ENEMY,HIT));wid=self.play(g,CARD);self.play(g,TRANSFER)
        self.play(g,ENEMY);self.play(g,HIT)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(23,30))
        self.assertEqual((self.weapon(g,2).id,self.weapon(g,2).durability),(wid,3));self.portable(g)
    def test_c02_actual_durability_buff_provides_six_independent_charges(self):
        g=self.game((CARD,BUFF,FIVE,HIT,HIT));self.play(g,CARD);self.play(g,BUFF);self.play(g,FIVE)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(30,1))
        self.play(g,HIT);self.play(g,HIT);self.assertEqual(self.hero(g).health,23);self.portable(g)
    def test_d00_wait_after_batch_keeps_all_original_numeric_changes_and_rolls_back_bad_choice(self):
        g=self.game((CARD,TAIL),wait=True);self.play(g,CARD);self.play(g,TAIL)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,23)
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g)
        self.assertEqual(self.hero(g).health,22);self.portable(g)
    def test_d01_new_weapon_during_wait_only_protects_later_independent_packet(self):
        g=self.game((CARD,TAIL),wait=True);old=self.play(g,CARD);self.play(g,TAIL);self.portable(g)
        self.choose(g,'replace');self.assertEqual(self.hero(g).health,23)
        self.assertNotEqual(self.weapon(g).id,old);self.assertEqual(self.weapon(g).durability,3);self.portable(g)
    def test_z00_generic_grant_rejects_intrinsic_guard_and_rolls_back(self):
        g=self.game((BAD,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)
    def test_z01_exact_definition_carrier_and_rule_scope_reject_fabricated_grants(self):
        g=self.game((CARD,));self.play(g,CARD);w=self.weapon(g)
        validate_carrier(g.registry,CARD,CardType.WEAPON,w.abilities)
        with self.assertRaises(ValueError):validate_carrier(g.registry,CARD,CardType.MINION,w.abilities)
        with self.assertRaises(ValueError):validate_carrier(g.registry,CARD,CardType.WEAPON,
            tuple(replace(a,origin='granted') if a.kind=='health_rule' else a for a in w.abilities))
        with self.assertRaises(ValueError):validate_definition(CardDefinition(P+'invalid','Invalid',CardType.MINION,health=1,health_rules=(RULE,)))
        for values in ({'flow':HealthFlow.HEALING},{'amount':2},{'target_relation':'any'},{'target_kinds':(CardType.MINION,)},{'layer':HealthLayer.SOURCE}):
            with self.assertRaises(ValueError):replace(RULE,**values)
    def test_z02_full_core_source_and_real_copy_identity_are_retained(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(data['cards'][0]['record']['tags']['DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'],57721)
        g=self.game();self.assertEqual(g.registry.card(CARD).metadata.deck_identity,'BT_781')
        self.assertNotIn('BT_781',g.registry.cards)


if __name__=='__main__':unittest.main()
