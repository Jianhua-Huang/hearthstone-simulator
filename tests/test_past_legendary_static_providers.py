"""Real static providers retain shared cost facts, combat and packet lifecycles."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_legendary_static_providers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import AddCostModifier,quote_cost,capture_generated_quote_fact
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Heal,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.model import (CardDefinition,CardType,CostAuraSpec,CostSpec,DamageKind,HealingKind,
    Keyword,KeywordAuraSpec,SpellRepeatSpec,SpellSchool,TargetSpec,TribeChangeSpec,Zone)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

AVI,REPRINT,SCARGIL,LADY,KAYN,SMITE,MURK,INARA,KANGOR,MOON=native.ROOTS
P='k683.';PLAIN=P+'plain';MURLOC=P+'murloc';PIRATE=P+'pirate';ALL=P+'all';FREE=P+'free';POISON=P+'poison';TAUNT=P+'taunt'
NATURE=P+'nature';ARCANE=P+'arcane';OTHER=P+'other';WAIT=P+'wait';HEAL=P+'heal';POKE=P+'poke';HUSH=P+'hush'
KILL=P+'kill';BOUNCE=P+'bounce';COPY=P+'copy';TAKE=P+'take';TURN=P+'turn';REDUCE=P+'reduce';FAIL=P+'fail';AXE=P+'axe';DOUBLE=P+'double'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_legendary_static_providers(r)
    for cid,tribes,cost,keys in((PLAIN,(),5,()),(MURLOC,('murloc',),5,()),(PIRATE,('pirate',),5,()),
            (ALL,('all',),5,()),(FREE,('murloc',),0,()),(POISON,(),5,(Keyword.POISONOUS,)),(TAUNT,(),5,(Keyword.TAUNT,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=40,keywords=keys,metadata=metadata(collectible=False,tribes=tribes)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    for cid,school in((NATURE,SpellSchool.NATURE),(ARCANE,SpellSchool.ARCANE),(OTHER,None)):
        r.register_behavior(cid,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=4,on_play=cid,spell_school=school,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K683 deliberate accepted-cost rollback')))
    def wait(c):
        source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==LADY)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('silence','Silence original source',(Silence(source),)),
            ChoiceOption('fault','Fail',(Silence(source),RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WAIT,wait);r.register_card(CardDefinition(WAIT,WAIT,CardType.SPELL,cost=4,on_play=WAIT,spell_school=SpellSchool.NATURE,metadata=metadata(collectible=False)))
    for cid,body,target in((HEAL,lambda c:(Heal(c.target_id,3,c.source_id,HealingKind.SPELL),),TargetSpec()),
            (POKE,lambda c:(Damage(c.target_id,10,c.source_id,DamageKind.SPELL),),TargetSpec()),
            (HUSH,lambda c:(Silence(c.target_id),),board),(KILL,lambda c:(Destroy(c.target_id,c.source_id),),board),
            (BOUNCE,lambda c:(ReturnToHand(c.target_id),),board),(COPY,lambda c:(CopyMinion(c.target_id,c.player_id),),board),
            (TAKE,lambda c:(ChangeControl(c.target_id,3-c.player_id),),board),
            (TURN,lambda c:(Transform(c.target_id,PLAIN),),board),
            (REDUCE,lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.SPELL,)),source_id=c.source_id),),None)):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=metadata(collectible=False)))
    for tribe in('murloc','pirate'):
        cid=P+'tribe.'+tribe
        def body(c,tribe=tribe):
            target=c.state.entities[c.target_id]
            ref=MinionReference.capture(target)if target.zone==Zone.BOARD else CardReference.capture(target)
            return(ChangeMinionTribes(ref,TribeChangeSpec('set',(tribe,)),c.source_id),)
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,Zone.HAND),kinds=(CardType.MINION,),relation='friendly'),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(AXE,AXE,CardType.WEAPON,attack=2,durability=3,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=20,spell_repeats=(SpellRepeatSpec(2,class_mode='any'),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastLegendaryStaticTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),player=1):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=('card.1',)*20,mana=10,max_mana=10)for p in(1,2)),active_player=player,seed=683),fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def price(self,g,cid,p=1):return quote_cost(g.state,g.registry,self.entity(g,cid,p)).amount
    def cycle(self,g,p=1):g.apply(EndTurn(p));g.apply(EndTurn(3-p))

    def test_all_ten_original_faces_keep_complete_source_and_reference_roles(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['cards']),10);self.assertEqual(len(d['official_observations']),24)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_legendary_source_bound'])
        for row in d['cards']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(row['record']['id']))),row['pool_card_sha256'])
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_every_real_provider_has_ordinary_paid_entry_and_full_printed_stats(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);c=g.registry.card(cid);e=self.unit(g,cid)
                self.assertEqual((e.attack,e.health),(c.attack,c.health));self.assertEqual(g.state.players[1].mana,10-c.cost)
                self.assertEqual([x.card_id for x in g.state.play_history],[cid])

    def test_both_avianas_set_all_own_minions_to_one_after_their_own_full_payment(self):
        for cid in(AVI,REPRINT):
            with self.subTest(card=cid):
                g=self.game((cid,MURLOC,PLAIN,NATURE),enemy_hand=(PLAIN,));self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,1);self.assertEqual((self.price(g,MURLOC),self.price(g,PLAIN),self.price(g,NATURE),self.price(g,PLAIN,2)),(1,1,4,5))
                self.play(g,MURLOC);self.assertEqual(g.state.players[1].mana,0)
        self.portable(g)

    def test_scargil_sets_current_murlocs_all_tribes_free_cards_and_own_copy_to_one(self):
        g=self.game((MURLOC,ALL,FREE,SCARGIL,PLAIN),board=(SCARGIL,),enemy_hand=(MURLOC,))
        self.assertEqual(tuple(self.price(g,cid)for cid in(MURLOC,ALL,FREE,SCARGIL,PLAIN)),(1,1,1,1,5))
        self.assertEqual(self.price(g,MURLOC,2),5)

    def test_scargil_changes_follow_current_hand_tribe_and_have_no_per_turn_budget(self):
        g=self.game((PLAIN,MURLOC,MURLOC,P+'tribe.murloc'),board=(SCARGIL,));own=self.entity(g,PLAIN).id
        self.assertEqual(self.price(g,PLAIN),5);self.play(g,P+'tribe.murloc',own);self.assertEqual(self.price(g,PLAIN),1)
        self.play(g,PLAIN);self.play(g,MURLOC);self.play(g,MURLOC);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_nature_aura_only_reduces_own_nature_school_and_quote_query_is_pure(self):
        g=self.game((NATURE,ARCANE,OTHER,PLAIN),board=(LADY,),enemy_hand=(NATURE,));saved=deepcopy(g.snapshot())
        self.assertEqual(tuple(self.price(g,cid)for cid in(NATURE,ARCANE,OTHER,PLAIN)),(2,4,4,5));self.assertEqual(self.price(g,NATURE,2),4)
        self.assertEqual(g.snapshot(),saved);self.play(g,NATURE);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_nature_aura_stacks_original_reducers_and_copied_sources_with_zero_floor(self):
        g=self.game((REDUCE,NATURE,ARCANE,COPY),board=(LADY,));self.play(g,REDUCE)
        self.assertEqual((self.price(g,NATURE),self.price(g,ARCANE)),(1,3));self.play(g,COPY,self.unit(g,LADY).id)
        self.assertEqual((self.price(g,NATURE),self.price(g,ARCANE)),(0,3));self.play(g,NATURE);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_generated_and_frozen_quotes_accept_original_nature_and_tribal_payer_facts(self):
        g=self.game(board=(LADY,SCARGIL))
        for pid,cid,amount in((1,NATURE,2),(2,NATURE,4),(1,MURLOC,1),(1,FREE,1),(1,PLAIN,5)):
            fact=capture_generated_quote_fact(g.state,g.registry,pid,cid);self.assertEqual(fact.amount,amount)
            validate_generated_quote_fact(g.registry,fact)
        self.portable(g)

    def test_source_silence_bounce_transform_and_control_retire_actual_cost_contributions(self):
        for source,subject,discounted in((AVI,PLAIN,1),(SCARGIL,MURLOC,1),(LADY,NATURE,2)):
            for action in(HUSH,BOUNCE,TURN,TAKE):
                with self.subTest(source=source,action=action):
                    g=self.game((subject,action),board=(source,));self.assertEqual(self.price(g,subject),discounted)
                    self.play(g,action,self.unit(g,source).id);self.assertEqual(self.price(g,subject),4 if subject==NATURE else 5)

    def test_accepted_nature_payment_restores_and_remains_original_after_source_silence(self):
        g=self.game((WAIT,NATURE),board=(LADY,));self.play(g,WAIT);self.assertEqual(g.state.players[1].mana,8)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'silence');self.assertEqual(self.price(g,NATURE),4)
        self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_actual_repeated_nature_casts_keep_one_discounted_original_payment(self):
        g=self.game((NATURE,),board=(LADY,DOUBLE));self.play(g,NATURE)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(self.hero(g,2).health,28)
        self.assertEqual([x.card_id for x in g.state.cast_history],[NATURE,NATURE]);self.portable(g)

    def test_kayn_bypasses_taunt_for_himself_other_minions_and_hero_then_silence_restores_gate(self):
        g=self.game((KAYN,AXE,HUSH),board=(PLAIN,MURLOC),enemy=(TAUNT,));self.play(g,KAYN);self.play(g,AXE)
        for actor in(self.unit(g,KAYN).id,self.unit(g,PLAIN).id,self.hero(g).id):g.apply(Attack(1,actor,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,23);self.play(g,HUSH,self.unit(g,KAYN).id);saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.unit(g,MURLOC).id,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_smite_grants_current_pirates_charge_including_himself(self):
        g=self.game((SMITE,));self.play(g,SMITE);g.apply(Attack(1,self.unit(g,SMITE).id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,24)
        g=self.game((PIRATE,PLAIN,P+'tribe.pirate'),board=(SMITE,));self.play(g,PIRATE);self.play(g,PLAIN)
        g.apply(Attack(1,self.unit(g,PIRATE).id,self.hero(g,2).id));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.unit(g,PLAIN).id,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);self.play(g,P+'tribe.pirate',self.unit(g,PLAIN).id)
        g.apply(Attack(1,self.unit(g,PLAIN).id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,26);self.portable(g)

    def test_murk_eye_counts_other_current_murlocs_on_both_boards_and_survives_control_change(self):
        g=self.game((P+'tribe.murloc',TAKE),board=(MURK,MURLOC,PLAIN),enemy=(MURLOC,ALL))
        own=self.unit(g,MURK).id;self.assertEqual(g.state.entities[own].attack,5)
        self.play(g,P+'tribe.murloc',self.unit(g,PLAIN).id);self.assertEqual(g.state.entities[own].attack,6)
        self.play(g,TAKE,own);self.assertEqual(g.state.entities[own].attack,6);self.portable(g)

    def test_inara_grants_current_own_turn_hero_attack_and_exact_two_attack_budget(self):
        g=self.game(board=(INARA,));hero=self.hero(g).id
        self.assertEqual(g.state.entities[hero].attack,2);self.assertIn(Keyword.WINDFURY,g.state.entities[hero].keywords)
        g.apply(Attack(1,hero,self.hero(g,2).id));g.apply(Attack(1,hero,self.hero(g,2).id));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,hero,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(1));self.assertEqual(g.state.entities[hero].attack,0)
        self.assertNotIn(Keyword.WINDFURY,g.state.entities[hero].keywords);g.apply(EndTurn(2));self.assertEqual(g.state.entities[hero].attack,2);self.portable(g)

    def test_inara_control_and_current_copy_follow_actual_controller_turn(self):
        g=self.game((TAKE,),board=(INARA,));self.play(g,TAKE,self.unit(g,INARA).id)
        self.assertEqual((self.hero(g).attack,self.hero(g,2).attack),(0,0));g.apply(EndTurn(1))
        self.assertEqual((self.hero(g).attack,self.hero(g,2).attack),(0,2));self.assertIn(Keyword.WINDFURY,self.hero(g,2).keywords);self.portable(g)
        g=self.game((COPY,HUSH),board=(INARA,));original=self.unit(g,INARA).id;self.play(g,COPY,original)
        self.assertEqual(self.hero(g).attack,4);self.play(g,HUSH,original);self.assertEqual(self.hero(g).attack,2)

    def test_kangor_doubles_friendly_healing_even_on_enemy_targets_without_enemy_provider_product(self):
        g=self.game((POKE,POKE,HEAL,HEAL),board=(KANGOR,),enemy=(KANGOR,))
        self.play(g,POKE,self.hero(g).id);self.play(g,POKE,self.hero(g,2).id)
        self.play(g,HEAL,self.hero(g).id);self.play(g,HEAL,self.hero(g,2).id)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(26,26));self.portable(g)

    def test_kangor_own_lifesteal_uses_damage_once_then_shared_healing_scale(self):
        g=self.game((POKE,),board=(KANGOR,),enemy=(PLAIN,));self.play(g,POKE,self.hero(g).id)
        g.apply(Attack(1,self.unit(g,KANGOR).id,self.unit(g,PLAIN,2).id));self.assertEqual(self.hero(g).health,22)
        self.assertEqual(self.unit(g,KANGOR).health,2)

    def test_multiple_kangors_multiply_original_healing_with_health_cap(self):
        g=self.game((POKE,HEAL),board=(KANGOR,KANGOR));self.play(g,POKE,self.hero(g).id);self.play(g,HEAL,self.hero(g).id)
        self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_moonfang_caps_only_its_own_incoming_packet_and_current_copy_preserves_cap(self):
        g=self.game((COPY,POKE,POKE,POKE,HUSH),board=(MOON,PLAIN));own=self.unit(g,MOON).id;self.play(g,COPY,own)
        copied=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==MOON and i!=own)
        self.play(g,POKE,own);self.assertEqual(g.state.entities[own].health,2)
        self.play(g,POKE,self.unit(g,PLAIN).id);self.assertEqual(self.unit(g,PLAIN).health,30)
        self.play(g,HUSH,own);self.play(g,POKE,own);self.assertEqual(g.state.entities[own].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[copied].health,3);self.portable(g)

    def test_positive_poisonous_retaliation_still_kills_moonfang_through_one_damage_cap(self):
        g=self.game(board=(MOON,),enemy=(POISON,));own=self.unit(g,MOON).id
        g.apply(Attack(1,own,self.unit(g,POISON,2).id));self.assertEqual(g.state.entities[own].zone,Zone.GRAVEYARD)

    def test_second_player_nature_payer_and_frozen_cost_replay_use_correct_owner(self):
        g=self.game((NATURE,),board=(LADY,),enemy_hand=(NATURE,),player=2)
        self.assertEqual((self.price(g,NATURE,2),self.price(g,NATURE,1)),(2,4));self.play(g,NATURE,player=2)
        self.assertEqual(g.state.players[2].mana,8);self.portable(g)

    def test_new_finite_declarations_reject_wrong_school_operations_tribal_values_and_hero_scope(self):
        with self.assertRaises(ValueError):CostAuraSpec(CostSpec(delta=-1,card_types=(CardType.SPELL,)),relation='friendly_nature_spells')
        with self.assertRaises(ValueError):CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.MINION,)),tribes_any=('murloc',))
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.WINDFURY,'friendly_minions',condition='controller_turn')

    def test_standard_host_real_nature_spell_gets_new_discount_other_school_keeps_price(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(LADY,'EX1_238','CORE_CS2_029'),deck=('CORE_CS2_120',)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_120',)*8,mana=10,max_mana=10)),seed=683,generation_context=h.context),h.registry)
        self.play(g,LADY);self.assertEqual((self.price(g,'EX1_238'),self.price(g,'CORE_CS2_029')),(0,4))
        self.play(g,'EX1_238',self.hero(g,2).id);self.play(g,'CORE_CS2_029',self.hero(g,2).id)
        self.assertEqual((g.state.players[1].mana,self.hero(g,2).health),(0,21));self.portable(g)
