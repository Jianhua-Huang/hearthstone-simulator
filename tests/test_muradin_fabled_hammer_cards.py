"""Real Hammer dependency and original weapon growth/shuffle boundaries."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.muradin_fabled_hammer_cards import HAMMER,ROOT,AVATAR,PREFIX,load_batch,register_muradin_fabled_hammer_cards
from hs_sim.cards.simple_followup_p71_cards import PREFIX as AVATAR_PREFIX
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import (ChoiceOption,GainArmor,InvokeBehavior,ModifyWeapon,RequestChoice,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.growing_weapon_shuffles import GROWTH_LABEL,ShuffleGrowingWeapon,permanent_attack
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest

P='hammer.test.';OTHER=P+'other';FILL=P+'filler';WATCH=P+'watch'


@lru_cache(maxsize=1)
def production_registry():
    return assembled_registry()


def family_registry():
    r=build_registry();p=production_registry()
    # Reuse only the actual Avatar face and its three existing executable bodies.
    # P71's other historical dependencies are outside this family fixture.
    r.register_card(p.card(AVATAR));r.register_pool_card(p.pool_cards[AVATAR])
    for suffix in ('avatar','avatar_buff','avatar_damage'):
        name=AVATAR_PREFIX+suffix;r.register_behavior(name,p.behavior(name))
    register_muradin_fabled_hammer_cards(r)
    return r


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in('writer','reader')
    r=family_registry()
    meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_card(CardDefinition(OTHER,OTHER,CardType.WEAPON,cost=1,attack=1,durability=2,metadata=meta))
    r.register_card(CardDefinition(FILL,FILL,CardType.SPELL,metadata=meta))
    def weapon(c):return c.state.entities[c.state.players[c.player_id].weapon_id]
    def fetch(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==HAMMER)
        return (MoveCard(CardReference.capture(e),c.player_id,Zone.HAND,source_id=c.source_id),)
    scripts={'break':lambda c:(ModifyWeapon(weapon(c).id,durability=-99,source_id=c.source_id),),
        'buff':lambda c:(ModifyWeapon(weapon(c).id,attack=8,durability=2,source_id=c.source_id),),
        'fetch':fetch}
    for key,body in scripts.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,metadata=meta))
    def fail(c):raise ResolutionError('Hammer deliberate failure')
    r.register_behavior(P+'fail',fail)
    if mode in('before','duplicate'):
        original_body=r._behaviors[PREFIX+'shuffle']
        def wrapped(c):
            effects=tuple(original_body(c))
            if mode=='duplicate':return effects+effects
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Shuffle',effects),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'wrapper',wrapped);r._cards[HAMMER]=replace(r.card(HAMMER),deathrattle=P+'wrapper')
    if mode in('wait','fail'):
        def watch(c):
            if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=HAMMER:return ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(1,(ChoiceOption('ok','Continue',(GainArmor(1,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,triggers=(TriggerSpec('card_shuffled',WATCH),),metadata=meta))
    r.validate();r.freeze();return r


class MuradinHammerDependencyTests(unittest.TestCase):
    def game(self,hand=(HAMMER,P+'break'),*,mode=None,empty_deck=False):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=(WATCH,)if mode in('wait','fail')else(),deck=()if empty_deck else(FILL,)*8,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=(FILL,)*8)),seed=232209),registry('writer',mode))
    def play(self,g,cid):
        p=g.state.active_player;e=next(g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,e.id));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode);self.assertIsNot(r,g.registry)
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in(1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in('"rng_state"','"resolution_frame"','"death_history"',GROWTH_LABEL,'SourceAllocationFact'):self.assertNotIn(field,wire)
        return other
    def test_a00_full_five_rows_six_faces_and_real_fabled_root(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),6)
        for section in('cards','dependencies','existing_dependencies','evidence_only'):
            for row in d[section]:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        r=production_registry();self.assertIn(ROOT,r.cards);self.assertIn(AVATAR,r.cards)
        self.assertEqual(r.card(HAMMER),registry('writer').card(HAMMER));self.assertEqual(len(d['cards']),1)
    def test_a01_real_paid_windfury_weapon_dies_after_four_attacks_and_shuffles_same_entity(self):
        g=self.game();eid=self.play(g,HAMMER);self.assertEqual(g.state.players[1].mana,14)
        self.assertIn(Keyword.WINDFURY,g.state.entities[g.state.players[1].hero_id].keywords)
        for round_index in range(2):
            for _ in range(2):g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
            if round_index==0:g.apply(EndTurn(1));g.apply(EndTurn(2))
        e=g.state.entities[eid];self.assertEqual((e.zone,e.attack,e.durability),(Zone.DECK,5,4))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(permanent_attack(e),2)
        self.assertEqual(len([d for d in g.state.death_history if d.entity_id==eid]),1);self.portable(g)
        self.assertEqual(g.state.deck_shuffle_history[-1].actor_id,1)
    def test_b00_two_real_deaths_accumulate_only_own_growth_and_repair_durability(self):
        g=self.game(hand=(HAMMER,P+'break',P+'fetch',P+'buff',P+'break'));eid=self.play(g,HAMMER)
        self.play(g,P+'break');self.assertEqual(g.state.entities[eid].attack,5)
        self.play(g,P+'fetch');self.assertEqual(self.play(g,HAMMER),eid);self.play(g,P+'buff')
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].durability),(13,6))
        self.play(g,P+'break');e=g.state.entities[eid];self.assertEqual((e.attack,e.durability),(7,4))
        self.assertEqual(permanent_attack(e),4);self.assertEqual(len([a for a in e.enchantments if a.label==GROWTH_LABEL]),1);self.portable(g)
    def test_b01_replacement_keeps_new_weapon_slot_and_shuffles_old_original(self):
        g=self.game(hand=(HAMMER,OTHER));eid=self.play(g,HAMMER);new=self.play(g,OTHER)
        self.assertEqual(g.state.players[1].weapon_id,new);self.assertEqual(g.state.entities[eid].zone,Zone.DECK)
        self.assertEqual(g.state.entities[eid].attack,5);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,1);self.portable(g)
    def test_b03_duplicate_original_request_is_stale_after_first_move_without_extra_rng(self):
        g=self.game(mode='duplicate');eid=self.play(g,HAMMER);self.play(g,P+'break')
        self.assertEqual(g.state.entities[eid].attack,5);self.assertEqual(len([e for e in g.events if e.kind=='card_shuffled']),1)
        self.assertTrue([e for e in g.events if e.kind=='effect_skipped']);self.portable(g)
    def test_c00_pending_original_dead_request_roundtrips_and_choice_failure_rolls_back(self):
        g=self.game(mode='before');eid=self.play(g,HAMMER);self.play(g,P+'break');other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.assertEqual(other.state.entities[eid].attack,5);self.portable(other)
    def test_c01_shuffle_notification_wait_sees_complete_original_and_portable_death_tail(self):
        g=self.game(mode='wait');eid=self.play(g,HAMMER);self.play(g,P+'break');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].durability),(5,4));other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.portable(other)
    def test_c02_late_shuffle_reaction_failure_restores_weapon_payment_rng_and_history(self):
        g=self.game(mode='fail');eid=self.play(g,HAMMER);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'break')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.entities[eid].durability,4);self.portable(g)
    def test_d00_empty_deck_uses_ordinary_single_insertion_policy(self):
        g=self.game(empty_deck=True);eid=self.play(g,HAMMER);self.play(g,P+'break')
        self.assertEqual(g.state.players[1].deck,[eid]);self.assertEqual(g.state.entities[eid].attack,5);self.portable(g)
    def test_d01_invalid_owner_growth_kind_and_borrowed_death_rejected(self):
        g=self.game();eid=self.play(g,HAMMER);live=SourceAllocationFact.capture(g.state,g.state.entities[eid])
        self.play(g,P+'break');death=g.state.death_history[-1]
        fact=replace(SourceAllocationFact.capture(g.state,g.state.entities[eid]),zone=Zone.GRAVEYARD,zone_epoch=death.cause.target_zone_epoch+1)
        with self.assertRaises(ValueError):ShuffleGrowingWeapon(fact,death,2,2)
        with self.assertRaises(ValueError):ShuffleGrowingWeapon(fact,death,1,True)
        with self.assertRaises(ValueError):ShuffleGrowingWeapon(replace(fact,kind=CardType.MINION),death,1,2)
        with self.assertRaises(ValueError):ShuffleGrowingWeapon(live,death,1,2)
    def test_d02_full_assembly_does_not_register_evidence_enchantments_or_mutate_avatar(self):
        r=production_registry()
        self.assertNotIn('TIME_209e',r.cards);self.assertNotIn('TIME_209t2e',r.cards)
        self.assertEqual((r.card(HAMMER).cost,r.card(HAMMER).attack,r.card(HAMMER).durability),(6,3,4))
        self.assertEqual(r.card(AVATAR).cost,3)
