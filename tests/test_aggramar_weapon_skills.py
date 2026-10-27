"""Native current-weapon grants, physical lifetime and original last attacks."""
from copy import deepcopy
from functools import lru_cache
import json,unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import aggramar_weapon_skills as native
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayerSetup,ResolutionError,Scenario,TriggerSpec,UseMinionAbility)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,EquipWeapon,InvokeBehavior,
    RequestChoice,Silence,TransferWeapon)
from hs_sim.engine.model import EquippedWeaponReference,TargetSpec,Zone
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k614.'
UNIT,SPRINT,ALT,LAST,NOOP,WOUND,BREAK,KILL,MUTE,TAKE,WAIT,ACCEPT,FAIL=(P+x for x in(
    'unit','sprint','alt','last','noop','wound','break','kill','mute','take','wait','accept','fail'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(WOUND,lambda c:(Damage(c.target_id,4,c.source_id),))
    r.register_behavior(BREAK,lambda c:()if c.state.players[c.player_id].weapon_id is None else(
        Destroy(c.state.players[c.player_id].weapon_id,c.source_id),))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_behavior(MUTE,lambda c:(Silence(c.target_id),))
    def take(c):
        wid=c.state.players[3-c.player_id].weapon_id
        return ()if wid is None else(TransferWeapon(EquippedWeaponReference.capture(c.state.entities[wid]),c.player_id,c.source_id),)
    r.register_behavior(TAKE,take)
    def fail(c):raise ResolutionError('K614 deliberate original continuation failure')
    r.register_behavior(FAIL,fail)
    def wait(c):
        if c.state.entities[c.event.source_id].kind!=CardType.HERO:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('replace','Replace',(EquipWeapon(c.player_id,ALT),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    def accept(c):
        if c.state.entities[c.event.source_id].card_id!=native.AGGRAMAR:return ()
        return(RequestChoice(c.event.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('replace','Replace',(EquipWeapon(c.event.player_id,ALT),))),c.source_id),)
    for key,fn in((WAIT,wait),(ACCEPT,accept)):r.register_behavior(key,fn)
    for cid,attack,health,keywords,triggers in(
            (UNIT,8,50,(),()),(SPRINT,1,8,(Keyword.CHARGE,),()),
            (WAIT,0,8,(),(TriggerSpec('attack_finished',WAIT),)),
            (ACCEPT,0,8,(),(TriggerSpec('minion_ability_started',ACCEPT),))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,keywords=keywords,triggers=triggers))
    for cid,attack,durability in((ALT,2,4),(LAST,3,1)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,attack=attack,durability=durability))
    for cid in(NOOP,WOUND,BREAK,KILL,MUTE,TAKE):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec()if cid in(WOUND,KILL,MUTE)else None))
    r.validate();return r


class AggramarWeaponSkillsTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),weapon=None,enemy_weapon=None,enemy_hand=(),player=1):
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else enemy_hand,
            board=board if p==player else enemy_board,weapon_card_id=weapon if p==player else enemy_weapon,
            deck=(NOOP,)*25,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=614),registry())

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def weapon(self,g,p=1):return g.state.entities[g.state.players[p].weapon_id]

    def use(self,g,skill,player=1):
        source=self.entity(g,native.AGGRAMAR,player,'board');mana=g.state.players[player].mana;casts=len(g.state.cast_history)
        g.apply(UseMinionAbility(player,source.id,skill))
        self.assertEqual(g.state.players[player].mana,mana);self.assertEqual(len(g.state.cast_history),casts)
        return source.id

    def next_turn(self,g,player=1):
        g.apply(EndTurn(player));g.apply(EndTurn(3-player))

    def test_nine_complete_raw_rows_twelve_primary_faces_and_explicit_roles(self):
        d=native.load_batch();raws={r['record']['id']:r for key in('cards','dependencies','evidence_only')for r in d[key]}
        self.assertEqual((len(raws),len(d['official_observations'])),(9,12))
        for o in d['official_observations']:
            batch.check_face(raws[o['card_id']]['record'],o['face'],o['locale'],numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        for cid in native.SKILLS:
            self.assertTrue(registry().card(cid).choice_only);self.assertFalse(registry().card(cid).hand_playable)
            self.assertNotIn(cid,registry().pool_cards);self.assertIsNone(raws[cid]['record']['cost'])
        for cid in native.EVIDENCE:
            self.assertEqual(raws[cid]['record']['type'],'ENCHANTMENT');self.assertNotIn(cid,registry().cards)
        self.assertEqual(set(d['new_token_ids']),{native.WEAPON,native.ENFORCER});self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_paid_battlecry_equips_real_three_three_and_replaces_old_weapon_both_seats(self):
        for player in(1,2):
            g=self.game((native.AGGRAMAR,),weapon=ALT,player=player);old=self.weapon(g,player).id
            self.play(g,native.AGGRAMAR,player=player);w=self.weapon(g,player)
            self.assertEqual((w.card_id,w.attack,w.durability),(native.WEAPON,3,3))
            self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[player].mana,24)
            self.assertEqual(len([e for e in g.events if e.kind=='weapon_equipped'and e.target_id==w.id]),1)

    def test_scenario_minion_entry_does_not_invent_a_battlecry(self):
        g=self.game(board=(native.AGGRAMAR,));self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(registry().card(native.ENFORCER).keywords,(Keyword.TAUNT,))

    def test_each_skill_modifies_current_other_weapon_without_name_filter(self):
        for skill in native.SKILLS:
            g=self.game(board=(native.AGGRAMAR,),weapon=ALT);wid=self.weapon(g).id;self.use(g,skill)
            self.assertEqual(g.state.players[1].weapon_id,wid)
            if skill==native.SKILLS[2]:
                self.assertEqual(self.weapon(g).attack,4);self.assertIn(Keyword.IMMUNE_WHILE_ATTACKING,self.weapon(g).keywords)
            else:
                self.assertEqual(len([a for a in self.weapon(g).abilities if a.kind=='trigger'and a.event=='attack_finished']),1)
            self.assertFalse(g.state.cast_history)

    def test_missing_weapon_finishes_once_without_granting_future_equipment(self):
        for skill in native.SKILLS:
            g=self.game((ALT,),board=(native.AGGRAMAR,));source=self.use(g,skill);before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(UseMinionAbility(1,source,skill))
            self.assertEqual(g.snapshot(),before);self.play(g,ALT)
            self.assertEqual(self.weapon(g).attack,2);self.assertFalse(self.weapon(g).abilities)
            self.assertFalse(g.state.players[1].player_effects)

    def test_native_draw_runs_on_all_three_real_hits_including_last_durability(self):
        g=self.game((native.AGGRAMAR,));self.play(g,native.AGGRAMAR);wid=self.weapon(g).id;self.use(g,native.SKILLS[0])
        for n in range(3):
            before=len(g.state.players[1].hand);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
            self.assertEqual(len(g.state.players[1].hand),before+1)
            if n<2:self.next_turn(g)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD)
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn'and e.source_id==wid]),3)
        self.portable(g)

    def test_native_enforcer_runs_on_all_three_hits_and_is_printed_taunt(self):
        g=self.game((native.AGGRAMAR,));self.play(g,native.AGGRAMAR);self.use(g,native.SKILLS[1])
        for n in range(3):
            g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
            tokens=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.ENFORCER]
            self.assertEqual(len(tokens),n+1)
            for token in tokens:self.assertEqual((token.attack,token.health,token.keywords),(3,3,{Keyword.TAUNT}))
            if n<2:self.next_turn(g)
        self.assertIsNone(g.state.players[1].weapon_id)

    def test_swift_slash_immunity_only_protects_real_attacker_and_expires_with_weapon(self):
        g=self.game((native.AGGRAMAR,WOUND,WOUND),enemy_board=(UNIT,));self.play(g,native.AGGRAMAR);self.use(g,native.SKILLS[2])
        target=self.entity(g,UNIT,2,'board').id
        for n in range(3):
            before=self.hero(g).health;g.apply(Attack(1,self.hero(g).id,target));self.assertEqual(self.hero(g).health,before)
            if n==0:
                self.play(g,WOUND,self.hero(g).id);self.assertEqual(self.hero(g).health,before-4)
            if n<2:self.next_turn(g)
        self.assertEqual(g.state.entities[target].health,35);self.assertIsNone(g.state.players[1].weapon_id)
        self.assertNotIn(Keyword.IMMUNE_WHILE_ATTACKING,self.hero(g).keywords)
        before=self.hero(g).health;self.play(g,WOUND,self.hero(g).id);self.assertEqual(self.hero(g).health,before-4)

    def test_weapon_grant_survives_silencing_or_destroying_original_titan(self):
        for removal in(MUTE,KILL):
            g=self.game((removal,),board=(native.AGGRAMAR,),weapon=native.WEAPON);source=self.use(g,native.SKILLS[0])
            self.play(g,removal,source);before=len(g.state.players[1].hand)
            g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id));self.assertEqual(len(g.state.players[1].hand),before+1)

    def test_destroyed_weapon_grant_does_not_follow_later_replacement(self):
        g=self.game((BREAK,ALT),board=(native.AGGRAMAR,),weapon=native.WEAPON);wid=self.weapon(g).id
        self.use(g,native.SKILLS[0]);self.play(g,BREAK);self.play(g,ALT);before=len(g.state.players[1].hand)
        g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id));self.assertEqual(len(g.state.players[1].hand),before)
        self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD)

    def test_minion_and_opponent_hero_attacks_do_not_fire_owners_grant(self):
        g=self.game(board=(native.AGGRAMAR,SPRINT),weapon=native.WEAPON,enemy_weapon=ALT)
        wid=self.weapon(g).id;self.use(g,native.SKILLS[0]);before=len(g.state.players[1].hand)
        g.apply(Attack(1,self.entity(g,SPRINT,zone='board').id,self.hero(g,2).id))
        self.assertEqual(len(g.state.players[1].hand),before);g.apply(EndTurn(1))
        g.apply(Attack(2,self.hero(g,2).id,self.hero(g).id))
        self.assertFalse([e for e in g.events if e.kind=='card_drawn'and e.source_id==wid])

    def test_three_real_grants_transfer_with_physical_weapon_to_actual_new_controller(self):
        g=self.game(board=(native.AGGRAMAR,UNIT),weapon=native.WEAPON,enemy_hand=(TAKE,))
        for n,skill in enumerate(native.SKILLS):
            self.use(g,skill)
            if n<2:self.next_turn(g)
        wid=self.weapon(g).id;g.apply(EndTurn(1));self.play(g,TAKE,player=2)
        self.assertEqual(g.state.players[2].weapon_id,wid);before=len(g.state.players[2].hand);hp=self.hero(g,2).health
        g.apply(Attack(2,self.hero(g,2).id,self.entity(g,UNIT,zone='board').id))
        self.assertEqual(self.hero(g,2).health,hp);self.assertEqual(len(g.state.players[2].hand),before+1)
        self.assertEqual(self.entity(g,native.ENFORCER,2,'board').controller,2);self.portable(g)

    def test_full_board_blocks_enforcer_allocation_but_keeps_original_wear(self):
        g=self.game(board=(native.AGGRAMAR,)+(UNIT,)*6,weapon=native.WEAPON);self.use(g,native.SKILLS[1])
        before=g.state.next_entity_id;g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual(g.state.next_entity_id,before);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(self.weapon(g).durability,2)

    def test_original_last_swing_wait_failure_restore_and_replacement_preserve_one_reward(self):
        g=self.game((LAST,),board=(native.AGGRAMAR,WAIT));self.play(g,LAST)
        wid=self.weapon(g).id;self.assertLess(self.entity(g,WAIT,zone='board').entered_order,self.weapon(g).entered_order)
        self.use(g,native.SKILLS[0])
        g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id));waiting=g.snapshot();before=len(g.state.players[1].hand)
        restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),waiting)
        self.choose(g,'replace');self.choose(restored,'replace');self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.players[1].hand),before+1);self.assertEqual(self.weapon(g).card_id,ALT)
        self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD);self.portable(g)

    def test_ability_wait_modifies_new_current_weapon_after_actual_replacement(self):
        g=self.game(board=(native.AGGRAMAR,ACCEPT),weapon=native.WEAPON);old=self.weapon(g).id
        self.use(g,native.SKILLS[2]);self.portable(g);self.choose(g,'replace')
        self.assertEqual(self.weapon(g).card_id,ALT);self.assertEqual(self.weapon(g).attack,4)
        self.assertIn(Keyword.IMMUNE_WHILE_ATTACKING,self.weapon(g).keywords)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)

    def test_actual_complete_local_host_all_three_skills_and_generated_faces_restore(self):
        fmt=build_cn37_local_pool_format()
        for skill in native.SKILLS:
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(native.AGGRAMAR,),deck=('CORE_EX1_028',)*4,mana=10,max_mana=10),
                PlayerSetup('HERO_08')),seed=614,generation_context=fmt.context),fmt.registry)
            source=self.play(g,native.AGGRAMAR);g.apply(UseMinionAbility(1,source,skill))
            before=len(g.state.players[1].hand);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
            if skill==native.SKILLS[0]:self.assertEqual(len(g.state.players[1].hand),before+1)
            if skill==native.SKILLS[1]:self.assertEqual(self.entity(g,native.ENFORCER,zone='board').attack,3)
            self.assertEqual(Game.from_snapshot(g.snapshot(),fmt.registry).snapshot(),g.snapshot())
            for player in(1,2):
                view=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())
                for key in('zone_epoch','resolution_frame','rng_state','hand_entry_id'):self.assertNotIn('"'+key+'"',view)

    def test_bad_final_skill_cannot_half_register_native_cards_or_behaviors(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.aggramar_weapon_skills.register_aggramar_weapon_skills',lambda r:None)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='MINION';before=r.fingerprint()
        with patch.object(native,'load_batch',lambda:data),self.assertRaises(TargetValidationError):native.register_aggramar_weapon_skills(r)
        self.assertEqual(r.fingerprint(),before)


if __name__=='__main__':unittest.main()
