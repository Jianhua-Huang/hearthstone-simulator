"""Ordered continuations, card-ID cost filters and Deathwing representatives."""
from hs_sim.engine.model import CostAuraSpec
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, ChooseInOrder, CostScope, CostSpec,
    EndTurn, Game, Herald, IllegalAction, Keyword, PlayCard, PlayerSetup, ResolutionError,
    ResolutionLimitExceeded, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    UseHeroPower, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, InvokeBehavior, ModifyCost, RefreshMana,
    RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import GenerateFromPool, GenerationContext
from hs_sim.engine.representative import (build_registry, DEATHWING_FAMILY_IDS,
    DEATHWING_POOL_ID, DEATHWING_POOL_IDS)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard

CONTEXT = GenerationContext('local-2026-09-23', 'experimental')


class DeathwingTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, cost=5, attack=2, health=6))
        self.r.register_card(CardDefinition('sleep', 'Sleep', CardType.MINION, health=50, dormant_turns=None))
        self.r.register_card(CardDefinition('shield', 'Shield', CardType.MINION, health=3,
            keywords=(Keyword.DIVINE_SHIELD,)))
        self.r.register_card(CardDefinition('otherhero', 'Other hero', CardType.HERO, cost=10, health=30,
            hero_card=True, hero_armor=0, keep_hero_class=True, initial_hero_power='CATA_190p'))
        self.r.register_behavior('noop', lambda c: [])
        self.r.register_card(CardDefinition('site', 'Site', CardType.LOCATION, durability=10, on_use='noop'))
        self.r.register_behavior('clear', lambda c: [Destroy(i) for i in c.state.players[c.player_id].board])
        self.spell('mana', lambda c: [RefreshMana(c.player_id, 10)])
        for n in (1, 2, 3, 4, 7):
            self.spell(f'rank{n}', lambda c, n=n: [*[Herald(c.player_id,c.source_id) for _ in range(n)],
                InvokeBehavior('clear',c.source_id,c.player_id)])
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)
        self.spell('silence', lambda c: [Silence(c.target_id)], requires_target=True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], requires_target=True)

    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, hand=(), board=(), enemy=(), deck=(), other_hand=(), context=CONTEXT, rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,
            deck=deck, max_mana=10, mana=10), PlayerSetup('HERO_08', board=enemy, hand=other_hand,
            deck=('plain',)*6, max_mana=10, mana=10)), seed=29, generation_context=context), self.r, ruleset=rules)

    def play(self, g, name, target=None):
        p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(p,i,target)); return i

    def select(self,g,name):
        c=g.state.pending_choice
        g.apply(SelectChoice(c.player_id,c.id,(name,)))

    def hero(self,g,p=1): return g.state.entities[g.state.players[p].hero_id]
    def board(self,g,p=1): return [g.state.entities[i] for i in g.state.players[p].board]
    def cost(self,g,name,p=1):
        e=next(g.state.entities[i] for i in (*g.state.players[p].hand,*g.state.players[p].deck) if g.state.entities[i].card_id==name)
        return quote_cost(g.state,self.r,e).amount

    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)

    def rank(self,n,hand=(),**kw):
        g=self.game(hand=((f'rank{n}',) if n else ())+hand,board=('plain',)*7 if n else (),**kw)
        if n:self.play(g,f'rank{n}')
        return g

    def test_real_definition_metadata_and_option_descriptors(self):
        self.assertEqual(len(self.r.card('CATA_190h').metadata.classes),6)
        self.assertTrue(self.r.card('CATA_190h').keep_hero_class)
        self.assertEqual(self.r.card('CATA_497').metadata.tribes,('dragon',))
        for n in range(10,14): self.assertTrue(self.r.card(f'CATA_190t{n}').choice_only)
        self.assertNotIn('CATA_190t14',DEATHWING_FAMILY_IDS)
        self.assertNotIn('ONY_035',DEATHWING_FAMILY_IDS)

    def test_deathwing_preserves_class_health_adds_armor_and_power(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[1].hero_id,7),GainArmor(1,3)])
        g=self.game(hand=('hurt','CATA_190h')); self.play(g,'hurt'); self.play(g,'CATA_190h')
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(23,15))
        self.assertEqual(g.state.players[1].hero_class,CardClass.WARRIOR)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'CATA_190p')
        self.check(g)

    def test_one_two_four_cataclysms_without_replacement(self):
        for n,count in ((0,1),(1,1),(2,2),(3,2),(4,4),(7,4)):
            with self.subTest(n=n):
                g=self.rank(n,('CATA_190h',)); self.play(g,'CATA_190h')
                for j,choice in enumerate(('CATA_190t10','CATA_190t11','CATA_190t12','CATA_190t13')[:count]):
                    self.assertEqual(len(g.state.pending_choice.options),4-j)
                    self.select(g,choice)
                self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_ruthless_temporary_attack(self):
        g=self.game(hand=('CATA_190h','mana')); self.play(g,'CATA_190h'); self.select(g,'CATA_190t10')
        self.play(g,'mana'); g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.hero(g).attack,5)
        g.apply(EndTurn(1)); self.assertEqual(self.hero(g).attack,0); self.check(g)

    def test_reign_full_board_still_consumes_choice(self):
        g=self.game(hand=('CATA_190h',),board=('plain',)*7); self.play(g,'CATA_190h'); self.select(g,'CATA_190t10')
        self.assertEqual(len(self.board(g)),7); self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_reign_dragon_is_independent_entity(self):
        g=self.game(hand=('CATA_190h',)); source=self.play(g,'CATA_190h'); self.select(g,'CATA_190t10')
        dragon=self.board(g)[0]
        self.assertEqual((dragon.card_id,dragon.attack,dragon.health),('CATA_190t14',12,12))
        self.assertNotEqual(dragon.id,source); self.check(g)

    def test_topple_uses_current_health_ignores_dormant_location(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[2].board[0],9)])
        g=self.game(hand=('hurt','CATA_190h'),enemy=('EX1_563','plain','sleep','site'))
        self.play(g,'hurt'); victim=self.board(g,2)[1].id; self.play(g,'CATA_190h'); self.select(g,'CATA_190t11')
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.board(g,2)),3); self.check(g)

    def test_topple_ties_destroy_exactly_one_with_seeded_replay(self):
        g=self.game(hand=('CATA_190h',),enemy=('plain','plain'))
        self.play(g,'CATA_190h'); self.select(g,'CATA_190t11')
        self.assertEqual(len(self.board(g,2)),1); self.check(g)

    def test_topple_reads_board_after_previous_branch_deathrattle(self):
        g=self.rank(2,('CATA_190h',),enemy=('FP1_007',))
        self.play(g,'CATA_190h'); self.select(g,'CATA_190t12')
        self.assertEqual(self.board(g,2)[0].card_id,'FP1_007t')
        self.check(g); self.select(g,'CATA_190t11'); self.assertEqual(self.board(g,2),[]); self.check(g)

    def test_raze_is_enemy_minion_ability_damage(self):
        g=self.game(hand=('CATA_190h',),board=('EX1_563','plain'),enemy=('plain','site','sleep'))
        self.play(g,'CATA_190h'); self.select(g,'CATA_190t12')
        self.assertEqual([e.health for e in self.board(g)],[12,6])
        self.assertEqual(self.board(g,2)[0].health,2)
        self.assertEqual(self.hero(g,2).health,30); self.check(g)

    def test_raze_divine_shield_and_reborn(self):
        g=self.game(hand=('CATA_190h',),enemy=('shield','ULD_205'))
        self.play(g,'CATA_190h'); self.select(g,'CATA_190t12')
        self.assertEqual(self.board(g,2)[0].health,3)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.board(g,2)[0].keywords)
        self.assertEqual(self.board(g,2)[-1].health,1); self.check(g)

    def test_empty_raze_and_topple_finish(self):
        for cid in ('CATA_190t11','CATA_190t12'):
            g=self.game(hand=('CATA_190h',)); self.play(g,'CATA_190h'); self.select(g,cid)
            self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_enthrall_five_new_cost_one_cards_and_private_deck(self):
        g=self.game(hand=('CATA_190h',),deck=('plain',)); self.play(g,'CATA_190h'); self.select(g,'CATA_190t13')
        generated=[g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].card_id!='plain']
        self.assertEqual(len(generated),5); self.assertEqual(len({e.id for e in generated}),5)
        self.assertTrue({e.card_id for e in generated}.issubset(DEATHWING_POOL_IDS))
        self.assertEqual([quote_cost(g.state,self.r,e).amount for e in generated],[1]*5)
        self.assertNotIn('EX1_563',json.dumps(g.observe(2))); self.assertNotIn('CATA_497',json.dumps(g.observe(2)))
        self.check(g)

    def test_enthrall_missing_context_rolls_back_to_choice(self):
        g=self.game(hand=('CATA_190h',),context=None); self.play(g,'CATA_190h'); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.select(g,'CATA_190t13')
        self.assertEqual(g.snapshot(),before); self.select(g,'CATA_190t10'); self.check(g)

    def test_every_choice_boundary_can_save_resume_and_replay(self):
        g=self.rank(4,('CATA_190h',)); self.play(g,'CATA_190h')
        for cid in ('CATA_190t13','CATA_190t12','CATA_190t10','CATA_190t11'):
            self.check(g); restored=Game.from_snapshot(g.snapshot(),self.r)
            self.select(g,cid); self.select(restored,cid); self.assertEqual(g.snapshot(),restored.snapshot())
        self.check(g)

    def test_reselection_wrong_seat_and_stale_choice_rejected(self):
        g=self.rank(2,('CATA_190h',)); self.play(g,'CATA_190h'); old=g.state.pending_choice.id
        self.select(g,'CATA_190t10'); before=g.snapshot()
        for action in (SelectChoice(1,old,('CATA_190t11',)),SelectChoice(2,g.state.pending_choice.id,('CATA_190t11',)),
                       SelectChoice(1,g.state.pending_choice.id,('CATA_190t10',))):
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)

    def test_ultraxion_linear_capture_before_own_herald(self):
        for n,expected in ((0,9),(1,8),(2,7),(4,5),(7,2)):
            g=self.rank(n,('CATA_497','CATA_190h')); self.play(g,'CATA_497')
            self.assertEqual(self.cost(g,'CATA_190h'),expected)
            self.assertEqual(len(g.state.herald_history),n+1); self.check(g)

    def test_ultraxion_scope_includes_future_generated_and_deck_cards(self):
        self.spell('create',lambda c:[AddToHand(1,'CATA_190h')])
        g=self.game(hand=('CATA_497','create'),deck=('CATA_190h',)); self.play(g,'CATA_497'); self.play(g,'create')
        for i in (*g.state.players[1].deck,*g.state.players[1].hand):
            if g.state.entities[i].card_id=='CATA_190h': self.assertEqual(quote_cost(g.state,self.r,g.state.entities[i]).amount,9)
        self.check(g)

    def test_ultraxion_discount_persists_source_death_and_silence(self):
        g=self.game(hand=('CATA_497','CATA_190h','silence','kill')); i=self.play(g,'CATA_497')
        self.play(g,'silence',i); self.play(g,'kill',i)
        self.assertEqual(self.cost(g,'CATA_190h'),9); self.check(g)

    def test_ultraxion_direct_summon_has_no_battlecry(self):
        self.spell('summon',lambda c:[Summon(1,'CATA_497')]); g=self.game(hand=('summon','CATA_190h'))
        self.play(g,'summon'); self.assertEqual(self.cost(g,'CATA_190h'),10); self.assertEqual(g.state.herald_history,[]); self.check(g)

    def test_ultraxion_stacks_and_never_increases_at_floor(self):
        g=self.rank(7,('CATA_497','CATA_190h','mana','CATA_497'))
        self.play(g,'CATA_497'); self.play(g,'mana'); self.play(g,'CATA_497')
        self.assertEqual(self.cost(g,'CATA_190h'),0); self.check(g)

    def test_ultraxion_does_not_discount_other_hero_progeny_or_opponent(self):
        g=self.game(hand=('CATA_497','otherhero','CATA_190t14'),other_hand=('CATA_190h',))
        self.play(g,'CATA_497')
        for cid in ('otherhero','CATA_190t14'):self.assertEqual(self.cost(g,cid),10)
        self.assertEqual(self.cost(g,'CATA_190h',2),10); self.check(g)

    def test_ultraxion_full_board_still_counts_and_discounts(self):
        g=self.game(hand=('CATA_497','CATA_190h'),board=('plain',)*6)
        self.play(g,'CATA_497'); self.assertEqual(len(self.board(g)),7)
        self.assertEqual(len(g.state.herald_history),1); self.assertEqual(self.cost(g,'CATA_190h'),9); self.check(g)

    def test_ultraxion_copy_does_not_copy_battlecry_discount(self):
        self.spell('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(hand=('CATA_497','copy','CATA_190h')); self.play(g,'CATA_497'); self.play(g,'copy')
        self.assertEqual(self.cost(g,'CATA_190h'),9); self.assertEqual(len(g.state.herald_history),1); self.check(g)

    def test_quota_frozen_when_branch_changes_herald_count(self):
        self.r.register_behavior('advance',lambda c:[Herald(1,c.source_id)]*4
            if c.event.source_id!=c.source_id and c.state.entities[c.event.source_id].card_id=='CATA_190t14' else [])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,
            triggers=(TriggerSpec('minion_summoned','advance'),)))
        self.spell('watch',lambda c:[Summon(1,'watcher')])
        g=self.rank(2,('watch','CATA_190h')); self.play(g,'watch'); self.play(g,'CATA_190h')
        self.select(g,'CATA_190t10'); self.assertEqual(len(g.state.herald_history),6)
        self.select(g,'CATA_190t11'); self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_id_filter_conjoins_kind_and_next_use_consumption(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-3,card_ids=('plain',)),uses_remaining=1)])
        g=self.game(hand=('discount','CS2_182','plain','plain')); self.play(g,'discount'); self.play(g,'CS2_182')
        self.assertEqual(self.cost(g,'plain'),2); self.play(g,'plain'); self.assertEqual(self.cost(g,'plain'),5); self.check(g)

    def test_id_filter_does_not_match_wrong_kind(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-3,card_types=(CardType.SPELL,),card_ids=('plain',)))])
        g=self.game(hand=('discount','plain')); self.play(g,'discount'); self.assertEqual(self.cost(g,'plain'),5); self.check(g)

    def test_id_filter_cost_aura_follows_live_source(self):
        self.r.register_card(CardDefinition('aura','Aura',CardType.MINION,health=3,
            cost_auras=(CostAuraSpec(CostSpec(delta=-2,card_ids=('plain',))),)))
        g=self.game(board=('aura',),hand=('plain','kill','CS2_182'))
        self.assertEqual(self.cost(g,'plain'),3); self.assertEqual(self.cost(g,'CS2_182'),4)
        self.play(g,'kill',self.board(g)[0].id); self.assertEqual(self.cost(g,'plain'),5); self.check(g)

    def test_id_filter_local_mismatch_skips_attachment(self):
        self.spell('discount',lambda c:[ModifyCost(c.state.players[1].hand[-1],CostSpec(delta=-3,card_ids=('CS2_182',)))])
        g=self.game(hand=('discount','plain')); self.play(g,'discount')
        self.assertEqual(self.cost(g,'plain'),5); self.assertEqual(g.state.entities[g.state.players[1].hand[0]].enchantments,[]); self.check(g)

    def test_id_filter_generated_mismatch_rejected_before_rng(self):
        self.spell('bad',lambda c:[GenerateFromPool(1,DEATHWING_POOL_ID,count=5,cost=CostSpec(set_to=1,card_ids=('CATA_497',)))])
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_id_filter_generated_match_attaches_and_expires(self):
        self.spell('create',lambda c:[AddToHand(1,'plain',cost=CostSpec(delta=-3,card_ids=('plain',)),expires_turn=c.state.turn)])
        g=self.game(hand=('create',)); self.play(g,'create'); self.assertEqual(self.cost(g,'plain'),2)
        g.apply(EndTurn(1)); self.assertEqual(self.cost(g,'plain'),5); self.check(g)

    def test_id_filter_current_copy_applies_player_discount_once(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-2,card_ids=('plain',)))])
        self.spell('copy',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),1,Zone.HAND)])
        g=self.game(hand=('discount','plain','copy')); self.play(g,'discount'); self.play(g,'copy')
        cards=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([quote_cost(g.state,self.r,e).amount for e in cards],[3,3]); self.check(g)

    def test_id_filter_local_then_player_modifier_order(self):
        self.spell('create',lambda c:[AddToHand(1,'plain',cost=CostSpec(set_to=1)),
            AddCostModifier(1,CostSpec(delta=-3,card_ids=('plain',)))])
        g=self.game(hand=('create',)); self.play(g,'create'); self.assertEqual(self.cost(g,'plain'),0); self.check(g)

    def test_id_filter_validation(self):
        for value in ([],None,('plain','plain'),('',),(3,),('  ',)):
            with self.assertRaises(ValueError):CostSpec(card_ids=value)
        with self.assertRaises(ValueError):AddCostModifier(1,CostSpec(card_ids=('plain',)),scope=CostScope.STARSHIP_LAUNCH)

    def test_id_filter_snapshot_tamper_rejected(self):
        g=self.game(hand=('CATA_497',)); self.play(g,'CATA_497'); s=g.snapshot()
        s['state']['players']['1']['cost_modifiers'][0]['spec']['card_ids']=['CATA_190h','CATA_190h']
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)

    def test_schema_36_is_rejected(self):
        g=self.game(); s=g.snapshot(); s['schema_version']=36
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)

    def ordered(self,options,count=2,tail=()):
        self.spell('ordered',lambda c:[ChooseInOrder(1,options,count,c.source_id),*tail])
        g=self.game(hand=('ordered',)); self.play(g,'ordered'); return g

    def test_ordered_branches_follow_selected_order_then_tail(self):
        self.r.register_behavior('damage_armor',lambda c:[Damage(c.state.players[1].hero_id,5)])
        # Hero ID is resolved at execution via behavior, not guessed in a fixture.
        self.spell('ordered',lambda c:[ChooseInOrder(1,(
            ChoiceOption('armor','Armor',(GainArmor(1,5),)),
            ChoiceOption('hit','Hit',(Damage(c.state.players[1].hero_id,5),))),2,c.source_id),GainArmor(1,1)])
        for order,hp,armor in ((('hit','armor'),25,6),(('armor','hit'),30,1)):
            g=self.game(hand=('ordered',)); self.play(g,'ordered')
            for o in order:self.select(g,o)
            self.assertEqual((self.hero(g).health,self.hero(g).armor),(hp,armor)); self.check(g)

    def test_nested_choice_finishes_before_next_outer_choice(self):
        g=self.ordered((ChoiceOption('nested','Nested',(RequestChoice(2,(ChoiceOption('inside','Inside',(GainArmor(2,3),)),)),)),
                        ChoiceOption('outer','Outer',(GainArmor(1,2),))))
        self.select(g,'nested'); self.assertEqual(g.state.pending_choice.player_id,2); self.check(g)
        self.select(g,'inside'); self.assertEqual(g.state.pending_choice.player_id,1); self.assertEqual(self.hero(g,2).armor,3)
        self.select(g,'outer'); self.assertEqual(self.hero(g).armor,2); self.check(g)

    def test_zero_ordered_choice_does_not_suspend(self):
        g=self.ordered((),0,(GainArmor(1,2),)); self.assertIsNone(g.state.pending_choice); self.assertEqual(self.hero(g).armor,2); self.check(g)

    def test_zero_ordered_choice_rejects_missing_source(self):
        self.spell('bad',lambda c:[ChooseInOrder(1,(),0,99999)])
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_lethal_branch_ends_without_next_choice_or_tail(self):
        self.spell('ordered',lambda c:[ChooseInOrder(1,(
            ChoiceOption('kill','Kill',(Damage(c.state.players[2].hero_id,50),)),
            ChoiceOption('armor','Armor',(GainArmor(1,5),))),2),GainArmor(1,10)])
        g=self.game(hand=('ordered',)); self.play(g,'ordered'); self.select(g,'kill')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.hero(g).armor,0); self.check(g)

    def test_ordered_choice_validates_unselected_branch(self):
        self.spell('bad',lambda c:[ChooseInOrder(1,(ChoiceOption('ok','OK'),
            ChoiceOption('bad','Bad',(InvokeBehavior('missing',c.source_id,1),))),1)])
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_ordered_choice_strict_counts_and_duplicates(self):
        opts=(ChoiceOption('one','One'),)
        for n in (-1,True,2):
            with self.assertRaises(ValueError):ChooseInOrder(1,opts,n)
        with self.assertRaises(ValueError):ChooseInOrder(1,opts*2)
        with self.assertRaises(ValueError):ChooseInOrder(1,list(opts))

    def test_ordered_option_limit_rolls_back(self):
        self.spell('many',lambda c:[ChooseInOrder(1,tuple(ChoiceOption(str(i),str(i)) for i in range(33)),1)])
        g=self.game(hand=('many',)); before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'many')
        self.assertEqual(g.snapshot(),before)

    def test_branch_exception_rolls_back_only_current_selection(self):
        self.r.register_behavior('explode',lambda c: (_ for _ in ()).throw(RuntimeError('branch error')))
        self.spell('ordered',lambda c:[ChooseInOrder(1,(ChoiceOption('ok','OK',(GainArmor(1,2),)),
            ChoiceOption('bad','Bad',(InvokeBehavior('explode',c.source_id,1),))),2)])
        g=self.game(hand=('ordered',)); self.play(g,'ordered'); self.select(g,'ok'); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'bad')
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.hero(g).armor,2)


if __name__=='__main__':unittest.main()
