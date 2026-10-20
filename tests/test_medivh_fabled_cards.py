"""Real Medivh trio, exact controlled prices and shared battlefield effects."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.medivh_fabled_cards import CARD,STAFF,KARAZHAN,POOL_ID,load_batch
from hs_sim.engine import (Attack,AuraSpec,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,
    DeckPolicy,DeckSpec,DestroyLocation,EndTurn,Game,IllegalAction,Keyword,MatchSetup,PlayCard,
    PlayerSetup,Rarity,ResolutionError,Scenario,SelectChoice,SnapshotError,SummonQuantitySpec,
    TargetSpec,TriggerSpec,UseHeroPower,UseLocation,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input,capture_generated_quote_fact,capture_quote_fact,quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,DamageKind,GainArmor,Heal,
    HealingKind,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Silence,SilenceBatch)
from hs_sim.engine.fabled_decks import expand_fabled_cards
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin
from hs_sim.engine.model import HealthFlow,HealthOp,HealthRule,IntrinsicCostSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash

P='fixture.medivh.';A=P+'eight_a';B=P+'eight_b';WATCH=P+'watch';FRAGILE=P+'fragile';AURA=P+'aura'
CTX=GenerationContext('medivh-explicit-complete-experiment','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal',pool='normal'):
    r=build_registry();r.register_behavior(P+'reward',lambda c:(GainArmor(c.player_id,3),))
    for cid,cost in((A,8),(B,8),(P+'seven',7),(P+'nine',9)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=20,metadata=META,battlecry=P+'reward')
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(FRAGILE,FRAGILE,CardType.MINION,health=1,deathrattle=P+'reward'))
    r.register_card(CardDefinition(AURA,AURA,CardType.MINION,health=5,auras=(AuraSpec(health=2),)))
    r.register_card(CardDefinition(P+'sleep',P+'sleep',CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition(P+'quantity',P+'quantity',CardType.MINION,health=4,summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(P+'bonus',P+'bonus',CardType.MINION,health=4,spell_damage=2,
        health_rules=(HealthRule(HealthFlow.HEALING,HealthOp.ADD,2,source_relation='friendly',healing_kinds=(HealingKind.SPELL,)),)))
    def fail(c):raise ResolutionError('Medivh reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    scripts={'hurt':lambda c:(Damage(c.target_id,2,c.source_id),),
        'wound':lambda c:(Damage(c.state.players[c.player_id].hero_id,10,c.source_id),),
        'damage':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        'heal':lambda c:(Heal(c.target_id,3,c.source_id,HealingKind.SPELL),),
        'heal_effect':lambda c:(Heal(c.target_id,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'tax':lambda c:(ModifyCost(c.target_id,CostSpec(delta=2),c.source_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        target=None if name=='wound'else TargetSpec(zones=(Zone.HAND,)if name=='tax'else(Zone.HERO,Zone.BOARD),
            kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION)if name=='tax'else(CardType.HERO,CardType.MINION))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,targeting=target))
    def watch(c):
        if mode=='paid_wait'and c.event.kind=='card_committed'and c.state.entities[c.event.source_id].card_id==CARD:
            location=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KARAZHAN)
            return(RequestChoice(c.player_id,(ChoiceOption('remove','Remove qualifier',(DestroyLocation(location,c.source_id),)),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='summon_wait'and c.event.kind=='minion_summoned'and c.event.player_id==c.player_id and c.state.entities[c.event.target_id].card_id in(A,B):
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,triggers=tuple(
        TriggerSpec(k,P+'watch')for k in('card_committed','minion_summoned'))))
    members=(A,B,P+'seven',P+'nine')
    if pool=='empty':members=()
    elif pool=='unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.MINION,8,META));members=(A,P+'unknown')
    if pool!='missing':r.register_pool(PoolDefinition(POOL_ID,'medivh-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


def rehash(snapshot):
    snapshot['events_hash']=canonical_hash(snapshot['events'])
    snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()if k not in('schema_version','events','events_hash','state_hash')})
    return snapshot


class MedivhFabledTests(unittest.TestCase):
    def game(self,hand=(CARD,STAFF,KARAZHAN),board=(),enemy=(),weapon=None,mode='normal',pool='normal',active=1,enemy_weapon=None):
        players=tuple(PlayerSetup('HERO_09'if p==active else'HERO_08',hand=hand if p==active else(),deck=(A,)*8,
            board=(((WATCH,)if mode!='normal'else())+board)if p==active else enemy,
            weapon_card_id=weapon if p==active else enemy_weapon,hero_power_card_id='HERO_09bp'if p==active else None,
            max_mana=10,mana=10)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=306,generation_context=CTX),fixture(mode,pool))
    def eid(self,g,card,zone=Zone.HAND,p=None):
        p=p or g.state.active_player
        return next(e.id for e in g.state.entities.values()if e.card_id==card and e.controller==p and e.zone==zone)
    def play(self,g,card=CARD,target=None):
        eid=self.eid(g,card);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def price(self,g,card):return quote_cost(g.state,g.registry,g.state.entities[self.eid(g,card)]).amount
    def use(self,g):g.apply(UseLocation(g.state.active_player,self.eid(g,KARAZHAN,Zone.BOARD)))
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='normal',pool='normal'):
        saved=g.snapshot();r=fixture.__wrapped__(mode,pool)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),r).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        return Game.from_snapshot(saved,r)

    def test_three_full_rows_six_primary_faces_and_exact_priest_fabled_companions(self):
        data=load_batch();r=fixture()
        self.assertEqual((len(data['cards']),len(data['dependencies']),len(data['official_observations'])),(1,2,6))
        self.assertEqual(r.card(CARD).metadata.classes,(CardClass.PRIEST,))
        self.assertEqual(expand_fabled_cards((CARD,),r),(CARD,STAFF,KARAZHAN))
        self.assertEqual((r.card(STAFF).attack,r.card(STAFF).durability,r.card(KARAZHAN).durability),(1,3,2))

    def test_each_original_conditional_price_tracks_only_current_own_qualifying_carrier(self):
        for card,board,weapon in((CARD,(KARAZHAN,),None),(STAFF,(CARD,),None),(KARAZHAN,(),STAFF)):
            with self.subTest(card=card):
                g=self.game((card,),board=board,weapon=weapon);self.assertEqual(self.price(g,card),0)
                e=g.state.entities[self.eid(g,card)]
                generated=capture_generated_quote_fact(g.state,g.registry,1,card)
                rules=g.registry.card(card).intrinsic_costs
                self.assertEqual((generated.intrinsic.amount,generated.intrinsic.condition_facts[0].card_ids),
                    (0,rules[0].card_ids))
                enemy=self.game((card,),enemy=board,enemy_weapon=weapon);self.assertEqual(self.price(enemy,card),10)

    def test_actual_ten_mana_root_then_zero_staff_then_zero_location_keeps_original_physical_cards(self):
        g=self.game();original=tuple(g.state.players[1].hand)
        for card,cost in((CARD,10),(STAFF,0),(KARAZHAN,0)):
            self.play(g,card);self.assertEqual(g.state.play_history[-1].cost,cost)
        self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual(tuple(e.id for e in g.state.entities.values()if e.id in original),original)
        self.assertEqual(g.state.players[1].weapon_id,original[1]);self.portable(g)

    def test_silenced_medivh_still_qualifies_until_actual_board_departure(self):
        g=self.game((STAFF,P+'silence',P+'bounce'),board=(CARD,));medivh=self.eid(g,CARD,Zone.BOARD)
        self.play(g,P+'silence',medivh);self.assertEqual(self.price(g,STAFF),0)
        self.play(g,P+'bounce',medivh);self.assertEqual(self.price(g,STAFF),10)

    def test_current_control_transfer_requotes_both_owners_without_a_silenceable_aura(self):
        g=self.game((STAFF,P+'give'),board=(CARD,));self.assertEqual(self.price(g,STAFF),0)
        self.play(g,P+'give',self.eid(g,CARD,Zone.BOARD));self.assertEqual(self.price(g,STAFF),10)
        g=self.game((STAFF,),board=(CARD,),active=2);self.assertEqual(self.price(g,STAFF),0)

    def test_intrinsic_zero_precedes_ordinary_local_cost_enchantment(self):
        g=self.game((STAFF,P+'tax'),board=(CARD,));self.play(g,P+'tax',self.eid(g,STAFF))
        self.assertEqual(self.price(g,STAFF),2);self.play(g,STAFF);self.assertEqual(g.state.players[1].mana,8)

    def test_paid_waiting_quote_survives_original_qualifier_removal_and_roundtrips(self):
        g=self.game((CARD,),board=(KARAZHAN,),mode='paid_wait');self.play(g)
        saved=g.snapshot();other=self.portable(g,'paid_wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g,'remove');self.choose(other,'remove');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,10))

    def test_rehashed_selector_or_complete_original_presence_crop_is_rejected(self):
        g=self.game((CARD,),board=(KARAZHAN,));self.play(g);saved=g.snapshot()
        for kind in('selector','row','acceptance'):
            bad=deepcopy(saved);match=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts'][0]
            if kind=='selector':match['card_ids']=[STAFF]
            elif kind=='row':match['boards'][0].pop(0)
            else:
                event=next(e for e in bad['events']if e['kind']=='controlled_card_cost_accepted')
                event['kind']='fixture.cropped_controlled_price_acceptance'
            with self.subTest(kind=kind),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_batch_silence_removes_all_deathrattles_before_health_aura_deaths(self):
        g=self.game((P+'hurt',CARD),board=(AURA,FRAGILE),enemy=(FRAGILE,))
        fragile=self.eid(g,FRAGILE,Zone.BOARD);self.play(g,P+'hurt',fragile);self.assertEqual(g.state.entities[fragile].health,1)
        self.play(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[CARD])
        self.assertFalse(g.state.players[2].board)

    def test_mass_effect_leaves_locations_dormant_minions_and_original_source_untouched(self):
        g=self.game((CARD,),board=(KARAZHAN,P+'sleep'),enemy=(KARAZHAN,A));self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[KARAZHAN,P+'sleep',CARD])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[KARAZHAN])

    def test_weapon_scales_spell_damage_and_healing_after_actual_additive_bonuses(self):
        g=self.game((P+'wound',P+'damage',P+'heal'),weapon=STAFF,board=(P+'bonus',));self.play(g,P+'wound')
        self.play(g,P+'damage',g.state.players[2].hero_id);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20)
        self.play(g,P+'heal',g.state.players[1].hero_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,3)

    def test_weapon_excludes_effect_healing_hero_power_combat_and_enemy_spells(self):
        g=self.game((P+'wound',P+'heal_effect'),weapon=STAFF);self.play(g,P+'wound')
        self.play(g,P+'heal_effect',g.state.players[1].hero_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23)
        power=next(a for a in g.legal_actions()if isinstance(a,UseHeroPower)and a.target_id==g.state.players[1].hero_id)
        g.apply(power);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,25)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29)
        enemy=self.game((P+'damage',),enemy_weapon=STAFF);self.play(enemy,P+'damage',enemy.state.players[2].hero_id)
        self.assertEqual(enemy.state.entities[enemy.state.players[2].hero_id].health,27)

    def test_location_delivers_two_eight_cost_bodies_without_their_battlecries(self):
        g=self.game((),board=(KARAZHAN,));self.use(g)
        self.assertEqual(len(g.state.card_summon_history),2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        children=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].kind==CardType.MINION]
        self.assertEqual(len(children),2);self.assertTrue(all(e.card_id in(A,B)for e in children))
        self.assertEqual(g.state.entities[self.eid(g,KARAZHAN,Zone.BOARD)].durability,1)

    def test_two_requests_share_normal_quantity_multiplier_but_independent_roots(self):
        g=self.game((),board=(KARAZHAN,P+'quantity'));self.use(g)
        self.assertEqual(len(g.state.card_summon_history),2)
        self.assertEqual(sum(g.state.entities[i].card_id in(A,B)for i in g.state.players[1].board),4)

    def test_capacity_and_confirmed_empty_pool_do_not_replace_candidates_or_draw_randomness(self):
        for board,pool,count in(((KARAZHAN,)+(A,)*6,'normal',7),((KARAZHAN,),'empty',1)):
            with self.subTest(pool=pool):
                g=self.game((),board=board,pool=pool);rng=g._rng.getstate();self.use(g)
                self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.players[1].board),count)
        g=self.game((),board=(KARAZHAN,)+(A,)*5);old=set(g.state.entities);self.use(g)
        self.assertEqual(len(set(g.state.entities)-old),1)

    def test_missing_or_unknown_eligible_pool_rolls_back_location_use_and_randomness(self):
        for pool in('missing','unknown'):
            with self.subTest(pool=pool):
                g=self.game((),board=(KARAZHAN,),pool=pool);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.use(g)
                self.assertEqual(g.snapshot(),saved)

    def test_first_summon_waiting_restores_then_finishes_original_second_request_once(self):
        g=self.game((),board=(KARAZHAN,),mode='summon_wait');self.use(g);other=self.portable(g,'summon_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):
            while game.state.pending_choice is not None:self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.card_summon_history),2)

    def test_selector_and_batch_shapes_are_strict_and_codec_preserves_exact_targets(self):
        g=self.game((),board=(A,B));effect=SilenceBatch(tuple(g.state.players[1].board));codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for ids in([1,2],(1,1),(True,),(-1,)):
            with self.subTest(ids=ids),self.assertRaises(ValueError):SilenceBatch(ids)
        spec=g.registry.card(CARD).intrinsic_costs[0]
        for change in({'card_ids':[]},{'card_ids':()},{'card_ids':(KARAZHAN,KARAZHAN)},{'set_to':1}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(spec,**change)

    def test_player_observation_does_not_publish_private_presence_receipts(self):
        g=self.game((CARD,STAFF,KARAZHAN),board=(KARAZHAN,));self.assertEqual(self.price(g,CARD),0)
        public=json.dumps(g.observe(2));self.assertNotIn('card_ids',public);self.assertNotIn('condition_facts',public)
        self.assertTrue(all(e.get('card_id')is None for e in g.observe(2)['players'][0]['hand']))

    def test_real_fabled_opening_keeps_all_original_physical_companions(self):
        r=fixture();cards=expand_fabled_cards((CARD,)+(A,)*9,r)
        policy=DeckPolicy('medivh.opening',CTX.target_id,CTX.mode,(CARD,STAFF,KARAZHAN,A),deck_size=12,max_copies=12)
        setup=MatchSetup(tuple(DeckSpec('HERO_09','HERO_09bp',CardClass.PRIEST,cards)for _ in(1,2)),policy,'GAME_005',seed=306,first_player=1)
        g=Game.from_decks(setup,r)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        for p in(1,2):self.assertEqual(g.state.players[p].original_deck,cards)
        self.portable(g)


if __name__=='__main__':unittest.main()
