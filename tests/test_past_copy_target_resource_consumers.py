"""Real resource consumers and original return/deck-discovery boundaries."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_copy_target_resource_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import local_cost,quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,Draw,Freeze,GainArmor,InvokeBehavior,
    RandomDamage,ReplaceHero,RequestChoice,Silence)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,Keyword,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.registry import Registry,UnsupportedDefinitionError
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import AddToDeck
from hs_sim.local_pool_format import build_cn37_local_pool_format

NEF,YSIEL,BARISTA,JEP,YREL,KIRI,SHEK,TENWU,DEATHWING,VARDEN,CARIEL,HOBART=native.ROOTS
TAIL=native.TAIL;LUNAR,SOLAR=native.EXISTING
P='k703.';A=P+'plain';BC=P+'battlecry';POWER=P+'power';TANK=P+'tank';DORMANT=P+'dormant';UNKNOWN=P+'unknown'
MAGE=P+'mage_spell';HUNTER=P+'hunter_spell';HOLY=P+'holy_spell';NATURE=P+'nature_spell';FREE=P+'free_spell'
KILL=P+'kill';HUSH=P+'hush';ENHANCE=P+'enhance';FROST=P+'freeze';PAIN=P+'pain';SWAP=P+'change_enemy';QUEUE=P+'queued_return'
NEUTRAL_HERO=P+'neutral_hero';UNKNOWN_HERO=P+'unknown_hero';WEAPON=P+'weapon';FAIL=P+'fail'
WATCH_DRAW=P+'draw_watch';WATCH_COPY=P+'copy_watch';WATCH_RETURN=P+'return_watch';WATCH_ATTACK=P+'attack_watch'
HELPERS=(A,BC,POWER,TANK,DORMANT,UNKNOWN,MAGE,HUNTER,HOLY,NATURE,FREE,KILL,HUSH,ENHANCE,FROST,PAIN,SWAP,QUEUE,
    NEUTRAL_HERO,UNKNOWN_HERO,WEAPON,WATCH_DRAW,WATCH_COPY,WATCH_RETURN,WATCH_ATTACK)
CTX=GenerationContext('k703-explicit-small-fixture','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(CardClass.MAGE,collectible=False)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,5),))
    for cid,attack,hp,cost in((A,1,12,3),(BC,2,12,6),(POWER,1,12,1),(TANK,20,30,1),(DORMANT,1,12,1),(UNKNOWN,1,12,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=hp,
            battlecry=P+'bc'if cid==BC else None,spell_damage=3 if cid==POWER else 0,
            dormant_turns=2 if cid==DORMANT else 0,metadata=None if cid==UNKNOWN else metadata(collectible=False)if cid==A else meta))
        if cid!=UNKNOWN:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,cost,cls,school in((MAGE,4,CardClass.MAGE,SpellSchool.ARCANE),(HUNTER,2,CardClass.HUNTER,SpellSchool.NATURE),
            (HOLY,2,CardClass.PALADIN,SpellSchool.HOLY),(NATURE,3,CardClass.DRUID,SpellSchool.NATURE),(FREE,0,CardClass.MAGE,SpellSchool.ARCANE)):
        r.register_behavior(cid,lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,spell_school=school,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)),metadata=metadata(cls)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(NEUTRAL_HERO,NEUTRAL_HERO,CardType.HERO,health=30,initial_hero_power='HERO_08bp',metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(UNKNOWN_HERO,UNKNOWN_HERO,CardType.HERO,health=30,initial_hero_power='HERO_08bp'))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K703 deliberate original continuation failure')))
    def menu(c,extra=()):
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*extra),c.source_id)
    def waiting(c):
        event=c.event;source=c.state.entities.get(event.source_id);extra=()
        if event.kind=='card_drawn':
            if event.player_id!=c.player_id or source is None or source.card_id not in(JEP,SHEK):return()
            extra=(ChoiceOption('extra','Independent draw',(Draw(c.player_id,1,c.source_id),)),
                ChoiceOption('shuffle','New same-name deck card',(AddToDeck(player_id=c.player_id,
                    card_id=c.state.entities[event.target_id].card_id,position='top',source_id=c.source_id),)))
        elif event.kind=='card_created':
            if source is None or source.card_id!=BARISTA:return()
            targets=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BC]
            if targets:extra=(ChoiceOption('remove','Remove remaining original',(Destroy(targets[-1],c.source_id),)),)
        elif event.kind=='card_returned':
            if event.player_id!=c.player_id or c.state.entities[event.target_id].card_id!=BC:return()
        elif source is None or source.card_id!=DEATHWING:return()
        return(menu(c,extra),)
    def queued(c):
        return(menu(c,(ChoiceOption('fill','Fill the original hand',(AddToHand(c.player_id,A,c.source_id),)),)),
            ReturnCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),c.source_id,
                cost=CostSpec(set_to=1),expires_turn=c.state.turn))
    r.register_behavior(P+'waiting',waiting)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        ENHANCE:lambda c:(Buff(c.target_id,5,5,c.source_id),),FROST:lambda c:(Freeze(c.target_id,c.source_id),),
        PAIN:lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.EFFECT),),
        SWAP:lambda c:(ReplaceHero(2,'HERO_05',hero_power_card_id='HERO_05bp'),),QUEUE:queued}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,metadata=meta,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in(KILL,HUSH,ENHANCE,FROST,PAIN,QUEUE)else None))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=2,attack=1,durability=3,metadata=meta))
    for cid,event in((WATCH_DRAW,'card_drawn'),(WATCH_COPY,'card_created'),(WATCH_RETURN,'card_returned'),(WATCH_ATTACK,'attack_declared')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'waiting'),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k703-copy-target-resource-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp','HERO_05','HERO_05bp',*native.EXISTING,*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_copy_target_resource_consumers(r)
    r.register_pool(PoolDefinition('constructed.cards','explicit-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in(MAGE,HUNTER,HOLY,NATURE,FREE))))
    r.validate();return r


class PastCopyTargetResourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*12,enemy_hero='HERO_08',watch=None,weapon=None,real_host=False,seed=703):
        self.mode='host'if real_host else'small';h=host()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch or weapon),
            PlayerSetup(enemy_hero,board=enemy,deck=(A,)*12,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=seed,generation_context=h.context if real_host else CTX),h.registry if real_host else fixture())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def choose_card(self,g,cid):self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def original_draws(self,g,source):return[x for x in g.state.draw_history if x.source_id==source and x.parent_id is None]

    def test_complete_thirteen_faces_and_real_named_dependency_roles(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['official_observations']),32)
        self.assertEqual(d['neutral_hero_reward_ids'],[TAIL,TAIL]);self.assertEqual(d['kiri_reward_ids'],[SOLAR,LUNAR])
        for row in d['cards']+d['dependencies']:
            card=r.card(row['record']['id']);self.assertEqual(card,native.make_definition(row['record']))
            self.assertEqual(r.pool_card(card.id),PoolCard.from_definition(card))

    def test_all_thirteen_real_faces_have_normal_paid_hand_entries(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(BC,));cost=fixture().card(cid).cost
                target=self.unit(g,BC).id if cid==TENWU else self.hero(g,2).id if cid==TAIL else None
                self.play(g,cid,target)
                if g.state.pending_choice is not None:self.choose(g,g.state.pending_choice.options[0].id)
                self.assertEqual(g.state.players[1].mana,30-cost)

    def test_nefarian_uses_opponent_class_and_allows_real_duplicate_generation(self):
        g=self.game((NEF,),enemy_hero='HERO_05');self.play(g,NEF);self.assertEqual(self.hand(g),[HUNTER,HUNTER])

    def test_nefarian_reads_actual_replaced_hero_class_instead_of_starting_class(self):
        g=self.game((SWAP,NEF));self.play(g,SWAP);self.assertEqual(g.state.players[2].hero_class,CardClass.HUNTER)
        self.play(g,NEF);self.assertEqual(self.hand(g),[HUNTER,HUNTER]);self.portable(g)

    def test_nefarian_neutral_hero_generates_two_actual_tail_swipes(self):
        g=self.game((NEF,),enemy_hero=NEUTRAL_HERO,board=(POWER,));self.play(g,NEF)
        self.assertEqual(self.hand(g),[TAIL,TAIL]);self.play(g,TAIL,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,23);self.assertEqual(g.state.players[1].mana,17)

    def test_nefarian_unknown_opponent_class_errors_and_restores_payment_and_rng(self):
        g=self.game((NEF,),enemy_hero=UNKNOWN_HERO);before=g.snapshot()
        with self.assertRaises(ResolutionError)as raised:self.play(g,NEF)
        self.assertIsInstance(raised.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before)

    def test_nefarian_standard_host_preserves_complete_class_spell_domain(self):
        h=host();self.assertGreater(len(h.registry.pool('constructed.cards',h.context).members),1000)
        query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.HUNTER,),include_neutral=False)
        expected=resolve_candidates(h.registry,h.context,'constructed.cards',query,source_card_id=NEF,player_id=1,exclude_source_by_rule=True)
        g=self.game((NEF,),enemy_hero='HERO_05',real_host=True);self.play(g,NEF)
        self.assertEqual(len(self.hand(g)),2);self.assertTrue(set(self.hand(g))<={x.card_id for x in expected});self.portable(g)

    def test_ysiel_sets_even_free_spells_to_one_and_expires_at_turn_end(self):
        g=self.game((YSIEL,MAGE,FREE,BC));self.play(g,YSIEL)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,MAGE)).amount,1)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,FREE)).amount,1)
        self.assertEqual(local_cost(self.entity(g,BC))[0],6);g.apply(EndTurn(1))
        self.assertEqual(local_cost(self.entity(g,MAGE))[0],4);self.assertEqual(local_cost(self.entity(g,FREE))[0],0)

    def test_ysiel_price_survives_source_death_and_applies_to_multiple_spells(self):
        g=self.game((YSIEL,KILL,MAGE,NATURE));source=self.play(g,YSIEL);self.play(g,KILL,source)
        before=g.state.players[1].mana;self.play(g,MAGE,self.hero(g,2).id);self.play(g,NATURE,self.hero(g,2).id)
        self.assertEqual(g.state.players[1].mana,before-2)

    def test_barista_copies_only_other_friendly_current_battlecries_as_printed_base(self):
        g=self.game((BC,ENHANCE,BARISTA),board=(A,),enemy=(BC,));original=self.play(g,BC);self.play(g,ENHANCE,original)
        self.play(g,BARISTA);self.assertEqual(self.hand(g),[BC]);copy=self.entity(g,BC)
        self.assertEqual((copy.attack,copy.health,local_cost(copy)[0]),(2,12,6));self.assertEqual(self.hero(g).armor,5)
        self.assertEqual(g.state.entities[original].attack,7);self.assertNotEqual(copy.id,original)

    def test_barista_current_capability_policy_excludes_silenced_original(self):
        g=self.game((HUSH,BARISTA),board=(BC,));self.play(g,HUSH,self.unit(g,BC).id);self.play(g,BARISTA)
        self.assertEqual(self.hand(g),[])

    def test_barista_frozen_base_group_survives_original_death_after_first_copy(self):
        g=self.game((BARISTA,),board=(BC,BC),watch=WATCH_COPY);self.play(g,BARISTA)
        self.portable(g);self.fault(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(self.hand(g),[BC,BC]);self.assertEqual(self.board(g).count(BC),1);self.portable(g)

    def test_jepetto_draws_original_minions_and_sets_only_their_stats_and_cost(self):
        g=self.game((JEP,),deck=(BC,MAGE,A));source=self.play(g,JEP)
        self.assertEqual(set(self.hand(g)),{BC,A});self.assertEqual(len(self.original_draws(g,source)),2)
        for cid in(BC,A):
            e=self.entity(g,cid);self.assertEqual((e.attack,e.health,local_cost(e)[0]),(1,1,1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[MAGE])

    def test_jepetto_empty_minion_query_neither_fatigues_nor_samples_rng(self):
        g=self.game((JEP,),deck=());before=g.snapshot()['rng_state'];self.play(g,JEP)
        self.assertFalse(g.state.draw_history);self.assertEqual(self.hero(g).health,30);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_jepetto_wait_does_not_reward_independent_reaction_draw(self):
        g=self.game((JEP,),deck=(BC,A,MAGE),watch=WATCH_DRAW);source=self.play(g,JEP)
        self.portable(g);self.fault(g);self.choose(g,'extra');self.finish(g)
        original=self.original_draws(g,source);self.assertEqual(len(original),1)
        first=g.state.entities[original[0].entity_id];self.assertEqual((first.attack,first.health,local_cost(first)[0]),(1,1,1))
        extra=next(x for x in g.state.draw_history if x.source_id!=source);e=g.state.entities[extra.entity_id];printed=fixture().card(e.card_id)
        self.assertEqual((e.attack,e.health,local_cost(e)[0]),(printed.attack,printed.health,printed.cost));self.portable(g)

    def test_yrel_four_keywords_enable_real_rush_shield_and_lifesteal(self):
        g=self.game((PAIN,YREL),deck=(BC,),enemy=(A,));self.play(g,PAIN,self.hero(g).id);source=self.play(g,YREL)
        self.assertTrue({Keyword.RUSH,Keyword.LIFESTEAL,Keyword.TAUNT,Keyword.DIVINE_SHIELD}<=g.state.entities[source].keywords)
        g.apply(Attack(1,source,self.unit(g,A,2).id));self.assertEqual(self.hero(g).health,30);self.assertEqual(g.state.entities[source].health,5)

    def test_yrel_current_neutral_card_prevents_reward_and_empty_deck_qualifies(self):
        g=self.game((YREL,),deck=(A,));self.play(g,YREL);self.assertNotIn(Keyword.RUSH,self.unit(g,YREL).keywords)
        g=self.game((YREL,),deck=());self.play(g,YREL);self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,YREL).keywords)

    def test_yrel_unknown_current_deck_class_is_not_a_positive_condition(self):
        g=self.game((YREL,),deck=(UNKNOWN,));before=g.snapshot()
        with self.assertRaises(ResolutionError)as raised:self.play(g,YREL)
        self.assertIsInstance(raised.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before)

    def test_kiri_real_existing_eclipses_repeat_and_discount_actual_spells(self):
        g=self.game((KIRI,TAIL,HOLY),enemy=(A,),real_host=True);self.play(g,KIRI)
        self.assertEqual(self.hand(g),[TAIL,HOLY,SOLAR,LUNAR]);self.play(g,SOLAR);self.play(g,TAIL,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,22);self.play(g,LUNAR,self.unit(g,A,2).id)
        self.assertEqual(self.unit(g,A,2).health,9)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,HOLY)).amount,0)
        before=g.state.players[1].mana;self.play(g,HOLY,self.hero(g,2).id)
        self.assertEqual(g.state.players[1].mana,before);self.assertEqual(self.hero(g,2).health,20)

    def test_shekzara_discovers_distinct_identities_and_draws_all_original_physical_copies(self):
        g=self.game((SHEK,),deck=(BC,BC,A,BC));original=set(g.state.players[1].deck);source=self.play(g,SHEK)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{BC,A});self.assertEqual(len(g.state.pending_choice.options),2)
        self.portable(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'not-offered')
        self.assertEqual(g.snapshot(),before);self.choose_card(g,BC)
        self.assertEqual(self.hand(g),[BC]*3);self.assertEqual(len(self.original_draws(g,source)),3)
        self.assertTrue(set(g.state.players[1].hand)<=original);self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)

    def test_shekzara_empty_deck_has_no_discovery_draw_fatigue_or_rng(self):
        g=self.game((SHEK,),deck=());before=g.snapshot()['rng_state'];self.play(g,SHEK)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.draw_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_shekzara_frozen_copy_inventory_ignores_new_same_name_shuffle(self):
        g=self.game((SHEK,),deck=(BC,BC,BC,A),watch=WATCH_DRAW);source=self.play(g,SHEK);self.choose_card(g,BC)
        self.portable(g);self.fault(g);self.choose(g,'shuffle');self.finish(g)
        self.assertEqual(self.hand(g),[BC]*3);self.assertEqual(len(self.original_draws(g,source)),3)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[BC,A]);self.portable(g)

    def test_shekzara_reaction_draw_of_an_original_copy_is_not_drawn_twice(self):
        g=self.game((SHEK,),deck=(BC,BC,BC,A),watch=WATCH_DRAW);source=self.play(g,SHEK);self.choose_card(g,BC)
        self.choose(g,'extra');self.finish(g);self.assertEqual(self.hand(g),[BC]*3)
        self.assertEqual(len(self.original_draws(g,source)),2);self.assertEqual(len(g.state.draw_history),3);self.portable(g)

    def test_tenwu_returns_same_physical_original_and_price_expires_at_turn_end(self):
        g=self.game((ENHANCE,TENWU),board=(BC,));original=self.unit(g,BC).id;self.play(g,ENHANCE,original);self.play(g,TENWU,original)
        returned=self.entity(g,BC);self.assertEqual(returned.id,original);self.assertEqual((returned.attack,returned.health,local_cost(returned)[0]),(2,12,1))
        self.portable(g);g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,BC))[0],6)

    def test_tenwu_allows_no_friendly_target_and_rejects_enemy_before_payment(self):
        g=self.game((TENWU,),enemy=(BC,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TENWU,self.unit(g,BC,2).id)
        self.assertEqual(g.snapshot(),before);self.play(g,TENWU);self.assertEqual(self.board(g),[TENWU])

    def test_tenwu_price_is_already_installed_at_original_return_wait(self):
        g=self.game((TENWU,),board=(BC,),watch=WATCH_RETURN);original=self.unit(g,BC).id;self.play(g,TENWU,original)
        self.assertEqual(local_cost(self.entity(g,BC))[0],1);self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.entity(g,BC).id,original);self.assertEqual(g.state.players[1].mana,28);self.portable(g)

    def test_timed_return_request_saved_before_delivery_restores_expiry_once(self):
        g=self.game((QUEUE,),board=(BC,));self.play(g,QUEUE,self.unit(g,BC).id);restored=self.portable(g);self.fault(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(local_cost(self.entity(g,BC))[0],1)
        g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,BC))[0],6)

    def test_timed_return_full_original_hand_uses_existing_death_without_price(self):
        g=self.game((QUEUE,)+(A,)*9,board=(BC,));original=self.unit(g,BC).id;self.play(g,QUEUE,original);self.choose(g,'fill')
        self.assertNotIn(BC,self.hand(g));self.assertEqual(len(self.hand(g)),10)
        self.assertTrue(any(x.entity_id==original for x in g.state.death_history))

    def test_deathwing_really_attacks_both_sides_other_minions(self):
        g=self.game((DEATHWING,),board=(A,A),enemy=(A,A));source=self.play(g,DEATHWING)
        self.assertEqual(self.board(g),[DEATHWING]);self.assertEqual(self.board(g,2),[]);self.assertEqual(g.state.entities[source].health,8)

    def test_deathwing_stops_when_original_attacker_dies(self):
        g=self.game((DEATHWING,),enemy=(TANK,TANK,TANK));self.play(g,DEATHWING)
        self.assertEqual(self.board(g),[]);self.assertEqual(sorted(g.state.entities[i].health for i in g.state.players[2].board),[18,30,30])

    def test_deathwing_attack_wait_keeps_original_remaining_targets_and_rolls_back_failure(self):
        g=self.game((DEATHWING,),enemy=(A,A),watch=WATCH_ATTACK);self.play(g,DEATHWING)
        self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.board(g,2),[]);self.portable(g)

    def test_varden_uses_original_frozen_flags_and_minion_damage_without_spell_bonus(self):
        g=self.game((FROST,VARDEN),board=(POWER,),enemy=(A,BC));target=self.unit(g,BC,2).id;self.play(g,FROST,target);self.play(g,VARDEN)
        self.assertEqual(g.state.entities[target].health,8);self.assertTrue(g.state.entities[target].frozen)
        self.assertEqual(self.unit(g,A,2).health,12);self.assertTrue(self.unit(g,A,2).frozen);self.assertEqual(self.hero(g,2).health,30)

    def test_varden_does_not_freeze_or_damage_dormant_enemy(self):
        g=self.game((VARDEN,),enemy=(DORMANT,A));self.play(g,VARDEN)
        self.assertFalse(self.unit(g,DORMANT,2).frozen);self.assertFalse(self.unit(g,DORMANT,2).active);self.assertTrue(self.unit(g,A,2).frozen)

    def test_cariel_real_rush_attack_discounts_only_current_holy_hand_spells(self):
        g=self.game((CARIEL,HOLY,NATURE,BC),board=(A,),enemy=(A,));source=self.play(g,CARIEL);target=self.unit(g,A,2).id
        g.apply(Attack(1,self.unit(g,A).id,target));self.assertEqual(local_cost(self.entity(g,HOLY))[0],2)
        g.apply(Attack(1,source,target));self.assertEqual(local_cost(self.entity(g,HOLY))[0],1)
        self.assertEqual(local_cost(self.entity(g,NATURE))[0],3);self.assertEqual(local_cost(self.entity(g,BC))[0],6)
        g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,HOLY))[0],1)

    def test_hobart_current_equipment_buffs_original_hand_and_deck_minions_only(self):
        g=self.game((HOBART,BC,HOLY),board=(A,),deck=(BC,HOLY),weapon=WEAPON);self.play(g,HOBART)
        hand=self.entity(g,BC);deck=self.entity(g,BC,zone='deck');self.assertEqual((hand.attack,hand.health),(4,14));self.assertEqual((deck.attack,deck.health),(4,14))
        self.assertEqual(self.unit(g,A).attack,1);self.assertEqual(self.unit(g,HOBART).attack,2);self.assertEqual(local_cost(self.entity(g,HOLY))[0],2)

    def test_hobart_without_weapon_is_legal_and_does_not_buff_or_consume_rng(self):
        g=self.game((HOBART,BC),deck=(BC,));before=g.snapshot()['rng_state'];self.play(g,HOBART)
        self.assertEqual(self.entity(g,BC).attack,2);self.assertEqual(self.entity(g,BC,zone='deck').attack,2);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_standard_host_real_timed_return_and_original_deck_discovery_entries(self):
        g=self.game((TENWU,),board=(BC,),real_host=True);self.play(g,TENWU,self.unit(g,BC).id)
        self.assertEqual(local_cost(self.entity(g,BC))[0],1)
        g=self.game((SHEK,),deck=(BC,BC,A),real_host=True);self.play(g,SHEK);self.choose_card(g,BC)
        self.assertEqual(self.hand(g),[BC,BC])
