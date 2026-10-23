from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_named_shuffle_cards import (
    ACORN, ARMLESS, CATCH, CONDUCTOR, DEPENDENCIES, DISPLAY, EMPTY, EXISTING,
    FELBEAST, FIEND, FRAGMENT, GRUB, HATCHLING, JAILER, JADE_FORMS, LEAVES, LOUD,
    MINER, NUMERIC, OIL, PATRIARCH, RABBIT, SALESMAN, SATISFIED, SLUDGE, SQUIRREL,
    SWARMER, TASKMASTER, ZERGLING, ZOMBIE, load_batch,
)
from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayerSetup, Scenario, TargetSpec, TriggerSpec, UseHandAction, Zone,
)
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Damage, Destroy, Draw, InvokeBehavior,
    RequestChoice, Silence, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import DamageKind, TargetMode
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.zones import CardReference, DestroyDeckCard, DestroyStoredCard, DiscardCard
from tools import card_batch as batch


P = 'test.k465.'
NOOP, KILL, SILENCE, HAND_BUFF, BOARD_BUFF, HURT, DRAW, DISCARD, BREAK_HAND, BREAK_DECK, TAKE, ACTIVE, FAIL, WATCH = (
    P+s for s in ('noop', 'kill', 'silence', 'hand_buff', 'board_buff', 'hurt', 'draw',
        'discard', 'break_hand', 'break_deck', 'take', 'active', 'fail', 'watch'))
YETI, RAVEN, POWER, COUNTER, FLASHBACK = 'CORE_CS2_182', 'KAR_300', 'CORE_EX1_012', 'CORE_EX1_287', 'TIME_711'
CONTEXT = GenerationContext('k465-explicit-named-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'thirteen-named-leaves-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c): raise ResolutionError('K465 deliberate late native failure')

    def stored(c, zone, cid=SLUDGE):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[c.player_id], zone)
            if c.state.entities[i].card_id == cid))

    def hand_buff(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind == CardType.MINION)
        return (BuffStoredCard(CardReference.capture(target), 2, 3, c.source_id),)

    bodies = {
        NOOP: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), HAND_BUFF: hand_buff,
        BOARD_BUFF: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 9, c.source_id, DamageKind.EFFECT),),
        DRAW: lambda c: (Draw(c.player_id, 1, c.source_id),),
        DISCARD: lambda c: (DiscardCard(stored(c, 'hand'), c.source_id),),
        BREAK_HAND: lambda c: (DestroyStoredCard(stored(c, 'hand'), c.source_id),),
        BREAK_DECK: lambda c: (DestroyDeckCard(stored(c, 'deck'), c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        ACTIVE: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),), FAIL: fail,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, SILENCE, BOARD_BUFF, TAKE, ACTIVE) else None))

    def watch(c):
        e = c.event; source = c.state.entities.get(e.source_id); cid = None if source is None else source.card_id
        target = c.state.entities.get(e.target_id)
        summon = e.kind == 'minion_summoned' and target is not None and target.card_id == FELBEAST
        deck = e.kind == 'card_added_to_deck' and cid in (JAILER, HATCHLING, SQUIRREL)
        hand = e.kind == 'card_added_to_hand' and cid in (LOUD, CONDUCTOR, SALESMAN)
        damage = e.kind == 'damage_dealt' and cid == SLUDGE
        if mode == 'fail' and (summon or deck or hand or damage):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = (mode == 'wait_summon' and summon or mode == 'wait_deck' and deck or
            mode == 'wait_hand' and hand or mode == 'wait_damage' and damage)
        if waiting:
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()

    behavior = WATCH+'.'+mode; r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, attack=0, durability=50,
        triggers=tuple(TriggerSpec(e, behavior) for e in ('minion_summoned', 'card_added_to_deck',
            'card_added_to_hand', 'damage_dealt')) if mode != 'normal' else ()))
    r.validate(); return r


class PastOneCostNamedShuffleTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, deck=(NOOP,)*6, enemy_hand=(), enemy_board=(),
             enemy_deck=(NOOP,)*6, active=1, mode='normal'):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp', weapon_card_id=WATCH if mode != 'normal' else None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp')), active_player=active, seed=465, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]

    def drain(self, g):
        while g.state.pending_choice is not None: self.choose(g)

    def test_twenty_eight_complete_rows_and_fifty_six_full_faces_remain_pinned(self):
        d=load_batch(); rows={x['record']['id']:x['record'] for x in d['dependencies']+d['existing_dependencies']}; hashes={}
        self.assertEqual((len(rows),len(d['official_observations'])),(28,56))
        self.assertEqual(set(rows),set(DEPENDENCIES+EXISTING))
        for o in d['official_observations']:
            if o['response_file'] not in hashes:hashes[o['response_file']]=batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']],o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'],DISPLAY.get(o['card_id']),numeric_normalizations=NUMERIC.get(o['card_id']))
        self.assertEqual(batch.sha(Path(d['source']['path'])),d['source']['sha256'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_named_family_links_and_noncollectible_native_bodies_are_preserved(self):
        d=load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']+d['existing_dependencies']}
        faces={(o['card_id'],o['locale']):o['face'] for o in d['official_observations']}
        links={TASKMASTER:(MINER,),CATCH:(GRUB,),FIEND:(FELBEAST,),ZOMBIE:(ARMLESS,EMPTY),
            HATCHLING:(PATRIARCH,),CONDUCTOR:(SLUDGE,),SALESMAN:(OIL,),SQUIRREL:(ACORN,SATISFIED)}
        for parent,children in links.items():
            for locale in ('zh_CN','en_US'):
                for child in children:
                    self.assertIn(rows[child]['dbf_id'],faces[parent,locale]['childIds'])
                    self.assertEqual(faces[child,locale]['parentId'],rows[parent]['dbf_id'])
        for cid in set(DEPENDENCIES)-set(LEAVES):self.assertFalse(rows[cid]['collectible'])
        self.assertEqual(rows[JAILER]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],rows[FRAGMENT]['dbf_id'])

    def test_restored_jade_display_retains_both_full_bodies_and_old_printing_checks(self):
        d=load_batch();raw=next(x['record'] for x in d['dependencies'] if x['record']['id']==SWARMER)
        for o in d['official_observations']:
            if o['card_id']==SWARMER:
                self.assertEqual(raw['text' if o['locale']=='zh_CN' else 'text_en'].count('@'),1)
                batch.check_face(raw,o['face'],o['locale'],DISPLAY[SWARMER])
        prior=batch.read(Path('data/cards/past-one-cost-awakening-v1.json'))
        original=next(x['record'] for x in prior['dependencies'] if x['record']['id']=='CFM_691')
        for o in prior['official_observations']:
            if o['card_id']=='CFM_691':batch.check_face(original,o['face'],o['locale'],prior['display_normalizations']['CFM_691'])

    def test_restored_jade_display_rejects_dropped_or_changed_rule_body_and_unpinned_source(self):
        d=load_batch();raw=next(x['record'] for x in d['dependencies'] if x['record']['id']==SWARMER)
        for o in [x for x in d['official_observations'] if x['card_id']==SWARMER]:
            for changed in ('<b>潜行</b>',o['face']['text']+' Draw 2 cards.'):
                face=deepcopy(o['face']);face['text']=changed
                with self.assertRaises(ValueError):batch.check_face(raw,face,o['locale'],DISPLAY[SWARMER])
            source=deepcopy(raw);source['text']+=' 抽两张牌。'
            with self.assertRaises(ValueError):batch.check_face(source,o['face'],o['locale'],DISPLAY[SWARMER])
            with self.assertRaises(ValueError):batch.check_face(raw,o['face'],o['locale'],{'@':''})

    def test_thirteen_native_hand_entries_pay_once_and_preserve_original_source_bodies(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g=self.game((cid,));source=self.play(g,cid);e=g.state.entities[source];c=g.registry.card(cid)
                self.assertEqual((e.attack,e.health,g.state.players[1].mana),(c.attack,c.health,9))

    def test_rabbit_copies_original_current_hand_buff_into_one_new_body_without_battlecry(self):
        g=self.game((HAND_BUFF,RABBIT));self.play(g,HAND_BUFF);source=self.play(g,RABBIT)
        self.assertEqual(self.ids(g,zone='board'),(RABBIT,RABBIT))
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(3,4) for i in g.state.players[1].board))
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(g.state.battlecry_history[0].source_id,source)

    def test_rabbit_full_board_has_only_the_real_paid_entry(self):
        g=self.game((RABBIT,),board=(RAVEN,)*6);self.play(g,RABBIT)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.ids(g,zone='board').count(RABBIT),1)

    def test_zergling_fixed_printed_child_does_not_inherit_parent_buff_or_run_battlecry(self):
        g=self.game((HAND_BUFF,ZERGLING));self.play(g,HAND_BUFF);source=self.play(g,ZERGLING)
        board=g.state.players[1].board;child=next(i for i in board if i!=source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,4))
        self.assertEqual((g.state.entities[child].attack,g.state.entities[child].health),(1,1));self.assertEqual(len(g.state.battlecry_history),1)

    def test_fiend_summons_two_real_felbeasts_then_damages_own_hero(self):
        g=self.game((FIEND,));self.play(g,FIEND)
        self.assertEqual(self.ids(g,zone='board'),(FIEND,FELBEAST,FELBEAST));self.assertEqual(self.hero(g).health,27)
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_fiend_capacity_never_skips_original_hero_damage(self):
        for n,children in ((5,1),(6,0)):
            g=self.game((FIEND,),board=(RAVEN,)*n);self.play(g,FIEND)
            self.assertEqual(self.ids(g,zone='board').count(FELBEAST),children);self.assertEqual(self.hero(g).health,27)

    def test_catch_opposing_named_grub_and_actual_rush_combat(self):
        g=self.game((CATCH,));source=self.play(g,CATCH);child=g.state.players[2].board[0]
        self.assertEqual(self.ids(g,2,'board'),(GRUB,));self.assertEqual((g.state.entities[child].attack,g.state.entities[child].health),(2,1))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
        g.apply(Attack(1,source,child));self.assertFalse(g.state.players[2].board);self.assertEqual(g.state.entities[source].health,1)

    def test_taskmaster_natural_death_gives_opponent_zero_attack_taunt_and_full_board_skips(self):
        for full in (False,True):
            g=self.game((KILL,),board=(TASKMASTER,),enemy_board=(RAVEN,)*7 if full else ())
            self.play(g,KILL,self.entity(g,TASKMASTER,zone='board').id)
            if full:self.assertEqual(len(g.state.players[2].board),7)
            else:
                child=self.entity(g,MINER,2,'board');self.assertEqual((child.attack,child.health),(0,3));self.assertIn(Keyword.TAUNT,child.keywords)

    def test_zombie_two_stage_death_chain_uses_new_physical_bodies_in_original_slot(self):
        g=self.game((KILL,KILL,KILL),board=(RAVEN,ZOMBIE,YETI));ids=[]
        for current,next_card in ((ZOMBIE,ARMLESS),(ARMLESS,EMPTY)):
            old=self.entity(g,current,zone='board').id;ids.append(old);self.play(g,KILL,old)
            self.assertEqual(self.ids(g,zone='board'),(RAVEN,next_card,YETI))
        last=self.entity(g,EMPTY,zone='board').id;ids.append(last);self.play(g,KILL,last)
        self.assertEqual(self.ids(g,zone='board'),(RAVEN,YETI));self.assertEqual(len(set(ids)),3)

    def test_active_living_zombie_deathrattle_keeps_carrier_and_places_child_to_its_right(self):
        g=self.game((ACTIVE,),board=(RAVEN,ZOMBIE,YETI));source=self.entity(g,ZOMBIE,zone='board').id;self.play(g,ACTIVE,source)
        self.assertEqual(self.ids(g,zone='board'),(RAVEN,ZOMBIE,ARMLESS,YETI));self.assertFalse(g.state.death_history)

    def test_silenced_named_deathrattles_do_not_issue_rewards_or_shuffles(self):
        for cid in (ZOMBIE,HATCHLING,CONDUCTOR,SALESMAN,SWARMER):
            g=self.game((SILENCE,KILL),board=(cid,));source=self.entity(g,cid,zone='board').id;deck=tuple(g.state.players[1].deck)
            self.play(g,SILENCE,source);self.play(g,KILL,source)
            self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[1].hand)
            self.assertEqual(tuple(g.state.players[1].deck),deck);self.assertFalse(g.state.jade_history)

    def test_hatchling_shuffles_new_printed_four_five_then_draws_and_really_plays_it(self):
        g=self.game((HATCHLING,KILL,DRAW),deck=());source=self.play(g,HATCHLING);self.play(g,KILL,source)
        child=g.state.players[1].deck[0];self.assertNotEqual(child,source);self.assertEqual(self.ids(g,zone='deck'),(PATRIARCH,))
        self.assertEqual((g.state.entities[child].attack,g.state.entities[child].health),(4,5))
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.play(g,DRAW);self.play(g,PATRIARCH)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(self.ids(g,zone='board'),(PATRIARCH,))

    def test_transferred_hatchling_natural_death_uses_current_controller_deck(self):
        g=self.game((TAKE,KILL),board=(HATCHLING,),deck=(),enemy_deck=());source=self.entity(g,HATCHLING,zone='board').id
        self.play(g,TAKE,source);self.play(g,KILL,source)
        self.assertFalse(g.state.players[1].deck);self.assertEqual(self.ids(g,2,'deck'),(PATRIARCH,))

    def test_jailer_shuffles_two_distinct_fragments_in_one_original_semantic_operation(self):
        g=self.game((JAILER,),deck=());self.play(g,JAILER)
        self.assertEqual(self.ids(g,zone='deck'),(FRAGMENT,FRAGMENT));self.assertEqual(len(set(g.state.players[1].deck)),2)
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertFalse(g.state.players[1].hand)

    def test_fragment_real_draw_cast_heals_two_replaces_draw_and_is_not_added_to_hand(self):
        g=self.game((HURT,DRAW),deck=(FRAGMENT,NOOP),board=(POWER,));self.play(g,HURT);self.play(g,DRAW)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(self.ids(g),(NOOP,));self.assertFalse(g.state.players[1].deck)
        self.assertEqual(len([r for r in g.state.cast_history if r.card_id==FRAGMENT]),1);self.assertEqual(g.state.players[1].mana,10)

    def test_fragment_replacement_draw_empty_deck_uses_original_fatigue(self):
        g=self.game((HURT,DRAW),deck=(FRAGMENT,));self.play(g,HURT);self.play(g,DRAW)
        self.assertEqual(self.hero(g).health,22);self.assertEqual(g.state.players[1].fatigue,1);self.assertFalse(g.state.players[1].hand)

    def test_fragment_manual_zero_cost_cast_heals_without_replacement_draw(self):
        g=self.game((HURT,FRAGMENT));self.play(g,HURT);deck=tuple(g.state.players[1].deck);self.play(g,FRAGMENT)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(tuple(g.state.players[1].deck),deck);self.assertFalse(g.state.draw_history)

    def test_squirrel_shuffles_four_existing_acorns_and_preserves_original_token_definitions(self):
        g=self.game((KILL,),board=(SQUIRREL,),deck=());self.play(g,KILL,self.entity(g,SQUIRREL,zone='board').id)
        self.assertEqual(self.ids(g,zone='deck'),(ACORN,)*4);self.assertEqual(len(set(g.state.players[1].deck)),4)
        self.assertEqual(len(g.state.deck_shuffle_history),1)
        g=self.game((DRAW,),deck=(ACORN,NOOP));self.play(g,DRAW)
        self.assertEqual(self.ids(g,zone='board'),(SATISFIED,));self.assertEqual(self.ids(g),(NOOP,))
        child=self.entity(g,SATISFIED,zone='board');self.assertEqual((child.attack,child.health),(2,1))

    def test_restored_and_original_swarmer_share_existing_player_jade_growth(self):
        g=self.game((KILL,SWARMER,KILL),board=('CFM_691',));self.play(g,KILL,self.entity(g,'CFM_691',zone='board').id)
        source=self.play(g,SWARMER);self.assertIn(Keyword.STEALTH,g.state.entities[source].keywords);self.play(g,KILL,source)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[1,2]);self.assertEqual(len(g.state.jade_history),2)

    def test_named_hand_rewards_create_complete_sludge_and_tradeable_oil(self):
        for parent,reward in ((CONDUCTOR,SLUDGE),(SALESMAN,OIL)):
            g=self.game((KILL,),board=(parent,));self.play(g,KILL,self.entity(g,parent,zone='board').id)
            self.assertEqual(self.ids(g),(reward,));self.assertIsNotNone(g.registry.card(reward).on_play)
        self.assertEqual(g.registry.card(OIL).hand_actions[0].kind,'trade')

    def test_sludge_played_real_three_mana_spell_selects_lowest_health_and_gets_spell_damage(self):
        g=self.game((SLUDGE,),board=(POWER,),enemy_board=(YETI,));self.play(g,SLUDGE)
        self.assertFalse(g.state.players[2].board);self.assertEqual(self.hero(g,2).health,30);self.assertEqual(g.state.players[1].mana,7)

    def test_sludge_tied_lowest_enemies_are_one_random_physical_choice(self):
        g=self.game((SLUDGE,),enemy_board=(MINER,MINER));original=set(g.state.players[2].board);rng=g._rng.getstate()
        self.play(g,SLUDGE);self.assertEqual(len(g.state.players[2].board),1)
        self.assertTrue(set(g.state.players[2].board)<original);self.assertEqual(self.entity(g,MINER,2,'board').health,3)
        self.assertEqual(self.hero(g,2).health,30);self.assertNotEqual(g._rng.getstate(),rng)

    def test_sludge_discard_and_hand_or_deck_destruction_are_independent_noncast_four_damage(self):
        for entry in (DISCARD,BREAK_HAND,BREAK_DECK):
            g=self.game((entry,) if entry==BREAK_DECK else (entry,SLUDGE),board=(POWER,),
                deck=(SLUDGE,) if entry==BREAK_DECK else (NOOP,),enemy_board=(YETI,))
            self.play(g,entry);self.assertEqual(self.entity(g,YETI,2,'board').health,1)
            self.assertFalse([r for r in g.state.cast_history if r.card_id==SLUDGE]);self.assertEqual(g.state.players[1].mana,10)

    def test_countered_sludge_play_has_no_lowest_target_damage(self):
        g=self.game((SLUDGE,),enemy_hand=(COUNTER,),enemy_board=(YETI,),active=2)
        self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.play(g,SLUDGE)
        self.assertEqual(self.entity(g,YETI,2,'board').health,5);self.assertEqual(g.state.players[1].mana,7)

    def test_burned_sludge_reward_executes_its_destroyed_body_for_original_recipient(self):
        g=self.game((NOOP,)*10,board=(CONDUCTOR,),enemy_hand=(KILL,),active=2)
        self.play(g,KILL,self.entity(g,CONDUCTOR,zone='board').id,player=2)
        self.assertEqual(self.ids(g),(NOOP,)*10);self.assertEqual(self.hero(g,2).health,26)

    def test_oil_real_zero_base_damage_can_be_modified_by_existing_spell_damage(self):
        for board,health in (((),30),((POWER,),29)):
            g=self.game((OIL,),board=board);self.play(g,OIL,g.state.players[2].hero_id)
            self.assertEqual(self.hero(g,2).health,health);self.assertEqual(g.state.players[1].mana,10)

    def test_oil_trade_really_pays_one_draws_other_physical_card_and_never_casts(self):
        g=self.game((OIL,),deck=(NOOP,));source=self.entity(g,OIL).id;g.apply(UseHandAction(1,source,'trade'))
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(self.ids(g),(NOOP,));self.assertIn(source,g.state.players[1].deck)
        self.assertFalse(g.state.cast_history);self.assertEqual(self.hero(g,2).health,30)

    def test_oil_required_target_and_empty_deck_trade_errors_are_atomic(self):
        g=self.game((OIL,),deck=());before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,OIL)
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(IllegalAction):g.apply(UseHandAction(1,self.entity(g,OIL).id,'trade'))
        self.assertEqual(g.snapshot(),before)

    def test_loud_original_completed_hero_attack_copies_current_material_without_moving_source(self):
        g=self.game((BOARD_BUFF,),board=(LOUD,));source=self.entity(g,LOUD,zone='board').id;self.play(g,BOARD_BUFF,source)
        g.apply(Attack(1,source,g.state.players[2].hero_id));self.assertEqual(self.ids(g),(LOUD,));copy=self.entity(g,LOUD)
        self.assertNotEqual(copy.id,source);self.assertEqual((copy.attack,copy.health),(3,4));self.assertIn(source,g.state.players[1].board)
        self.assertEqual(self.hero(g,2).health,27);self.portable(g)

    def test_loud_minion_attack_and_ordinary_damage_do_not_issue_hand_copies(self):
        g=self.game(board=(LOUD,),enemy_board=(MINER,));source=self.entity(g,LOUD,zone='board').id
        g.apply(Attack(1,source,self.entity(g,MINER,2,'board').id));self.assertFalse(g.state.players[1].hand)
        g=self.game((HURT,),board=(LOUD,));self.play(g,HURT);self.assertFalse(g.state.players[1].hand)

    def test_loud_full_hand_overflow_keeps_original_attacker(self):
        g=self.game((NOOP,)*10,board=(LOUD,));source=self.entity(g,LOUD,zone='board').id
        g.apply(Attack(1,source,g.state.players[2].hero_id));self.assertEqual(self.ids(g),(NOOP,)*10)
        self.assertEqual(self.ids(g,zone='board'),(LOUD,));self.assertEqual(self.hero(g,2).health,29)

    def test_fixed_summon_wait_restores_original_unfinished_second_body_and_hero_damage(self):
        g=self.game((FIEND,),mode='wait_summon');self.play(g,FIEND);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.drain(g);self.assertEqual(self.ids(g,zone='board'),(FIEND,FELBEAST,FELBEAST));self.assertEqual(self.hero(g).health,27)

    def test_semantic_shuffle_wait_restores_two_original_insertions_without_duplicate_operation(self):
        g=self.game((JAILER,),deck=(),mode='wait_deck');self.play(g,JAILER);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.drain(g);self.assertEqual(self.ids(g,zone='deck'),(FRAGMENT,FRAGMENT));self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_natural_hand_reward_wait_restores_original_dead_source_and_private_delivery(self):
        g=self.game((KILL,),board=(CONDUCTOR,),mode='wait_hand');self.play(g,KILL,self.entity(g,CONDUCTOR,zone='board').id)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.drain(g);self.assertEqual(self.ids(g),(SLUDGE,))
        other=g.for_player(2).observe();self.assertNotIn(SLUDGE,str(other))

    def test_sludge_random_damage_wait_restores_original_cast_payment_and_does_not_hit_twice(self):
        g=self.game((SLUDGE,),enemy_board=(YETI,),mode='wait_damage');self.play(g,SLUDGE)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.drain(g)
        self.assertEqual(self.entity(g,YETI,2,'board').health,1);self.assertEqual(g.state.players[1].mana,7)

    def test_late_native_failures_restore_creation_shuffle_hand_copy_and_passive_damage(self):
        for kind in ('summon','shuffle','copy','played','discarded','destroyed'):
            with self.subTest(entry=kind):
                if kind=='summon':g=self.game((FIEND,),mode='fail');action=lambda:self.play(g,FIEND)
                elif kind=='shuffle':
                    g=self.game((KILL,),board=(HATCHLING,),deck=(),mode='fail');action=lambda:self.play(g,KILL,self.entity(g,HATCHLING,zone='board').id)
                elif kind=='copy':
                    g=self.game(board=(LOUD,),mode='fail');action=lambda:g.apply(Attack(1,self.entity(g,LOUD,zone='board').id,g.state.players[2].hero_id))
                elif kind=='played':g=self.game((SLUDGE,),enemy_board=(YETI,),mode='fail');action=lambda:self.play(g,SLUDGE)
                elif kind=='discarded':g=self.game((DISCARD,SLUDGE),enemy_board=(YETI,),mode='fail');action=lambda:self.play(g,DISCARD)
                else:g=self.game((BREAK_DECK,),deck=(SLUDGE,),enemy_board=(YETI,),mode='fail');action=lambda:self.play(g,BREAK_DECK)
                before=g.snapshot()
                with self.assertRaises(ResolutionError):action()
                self.assertEqual(g.snapshot(),before)

    def test_failing_original_choice_retains_already_accepted_paid_wait(self):
        g=self.game((FIEND,),mode='wait_summon');self.play(g,FIEND);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,9)

    def test_actual_flashback_contains_all_thirteen_members_and_runs_no_summoned_battlecries(self):
        g=self.game((FLASHBACK,));self.play(g,FLASHBACK);row,=g.state.pool_summon_history
        self.assertEqual({x.card_id for x in row.spec.basis.candidates},set(LEAVES));self.assertEqual(len(g.state.players[1].board),2)
        self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.players[1].hand)

    def test_experimental_past_is_not_a_production_pool_or_new_standard_root_claim(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        r=build_registry();self.assertNotIn('constructed.past.cards',r.pools)
        self.assertFalse(set(DEPENDENCIES)&set(build_cn37_launch_candidate_format().root_card_ids))


if __name__=='__main__':unittest.main()
