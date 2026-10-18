"""Native weapon Battlecry, printed hero restriction and temporal stat layer."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.infinite_weapon_attack_card import CARD,INFINITE_ATTACK_VALUE,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,IllegalAction,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,Zone)
from hs_sim.engine.effects import (ChoiceOption,EquipWeapon,InvokeBehavior,ModifyWeapon,
    RequestChoice,TransferWeapon)
from hs_sim.engine.equipment import SetWeaponAttackForTurn
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EquippedWeaponReference,LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay

P='infinity.weapon.test.'
FILL,VANILLA,WATCH,AUTO,SWAP,BUFF,TRANSFER,PENDING,BAD=(P+x for x in (
    'fill','vanilla','watch','auto','swap','buff','transfer','pending','bad'))


@lru_cache(maxsize=None)
def registry(mode,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(collectible=False,classes=(CardClass.NEUTRAL,),rarity=Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=2,health=30,metadata=meta))
    r.register_card(CardDefinition(VANILLA,VANILLA,CardType.WEAPON,attack=1,durability=3,metadata=meta))
    def current(c):return EquippedWeaponReference.capture(c.state.entities[c.state.players[1].weapon_id])
    def fail(c):raise ResolutionError('Infinite weapon deliberate choice failure')
    r.register_behavior(P+'fail',fail)
    def choice(c):
        return RequestChoice(1,(ChoiceOption('ok','Continue'),
            ChoiceOption('replace','Equip another same face',(EquipWeapon(1,CARD),)),
            ChoiceOption('swap','Equip ordinary weapon',(EquipWeapon(1,VANILLA),)),
            ChoiceOption('transfer','Transfer original',(TransferWeapon(current(c),2,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id)
    def pending(c):return (choice(c),SetWeaponAttackForTurn(current(c),9,c.state.turn,c.source_id))
    bodies={AUTO:lambda c:(EquipWeapon(c.player_id,CARD),),SWAP:lambda c:(EquipWeapon(c.player_id,VANILLA),),
        BUFF:lambda c:(ModifyWeapon(current(c),attack=2,source_id=c.source_id),),
        TRANSFER:lambda c:(TransferWeapon(current(c),2,c.source_id),),
        PENDING:pending,BAD:lambda c:(SetWeaponAttackForTurn(current(c),9,c.state.turn+1,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    if mode:
        event='battlecry_started' if mode=='before' else 'weapon_equipped' if mode=='prior' else 'weapon_changed'
        def eligible(c):
            target=c.state.entities.get(c.event.source_id if mode=='before' else c.event.target_id)
            return target is not None and target.card_id==CARD and target.controller==1
        def body(c):
            target=c.state.entities[c.event.source_id if mode=='before' else c.event.target_id]
            if mode=='prior':return (ModifyWeapon(EquippedWeaponReference.capture(target),attack=2,source_id=c.source_id),)
            return (choice(c),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'pause',body)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec(event,P+'pause',condition_id=P+'eligible'),)))
    r.validate();r.freeze();return r


class InfiniteWeaponAttackTests(unittest.TestCase):
    def game(self,hand=(),enemy=(),mode=None,existing=False):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=(FILL,)*12,
            weapon_card_id=CARD if existing else None,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=((WATCH,) if mode else ())+enemy,deck=(FILL,)*12,
                mana=50,max_mana=50,mana_cap=50)),seed=121151),registry(mode,'writer'))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def weapon(self,g,pid=1):return g.state.entities[g.state.players[pid].weapon_id]
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry(self.mode,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,r).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),r).snapshot(),snap)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('resolution_frame','source_allocation','rng_state','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
    def test_a00_paid_native_battlecry_sets_only_original_weapon_and_current_hero(self):
        g=self.game((CARD,));wid=self.play(g,CARD)
        self.assertEqual((self.weapon(g).id,self.weapon(g).attack,self.weapon(g).durability),(wid,INFINITE_ATTACK_VALUE,2))
        self.assertEqual((self.hero(g).attack,g.state.players[1].mana),(INFINITE_ATTACK_VALUE,47))
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
    def test_a01_native_minion_attack_uses_set_value_and_ordinary_retaliation_wear(self):
        g=self.game((CARD,),enemy=(FILL,));self.play(g,CARD);target=g.state.players[2].board[0]
        g.apply(Attack(1,self.hero(g).id,target))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual((self.hero(g).health,self.weapon(g).durability),(28,1));self.portable(g)
    def test_a02_printed_restriction_rejects_enemy_hero_without_spending_attack(self):
        g=self.game((CARD,));self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_a03_end_of_original_turn_removes_set_but_keeps_printed_restriction(self):
        g=self.game((CARD,));self.play(g,CARD);g.apply(EndTurn(1))
        self.assertEqual((self.weapon(g).attack,self.hero(g).attack),(4,0))
        g.apply(EndTurn(2));self.assertEqual(self.hero(g).attack,4)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.portable(g)
    def test_a04_generated_automatic_equipment_has_printed_four_attack_without_battlecry(self):
        g=self.game((AUTO,));self.play(g,AUTO)
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(4,2));self.assertFalse(g.state.battlecry_history)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.portable(g)
    def test_a05_existing_scenario_equipment_does_not_invent_battlecry(self):
        g=self.game(existing=True);self.assertEqual(self.weapon(g).attack,4)
        self.assertFalse(g.state.battlecry_history);self.portable(g)
    def test_b00_original_prior_buff_is_overridden_then_restored_by_ordinary_expiry(self):
        g=self.game((CARD,),mode='prior');self.play(g,CARD)
        self.assertEqual(self.weapon(g).attack,INFINITE_ATTACK_VALUE)
        g.apply(EndTurn(1));self.assertEqual(self.weapon(g).attack,6);self.portable(g)
    def test_b01_later_permanent_buff_survives_expiration_of_temporary_set(self):
        g=self.game((CARD,BUFF));self.play(g,CARD);self.play(g,BUFF)
        g.apply(EndTurn(1));self.assertEqual(self.weapon(g).attack,6);self.portable(g)
    def test_b02_pre_body_replacement_does_not_set_a_different_current_weapon(self):
        g=self.game((CARD,),mode='before');old=self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'swap')
        self.assertEqual((self.weapon(g).card_id,self.weapon(g).attack),(VANILLA,1))
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)
    def test_b03_after_set_wait_restores_and_does_not_move_material_to_new_same_face(self):
        g=self.game((CARD,),mode='after');old=self.play(g,CARD);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'replace')
        self.assertNotEqual(self.weapon(g).id,old);self.assertEqual(self.weapon(g).attack,4)
        self.assertEqual(g.state.entities[old].attack,INFINITE_ATTACK_VALUE);self.portable(g)
    def test_c00_transfer_keeps_original_this_turn_expiry_and_current_equipment_policy(self):
        g=self.game((CARD,TRANSFER));wid=self.play(g,CARD);self.play(g,TRANSFER)
        self.assertEqual((self.weapon(g,2).id,self.weapon(g,2).attack,self.hero(g,2).attack),(wid,INFINITE_ATTACK_VALUE,0))
        g.apply(EndTurn(1));self.assertEqual((self.weapon(g,2).attack,self.hero(g,2).attack),(4,4))
        with self.assertRaises(IllegalAction):g.apply(Attack(2,self.hero(g,2).id,self.hero(g).id))
        self.portable(g)
    def test_c01_pending_typed_set_restores_original_request_and_applies_once(self):
        g=self.game((AUTO,PENDING));self.play(g,AUTO);self.play(g,PENDING);self.portable(g)
        self.choose(g);self.assertEqual(self.weapon(g).attack,9);self.portable(g)
    def test_c02_pending_set_skips_later_same_face_equipment(self):
        g=self.game((AUTO,PENDING));self.play(g,AUTO);old=self.weapon(g).id;self.play(g,PENDING)
        self.portable(g);self.choose(g,'replace');self.assertNotEqual(self.weapon(g).id,old)
        self.assertEqual(self.weapon(g).attack,4);self.assertEqual(g.state.entities[old].attack,4);self.portable(g)
    def test_c03_pending_set_skips_same_physical_weapon_after_control_installation_changes(self):
        g=self.game((AUTO,PENDING));self.play(g,AUTO);old=self.weapon(g).id;self.play(g,PENDING)
        self.choose(g,'transfer');self.assertEqual(self.weapon(g,2).id,old)
        self.assertEqual(self.weapon(g,2).attack,4);self.portable(g)
    def test_c04_replacement_retires_old_hero_attack_restriction(self):
        g=self.game((CARD,SWAP));self.play(g,CARD);self.play(g,SWAP)
        g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,29);self.portable(g)
    def test_d00_two_native_weapon_battlecries_keep_two_independent_original_enchantments(self):
        g=self.game((CARD,CARD));first=self.play(g,CARD);second=self.play(g,CARD)
        self.assertNotEqual(first,second);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(g.state.players[1].mana,44)
        g.apply(EndTurn(1));self.assertEqual([g.state.entities[i].attack for i in (first,second)],[4,4]);self.portable(g)
    def test_z00_non_current_turn_request_fails_with_full_action_rollback(self):
        g=self.game((AUTO,BAD));self.play(g,AUTO);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)
    def test_z01_full_source_numeric_policy_and_request_validation(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(data['policy']['infinite_attack_value'],INFINITE_ATTACK_VALUE)
        g=self.game(existing=True);ref=EquippedWeaponReference.capture(self.weapon(g))
        SetWeaponAttackForTurn(ref,9,1)
        for args in ((ref,-1,1),(ref,True,1),(ref,9,0),(ref.entity_id,9,1)):
            with self.assertRaises(ValueError):SetWeaponAttackForTurn(*args)


if __name__=='__main__':unittest.main()
