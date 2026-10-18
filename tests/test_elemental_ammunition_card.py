"""Tiny Pal's real weapon faces, completed attacks and physical choice continuation."""
from dataclasses import replace
from functools import lru_cache
import json,random,unittest

from hs_sim.cards import build_registry
from hs_sim.cards.elemental_ammunition_card import CARD,FORMS,ROOTS,POOL,EARTH,AIR,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,IllegalAction,Keyword,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,Zone)
from hs_sim.engine.battlecry_sources import RepeatBattlecry
from hs_sim.engine.effects import (ChoiceOption,Damage,EquipWeapon,GrantKeyword,InvokeBehavior,
    ModifyWeapon,RequestChoice,TransferWeapon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EquippedWeaponReference,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.weapon_forms import RefaceEquippedWeapon
from hs_sim.targets import canonical_digest

P='tiny.pal.test.'
FILL,THREE,OTHER,BC,FIVE,VANILLA,WATCH,UNKNOWN=(P+x for x in (
    'fill','three','other','battlecry','five','vanilla','watch','unknown'))
AUTO,BUFF,WEAR,SWAP,REPEAT,PENDING,PING=(P+x for x in (
    'auto','buff','wear','swap','repeat','pending','ping'))
CTX=GenerationContext('tiny-pal-explicit-experiment','experimental')
MEMBERS=(THREE,OTHER,BC,FIVE)


@lru_cache(maxsize=None)
def registry(mode,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=30,metadata=meta))
    r.register_card(CardDefinition(VANILLA,VANILLA,CardType.WEAPON,attack=1,durability=4,metadata=meta))
    r.register_behavior(P+'noop',lambda c:())
    for cid,cost,bc in ((THREE,3,False),(OTHER,3,False),(BC,5,True),(FIVE,5,False)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,
            battlecry=P+'noop' if bc else None,metadata=replace(meta,collectible=True))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    members=MEMBERS if mode!='unknown' else (UNKNOWN,)
    if mode=='unknown':r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,replace(meta,collectible=True)))
    if mode=='empty':members=(FIVE,)
    r.register_pool(PoolDefinition(POOL,'tiny-pal-explicit-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(c)for c in members),complete=True))
    def current(c):return EquippedWeaponReference.capture(c.state.entities[c.state.players[1].weapon_id])
    def fail(c):raise ResolutionError('Tiny Pal deliberate continuation failure')
    r.register_behavior(P+'fail',fail)
    def menu(c,label='Continue'):
        return RequestChoice(1,(ChoiceOption('ok',label),
            ChoiceOption('swap','Replace weapon',(EquipWeapon(1,VANILLA),)),
            ChoiceOption('transfer','Transfer weapon',(TransferWeapon(current(c),2,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id)
    def repeat(c):
        original=next(x for x in c.state.battlecry_history if x.card_id==CARD and x.origin=='hand')
        return (RepeatBattlecry(c.player_id,c.source_id,original.id),)
    def pending(c):return (menu(c),RefaceEquippedWeapon(current(c),FORMS[1],c.source_id))
    bodies={AUTO:lambda c:(EquipWeapon(c.player_id,CARD),),
        BUFF:lambda c:(ModifyWeapon(current(c),attack=3,durability=2,source_id=c.source_id),
            GrantKeyword(current(c).entity_id,Keyword.LIFESTEAL,c.source_id)),
        WEAR:lambda c:(ModifyWeapon(current(c),durability=-2,source_id=c.source_id),),
        SWAP:lambda c:(EquipWeapon(c.player_id,VANILLA),),REPEAT:repeat,PENDING:pending,
        PING:lambda c:(Damage(c.state.players[2].hero_id,29,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        if cid==REPEAT:r.register_card(CardDefinition(cid,cid,CardType.MINION,health=3,battlecry=cid,metadata=meta))
        else:r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    if mode=='freeze':
        def observed(c):
            count=sum(c.state.entities[i].frozen for i in (c.state.players[2].hero_id,*c.state.players[2].board))
            return (menu(c,str(count)),)
        r.register_behavior(P+'observe',observed)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec('frozen',P+'observe'),)))
    r.validate();r.freeze();return r


class ElementalAmmunitionTests(unittest.TestCase):
    def game(self,hand=(),face=None,enemy=(),board=(),mode=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,
            board=((WATCH,)if mode=='freeze'else())+board,weapon_card_id=face,deck=(FILL,)*12,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,
            deck=(FILL,)*12,mana=50,max_mana=50,mana_cap=50)),seed=222458,generation_context=CTX),registry(mode,'writer'))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,position=0 if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def weapon(self,g,pid=1):
        wid=g.state.players[pid].weapon_id
        return g.state.entities[wid]if wid is not None else None
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def attack(self,g,target=None):
        if target is None:target=g.state.players[2].board[0]if g.state.players[2].board else self.hero(g,2).id
        g.apply(Attack(1,self.hero(g).id,target))
    def portable(self,g):
        r=registry(self.mode,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('rng_state','resolution_frame','source_allocation','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def test_a00_complete_real_source_all_four_forms_and_primary_faces(self):
        data=load_batch();r=registry(None,'writer')
        self.assertEqual(tuple(x['record']['id']for x in data['cards']+data['dependencies']),ROOTS)
        for row in data['cards']+data['dependencies']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            d=r.card(row['record']['id']);self.assertEqual((d.kind,d.cost,d.attack,d.durability),(CardType.WEAPON,4,2,3))
            self.assertEqual(d.metadata.deck_identity,CARD)
        self.assertEqual(len(data['official_observations']),10)
        self.assertTrue(r.card(CARD).battlecry);self.assertTrue(all(r.card(c).battlecry is None for c in FORMS))
        self.assertFalse(data['policy']['formal_pool_complete']);self.assertFalse(data['policy']['cn_calibrated'])
    def test_a01_paid_battlecry_four_choices_same_physical_weapon_single_payment(self):
        g=self.game((CARD,));wid=self.play(g,CARD)
        self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),FORMS)
        self.assertEqual((self.weapon(g).id,g.state.players[1].mana),(wid,46));other=self.portable(g)
        for game in (g,other):self.choose(game,FORMS[1])
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual((self.weapon(g).id,self.weapon(g).card_id,self.weapon(g).durability),(wid,FORMS[1],3))
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
    def test_a02_actual_fire_attack_wear_excludes_only_current_and_allows_return(self):
        g=self.game((CARD,),enemy=(FILL,FILL));wid=self.play(g,CARD);self.choose(g,FORMS[1]);target=g.state.players[2].board[0]
        self.attack(g,target)
        self.assertEqual((g.state.entities[target].health,self.hero(g,2).health,self.weapon(g).durability),(27,29,2))
        self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),(FORMS[0],FORMS[2],FORMS[3]))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,FORMS[1])
        self.assertEqual(g.snapshot(),saved);self.choose(g,FORMS[0]);self.assertEqual(self.weapon(g).id,wid)
        with self.assertRaises(IllegalAction):self.attack(g,target)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.attack(g,target)
        self.assertIn(FORMS[1],tuple(o.id for o in g.state.pending_choice.options));self.choose(g,FORMS[1])
        self.assertEqual((self.weapon(g).id,self.weapon(g).durability),(wid,1))
        self.assertEqual(self.hero(g,2).health,29);self.portable(g)
    def test_a03_last_durability_fire_still_fires_without_new_choice(self):
        g=self.game((WEAR,),face=FORMS[1],enemy=(FILL,));wid=self.weapon(g).id;self.play(g,WEAR);self.attack(g)
        self.assertEqual(self.hero(g,2).health,29);self.assertIsNone(self.weapon(g));self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD);self.portable(g)
    def test_a04_auto_equipped_root_no_initial_ammunition_but_attack_offers_four(self):
        g=self.game((AUTO,),enemy=(FILL,));self.play(g,AUTO);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.battlecry_history);self.attack(g)
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),FORMS)
        self.assertEqual(self.weapon(g).durability,2);self.portable(g)
    def test_a05_lethal_fire_ends_game_before_ammunition_choice(self):
        g=self.game((PING,),face=FORMS[1],enemy=(FILL,));self.play(g,PING);self.attack(g)
        self.assertEqual(g.state.winner,1);self.assertIsNone(g.state.pending_choice);self.portable(g)
    def test_b00_frost_uses_two_distinct_other_current_enemies_and_exact_rng(self):
        g=self.game(face=FORMS[0],enemy=(FILL,FILL,FILL));target=g.state.players[2].board[0]
        candidates=(self.hero(g,2).id,*g.state.players[2].board[1:]);rng=random.Random();rng.setstate(g._rng.getstate())
        expected=set(rng.sample(candidates,2));self.attack(g,target)
        actual={i for i in (self.hero(g,2).id,*g.state.players[2].board)if g.state.entities[i].frozen}
        self.assertEqual(actual,expected);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertFalse(g.state.entities[target].frozen)
        self.portable(g)
    def test_b01_both_freezes_apply_before_first_observer_wait_and_failed_resume(self):
        g=self.game(face=FORMS[0],enemy=(FILL,FILL),mode='freeze');self.attack(g)
        self.assertEqual(g.state.pending_choice.options[0].label,'2');other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.pending_choice.options),3);self.portable(g)
    def test_b02_bound_after_attack_form_does_not_follow_replacement_weapon(self):
        g=self.game(face=FORMS[0],enemy=(FILL,FILL),mode='freeze');wid=self.weapon(g).id;self.attack(g);self.choose(g,'swap')
        self.assertNotEqual(self.weapon(g).id,wid);self.assertEqual(self.weapon(g).card_id,VANILLA)
        self.assertIsNone(g.state.pending_choice);self.portable(g)
    def test_b03_bound_after_attack_form_does_not_follow_transferred_weapon(self):
        g=self.game(face=FORMS[0],enemy=(FILL,FILL),mode='freeze');wid=self.weapon(g).id;self.attack(g);self.choose(g,'transfer')
        self.assertIsNone(self.weapon(g));self.assertEqual((self.weapon(g,2).id,self.weapon(g,2).card_id),(wid,FORMS[0]))
        self.assertIsNone(g.state.pending_choice);self.portable(g)
    def test_c00_earth_uses_full_printed_three_cost_query_and_entry_taunt(self):
        g=self.game(face=FORMS[2]);rows=resolve_candidates(g.registry,CTX,POOL,EARTH,source_card_id=FORMS[2],exclude_source_by_rule=True,player_id=1)
        self.assertEqual(tuple(x.card_id for x in rows),tuple(sorted((THREE,OTHER))));self.attack(g)
        body=g.state.entities[g.state.players[1].board[-1]];self.assertIn(body.card_id,(THREE,OTHER))
        self.assertIn(Keyword.TAUNT,body.keywords);self.assertNotIn(Keyword.TAUNT,g.registry.card(body.card_id).keywords)
        self.assertFalse(g.state.battlecry_history);self.portable(g)
    def test_c01_air_gets_only_printed_battlecry_minion_and_costs_two_less(self):
        g=self.game(face=FORMS[3]);rows=resolve_candidates(g.registry,CTX,POOL,AIR,source_card_id=FORMS[3],exclude_source_by_rule=True,player_id=1)
        self.assertEqual(tuple(x.card_id for x in rows),(BC,));self.attack(g)
        body=g.state.entities[g.state.players[1].hand[-1]];self.assertEqual(body.card_id,BC);self.assertEqual(body.cost,3)
        self.assertFalse(g.state.battlecry_history);self.portable(g)
    def test_c02_unknown_eligible_earth_candidate_rejects_whole_attack(self):
        g=self.game(face=FORMS[2],mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_c03_empty_generation_pool_keeps_attack_wear_and_choice_without_rng(self):
        for face in (FORMS[2],FORMS[3]):
            with self.subTest(face=face):
                g=self.game(face=face,mode='empty');saved=g._rng.getstate();self.attack(g)
                self.assertEqual(g._rng.getstate(),saved);self.assertEqual(self.weapon(g).durability,2)
                self.assertEqual(len(g.state.pending_choice.options),3);self.portable(g)
    def test_c04_full_board_earth_and_full_hand_air_follow_existing_delivery(self):
        for face,board,hand in ((FORMS[2],(FILL,)*7,()),(FORMS[3],(),(FILL,)*10)):
            with self.subTest(face=face):
                g=self.game(face=face,board=board,hand=hand);self.attack(g)
                self.assertEqual((len(g.state.players[1].board),len(g.state.players[1].hand)),(len(board),len(hand)))
                self.assertEqual(len(g.state.pending_choice.options),3);self.portable(g)
    def test_d00_reface_preserves_current_durability_buffs_grants_and_hero_attack_use(self):
        g=self.game((BUFF,),face=FORMS[1],enemy=(FILL,));wid=self.weapon(g).id;self.play(g,BUFF)
        self.attack(g);self.choose(g,FORMS[0]);e=self.weapon(g)
        self.assertEqual((e.id,e.attack,e.durability),(wid,5,4));self.assertIn(Keyword.LIFESTEAL,e.keywords)
        self.assertEqual(self.hero(g).attacks_this_turn,1)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.portable(g)
    def test_d01_historical_battlecry_randomly_transforms_current_foreign_weapon(self):
        g=self.game((CARD,SWAP,REPEAT));self.play(g,CARD);self.choose(g,FORMS[0]);self.play(g,SWAP);wid=self.weapon(g).id
        self.play(g,REPEAT);self.assertIsNone(g.state.pending_choice);self.assertEqual(self.weapon(g).id,wid)
        self.assertIn(self.weapon(g).card_id,FORMS);self.assertEqual(self.weapon(g).durability,4);self.portable(g)
    def test_d02_historical_battlecry_without_current_weapon_has_no_choice_or_rng(self):
        g=self.game((CARD,WEAR,REPEAT),enemy=(FILL,));self.play(g,CARD);self.choose(g,FORMS[1]);self.play(g,WEAR);self.attack(g)
        self.assertIsNone(self.weapon(g));saved=g._rng.getstate();self.play(g,REPEAT)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),saved);self.portable(g)
    def test_d03_original_reface_wait_restores_and_does_not_touch_later_equipment(self):
        g=self.game((PENDING,),face=FORMS[0]);wid=self.weapon(g).id;self.play(g,PENDING);other=self.portable(g)
        for game in (g,other):self.choose(game,'swap')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertNotEqual(self.weapon(g).id,wid)
        self.assertEqual(self.weapon(g).card_id,VANILLA);self.portable(g)

