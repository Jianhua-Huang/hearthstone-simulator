"""Four real Dragon dependencies and a finite random-location primitive."""
from dataclasses import replace
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.dragon_native_effect_cards import FLOWER,TURTLE,CRUMBLE,CONFLUX,ROOTS,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseLocation,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dark_gifts import GrantDarkGift
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,EquipWeapon,
    InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec,ChoicePurpose,DamageKind,TribeChangeSpec
from hs_sim.engine.locations import RandomDestroyLocation
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';LOC='CORE_REV_990';LOC2='SC_403';AXE='TLC_478'


def registry():
    r=build_registry()
    def gift(c,enemy=False):
        p=3-c.player_id if enemy else c.player_id
        cards=[c.state.entities[i]for i in c.state.players[p].hand if c.state.entities[i].kind==CardType.MINION]
        target=next((e for e in cards if e.card_id==YETI),cards[0])
        return(GrantDarkGift(CardReference.capture(target),'EDR_100t3',c.source_id),)
    def ids(c):return tuple(c.state.players[3-c.player_id].board)
    def wait(c,fail=False):
        tail=(InvokeBehavior('k85.fail',c.source_id,c.player_id),)if fail else()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(RandomDestroyLocation(ids(c),c.source_id),*tail)),),source_id=c.source_id),)
    scripts=dict(silence=lambda c:(Silence(c.target_id),),
        transfer=lambda c:(ChangeControl(c.target_id,2),),
        tribe=lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('dragon',)),c.source_id),),
        gift=gift,gift_enemy=lambda c:gift(c,True),loc=lambda c:(RandomDestroyLocation(ids(c),c.source_id),),
        locwait=wait,locwaitfail=lambda c:wait(c,True),loc_unknown=lambda c:(RandomDestroyLocation((),999999),),
        wound=lambda c:(Damage(c.state.players[2].hero_id,23,c.source_id,DamageKind.EFFECT),))
    for key,body in scripts.items():
        name='k85.'+key;r.register_behavior(name,body)
        r.register_card(CardDefinition(name,key,CardType.SPELL,on_play=name,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if key in('silence','transfer','tribe')else None))
    r.register_behavior('k85.fail',lambda c:(AddToHand(c.player_id,'unknown.k85'),))
    r.register_behavior('k85.noop',lambda c:())
    r.register_card(CardDefinition('k85.all','All tribes',CardType.MINION,attack=2,health=5,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('all',))))
    r.register_card(CardDefinition('k85.unknown_tribes','Unknown tribes',CardType.MINION,health=5))
    r.register_card(CardDefinition('k85.brann','Repeat',CardType.MINION,health=8,battlecry_repeats=(BattlecryRepeatSpec(),)))
    r.register_card(CardDefinition('k85.bonus','Spell damage',CardType.MINION,health=8,spell_damage=9))
    r.register_card(CardDefinition('k85.weapon','Weapon',CardType.WEAPON,attack=2,durability=3))
    r.register_behavior('k85.equip_wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('equip','Equip a new weapon',(EquipWeapon(c.player_id,'k85.weapon'),)),),source_id=c.source_id),))
    r.register_card(CardDefinition('k85.loc_wait','Waiting location',CardType.LOCATION,durability=2,
        on_use='k85.noop',deathrattle='k85.equip_wait'))
    r.register_card(CardDefinition('k85.loc_fail','Failing location',CardType.LOCATION,durability=2,
        on_use='k85.noop',deathrattle='k85.fail'))
    def kill(c):
        target=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==CRUMBLE),None)
        return()if target is None else(Destroy(target),)
    r.register_behavior('k85.kill_crumble',kill)
    r.register_card(CardDefinition('k85.death','Death test',CardType.MINION,health=1,deathrattle='k85.kill_crumble'))
    def damage_wait(c):
        e=c.event
        if e.source_id not in c.state.entities or c.state.entities[e.source_id].card_id!=CONFLUX:return()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),),source_id=c.source_id),)
    r.register_behavior('k85.damage_wait',damage_wait)
    r.register_card(CardDefinition('k85.damage_watch','Watch',CardType.MINION,health=8,
        triggers=(TriggerSpec('damage_dealt','k85.damage_wait'),)))
    return r


class DragonNativeEffectCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=(),weapon=None,enemy_weapon=None,seed=85):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,
                        weapon_card_id=weapon,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,
                        weapon_card_id=enemy_weapon,hero_power_card_id='HERO_08bp'),
        ),seed=seed),self.r)
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','RandomDestroyLocation','CardReference','next_attachment_id'):
                self.assertNotIn(key,public)
        return other
    def rng(self,g):
        state=g.snapshot()['rng_state'];rng=Random();rng.setstate((state[0],tuple(state[1]),state[2]));return rng

    def test_complete_pins_four_roots_dual_tribes_and_rewind(self):
        data=load_batch();self.assertEqual(tuple(x['record']['id']for x in data['cards']),ROOTS)
        self.assertFalse(data['dependencies']);self.assertEqual(len(data['evidence_only']),2)
        for row in data['cards']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in data['cards']:
            raw=row['record'];card=self.r.card(raw['id'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=card.id))
        self.assertEqual(set(self.r.card(TURTLE).metadata.tribes),{'beast','dragon'})
        self.assertIn(Keyword.REWIND,self.r.card(CONFLUX).keywords);self.assertEqual(self.r.card(CONFLUX).rewind.retries,1)

    def test_flower_owner_end_buffs_only_other_friendly_dragon(self):
        g=self.game((FLOWER,),(TURTLE,YETI),(TURTLE,));friend=g.state.players[1].board[0]
        source=self.play(g,FLOWER);g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[friend].attack,g.state.entities[friend].health),(4,7))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,4))
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].attack,3)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[friend].attack,4)

    def test_flower_empty_pool_does_not_use_rng(self):
        g=self.game((FLOWER,));self.play(g,FLOWER);rng=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_flower_current_tribe_and_all_tribe_are_physical_candidates(self):
        g=self.game(('k85.tribe',),(FLOWER,YETI,'k85.all'))
        target=g.state.players[1].board[1];self.play(g,'k85.tribe',target)
        expected=self.rng(g).choice(sorted(g.state.players[1].board[1:]));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[expected].attack,5 if expected==target else 3)

    def test_flower_unknown_tribes_raise_instead_of_silent_nonmatch(self):
        g=self.game(board=(FLOWER,'k85.unknown_tribes'));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown current tribe'):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),saved)

    def test_flower_silence_removes_trigger(self):
        g=self.game(('k85.silence',),(FLOWER,TURTLE));self.play(g,'k85.silence',g.state.players[1].board[0]);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[1].board[1]].attack,3)

    def test_flower_control_change_uses_new_owner_end_and_friendly_board(self):
        g=self.game(('k85.transfer',),(FLOWER,TURTLE),(TURTLE,));source=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.play(g,'k85.transfer',source);g.apply(EndTurn(1));self.assertEqual(g.state.entities[enemy].attack,3)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[enemy].attack,4);self.portable(g)

    def test_turtle_without_real_held_gift_has_no_reward(self):
        for hand in((TURTLE,),(TURTLE,'CORE_EX1_008')):
            g=self.game(hand);self.play(g,TURTLE);self.assertEqual((self.hero(g).attack,self.hero(g).armor),(0,0))

    def test_turtle_held_gift_gives_real_armor_and_this_turn_attack(self):
        g=self.game(('k85.gift',TURTLE,YETI));self.play(g,'k85.gift');self.play(g,TURTLE)
        self.assertEqual((self.hero(g).attack,self.hero(g).armor),(3,6));self.assertEqual(g.state.players[1].mana,36)
        g.apply(EndTurn(1));self.assertEqual((self.hero(g).attack,self.hero(g).armor),(0,6));self.portable(g)

    def test_turtle_own_played_gift_and_enemy_held_gift_do_not_qualify(self):
        g=self.game(('k85.gift',TURTLE));self.play(g,'k85.gift');self.play(g,TURTLE)
        self.assertEqual((self.hero(g).attack,self.hero(g).armor),(0,0))
        h=self.game(('k85.gift_enemy',TURTLE),enemy_hand=(YETI,));self.play(h,'k85.gift_enemy');self.play(h,TURTLE)
        self.assertEqual((self.hero(h).attack,self.hero(h).armor),(0,0))

    def test_turtle_two_real_battlecries_stack_reward_with_one_payment(self):
        g=self.game(('k85.gift',TURTLE,YETI),('k85.brann',));self.play(g,'k85.gift');self.play(g,TURTLE)
        self.assertEqual((self.hero(g).attack,self.hero(g).armor),(6,12));self.assertEqual(g.state.players[1].mana,36)
        g.apply(EndTurn(1));self.assertEqual((self.hero(g).attack,self.hero(g).armor),(0,12))

    def test_crumble_destroys_one_enemy_of_each_type_without_friendly_loss(self):
        g=self.game((CRUMBLE,),(YETI,LOC),(YETI,LOC),weapon=AXE,enemy_weapon=AXE)
        doomed=tuple(g.state.players[2].board)+(g.state.players[2].weapon_id,);own=tuple(g.state.players[1].board);weapon=g.state.players[1].weapon_id
        self.play(g,CRUMBLE);self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in doomed))
        self.assertTrue(all(i in g.state.players[1].board for i in own));self.assertEqual(g.state.players[1].weapon_id,weapon)
        self.assertEqual(g.state.players[1].mana,32);self.portable(g)

    def test_crumble_random_minion_and_location_use_original_rng_in_stage_order(self):
        g=self.game((CRUMBLE,),enemy=(YETI,TURTLE,LOC,LOC2),enemy_weapon=AXE)
        board=g.state.players[2].board;mins=board[:2];locs=board[2:];rng=self.rng(g)
        chosen=(rng.choice(sorted(mins)),rng.choice(sorted(locs)));self.play(g,CRUMBLE)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in chosen))
        self.assertEqual(g.snapshot()['rng_state'],[rng.getstate()[0],list(rng.getstate()[1]),rng.getstate()[2]])
        self.assertEqual([e.target_id for e in g.events if e.kind=='random_choice'],list(chosen))

    def test_crumble_missing_minion_and_location_still_destroys_weapon_without_rng(self):
        g=self.game((CRUMBLE,),enemy_weapon=AXE);weapon=g.state.players[2].weapon_id;rng=g.snapshot()['rng_state'];self.play(g,CRUMBLE)
        self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_crumble_can_destroy_cooling_location(self):
        g=self.game((CRUMBLE,),enemy=(YETI,LOC));yeti,location=g.state.players[2].board
        g.apply(EndTurn(1));g.apply(UseLocation(2,location,yeti));g.apply(EndTurn(2))
        self.assertGreater(g.state.entities[location].location_cooldown,0);self.play(g,CRUMBLE)
        self.assertEqual(g.state.entities[location].zone,Zone.GRAVEYARD)

    def test_crumble_location_deathrattle_wait_then_requeries_equipped_weapon(self):
        g=self.game((CRUMBLE,),enemy=('k85.loc_wait',),enemy_weapon=AXE);old=g.state.players[2].weapon_id
        self.play(g,CRUMBLE);self.assertEqual(g.state.pending_choice.player_id,2);other=self.portable(g)
        self.choose(g,'equip');self.choose(other,'equip');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        new=[e for e in g.state.entities.values()if e.card_id=='k85.weapon'];self.assertEqual(len(new),1);self.assertEqual(new[0].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_crumble_accepted_tail_survives_source_death(self):
        g=self.game((CRUMBLE,),enemy=('k85.death',LOC),enemy_weapon=AXE);loc=g.state.players[2].board[1]
        source=self.play(g,CRUMBLE);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[loc].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[2].weapon_id)

    def test_crumble_late_location_failure_rolls_back_entire_play(self):
        g=self.game((CRUMBLE,),enemy=(YETI,'k85.loc_fail'),enemy_weapon=AXE);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CRUMBLE)
        self.assertEqual(g.snapshot(),saved)

    def test_random_location_request_filters_other_types_and_uses_existing_death(self):
        g=self.game(('k85.loc',),enemy=(YETI,LOC));yeti,location=g.state.players[2].board;self.play(g,'k85.loc')
        self.assertIn(yeti,g.state.players[2].board);self.assertEqual(g.state.entities[location].zone,Zone.GRAVEYARD)
        self.assertEqual(sum(d.card_id==LOC for d in g.state.death_history),1)

    def test_random_location_empty_pool_does_not_consume_rng(self):
        g=self.game(('k85.loc',),enemy=(YETI,));rng=g.snapshot()['rng_state'];self.play(g,'k85.loc')
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_random_location_waiting_branch_codec_restore_and_replay(self):
        g=self.game(('k85.locwait',),enemy=(LOC,LOC2));self.play(g,'k85.locwait');other=self.portable(g)
        codec=FrameCodec(g.mechanics,self.r);work=RandomDestroyLocation(tuple(g.state.players[2].board),g.state.players[1].hero_id)
        self.assertEqual(codec.decode(codec.encode(work)),work);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[2].board),1)

    def test_random_location_failed_choice_restores_original_rng_and_locations(self):
        g=self.game(('k85.locwaitfail',),enemy=(LOC,LOC2));self.play(g,'k85.locwaitfail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_random_location_unknown_source_fails_even_when_empty(self):
        g=self.game(('k85.loc_unknown',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k85.loc_unknown')
        self.assertEqual(g.snapshot(),saved)

    def test_random_location_constructor_rejects_mutable_duplicate_and_invalid_ids(self):
        for values in([1],(1,1),(True,),(0,)):
            with self.subTest(values=values),self.assertRaises(ValueError):RandomDestroyLocation(values)

    def test_conflux_damage_is_minion_ability_and_not_spell_damage(self):
        g=self.game((CONFLUX,),('k85.bonus',));self.play(g,CONFLUX)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.choose(g,'keep')
        row=g.state.damage_history[-1].health_result
        self.assertEqual((row.damage_dealt,row.spell_bonus,row.damage_kind),(7,0,'minion_ability'))
        self.assertEqual(self.hero(g,2).health,23);self.assertEqual(g.state.players[1].mana,33)

    def test_conflux_repeat_excludes_enemy_already_killed_in_first_battlecry(self):
        g=self.game((CONFLUX,),('k85.brann',),(YETI,),seed=0);victim=g.state.players[2].board[0]
        self.play(g,CONFLUX);self.choose(g,'keep')
        self.assertEqual([x.health_result.target_id for x in g.state.damage_history],[victim,g.state.players[2].hero_id])
        self.assertEqual(self.hero(g,2).health,23);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)

    def test_conflux_retry_reverts_first_result_and_keeps_rng_progress_one_final_payment(self):
        g=self.game((CONFLUX,),enemy=(YETI,),seed=7);victim=g.state.players[2].board[0]
        self.play(g,CONFLUX);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);rng=g.snapshot()['rng_state']
        other=self.portable(g);self.choose(g,'retry');self.choose(other,'retry');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,33)
        self.assertEqual(g.state.entities[victim].zone,Zone.BOARD);self.assertEqual(g.state.entities[victim].health,5)
        self.assertEqual(self.hero(g,2).health,23);self.assertNotEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_conflux_damage_wait_resumes_before_real_rewind_choice(self):
        g=self.game((CONFLUX,),('k85.damage_watch',));self.play(g,CONFLUX)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.choose(g,'keep');self.portable(g)

    def test_conflux_terminal_damage_does_not_offer_rewind(self):
        g=self.game(('k85.wound',CONFLUX));self.play(g,'k85.wound');self.play(g,CONFLUX)
        self.assertEqual(g.state.winner,1);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_previous_schema_is_explicitly_rejected(self):
        g=self.game();saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaisesRegex(SnapshotError,f'1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
